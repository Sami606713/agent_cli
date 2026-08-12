"""Process supervisor for `langctl dev`.

Runs several long-lived child processes as one foreground unit:

* each child is spawned into **its own process group** (POSIX) or job-style group
  (Windows), so teardown reaches grandchildren — ``langgraph dev`` spawns a
  uvicorn reloader child, and killing only the parent leaves port 2024 held;
* children start **sequentially behind a readiness gate**, so the frontend never
  boots against a dead Agent Server;
* stdout/stderr are merged into one prefixed, colourised stream;
* teardown is guaranteed on any exit path — normal, exception, or Ctrl-C — and
  escalates SIGTERM → SIGKILL after a grace period.

Nothing here is LangChain-specific; :mod:`langctl.commands.dev` supplies the
commands and the health URLs.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

from .health import WaitResult, wait_for_http

IS_WINDOWS = sys.platform == "win32"

#: How long a child gets to exit after SIGTERM before we SIGKILL it.
GRACE_PERIOD = 5.0

#: Lines of recent output kept per process, for the crash report.
LOG_TAIL_LINES = 40


@dataclass
class ProcessSpec:
    """Declarative description of one child process."""

    name: str
    command: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    color: str = "cyan"
    #: URL polled before the *next* process starts. None means "no gate".
    health_url: str | None = None
    #: Seconds to wait for health_url before declaring failure.
    health_timeout: float = 90.0
    #: Human-readable hint shown if this process fails to become healthy.
    ready_hint: str | None = None
    #: Called with every output line. Used to scrape a value a process only
    #: announces in prose — a tunnel's public URL, for instance.
    on_line: Callable[[str], None] | None = None
    #: When False, output is captured for the crash report but not printed.
    #: Tunnel clients are chatty and their logs bury the app's own output.
    echo: bool = True


class ManagedProcess:
    """One child process plus its output pump."""

    def __init__(self, spec: ProcessSpec, console: Console, write_lock: threading.Lock):
        self.spec = spec
        self._console = console
        self._write_lock = write_lock
        self.popen: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._tail: deque[str] = deque(maxlen=LOG_TAIL_LINES)
        self._stopping = threading.Event()

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        env = {**os.environ, **self.spec.env}
        # Unbuffered child output; without this, Python children buffer stdout when
        # it is a pipe and their logs appear only at exit.
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("FORCE_COLOR", "1")

        kwargs: dict = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            # New session => new process group => signals reach grandchildren.
            kwargs["start_new_session"] = True

        try:
            self.popen = subprocess.Popen(
                self.spec.command,
                cwd=str(self.spec.cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                **kwargs,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"{self.spec.command[0]}: command not found (needed for '{self.spec.name}')"
            ) from exc

        self._reader = threading.Thread(
            target=self._pump, name=f"log-{self.spec.name}", daemon=True
        )
        self._reader.start()

    def _pump(self) -> None:
        assert self.popen is not None and self.popen.stdout is not None
        prefix = f"[{self.spec.color}]{self.spec.name:>5}[/{self.spec.color}] [dim]│[/dim] "
        try:
            for line in self.popen.stdout:
                line = line.rstrip("\n")
                self._tail.append(line)
                if self.spec.on_line is not None:
                    try:
                        self.spec.on_line(line)
                    except Exception:
                        pass  # an observer must never kill the log pump
                if self._stopping.is_set() or not self.spec.echo:
                    continue
                # Rich's console is not reentrant across threads; serialise writes
                # so two children cannot interleave mid-line.
                with self._write_lock:
                    self._console.print(prefix + _escape(line), highlight=False, soft_wrap=True)
        except (ValueError, OSError):
            pass  # pipe closed during teardown

    @property
    def returncode(self) -> int | None:
        return self.popen.poll() if self.popen else None

    def is_running(self) -> bool:
        return self.popen is not None and self.popen.poll() is None

    def log_tail(self, lines: int = LOG_TAIL_LINES) -> str:
        return "\n".join(list(self._tail)[-lines:])

    def stop(self, grace: float = GRACE_PERIOD) -> None:
        """Terminate the whole process group, escalating if it does not go."""
        if self.popen is None or self.popen.poll() is not None:
            return
        self._stopping.set()

        try:
            if IS_WINDOWS:
                self.popen.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                os.killpg(os.getpgid(self.popen.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            # Already gone, or we cannot reach the group; fall back to the child.
            try:
                self.popen.terminate()
            except Exception:
                pass

        try:
            self.popen.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            pass

        try:
            if IS_WINDOWS:
                self.popen.kill()
            else:
                os.killpg(os.getpgid(self.popen.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                self.popen.kill()
            except Exception:
                pass
        try:
            self.popen.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass


def _escape(text: str) -> str:
    """Neutralise Rich markup in child output so a stray '[' cannot crash logging."""
    return text.replace("[", "\\[")


class StartupFailure(RuntimeError):
    """A child died or never became healthy during startup."""

    def __init__(self, process: ManagedProcess, reason: str):
        super().__init__(reason)
        self.process = process
        self.reason = reason


#: Signals that mean "shut down". SIGTERM is not optional: CI runners, `timeout`,
#: `docker stop`, and IDE stop buttons all send it, and the default disposition
#: kills us instantly — orphaning every child and leaving their ports held.
SHUTDOWN_SIGNALS = (signal.SIGINT, signal.SIGTERM) + (
    () if IS_WINDOWS else (signal.SIGHUP,)
)


class Supervisor:
    """Starts a list of processes in order, then blocks until one exits."""

    def __init__(self, console: Console):
        self.console = console
        self.processes: list[ManagedProcess] = []
        self._write_lock = threading.Lock()
        self._stopped = False
        self._shutdown = threading.Event()
        self._previous_handlers: dict[int, object] = {}

    def __enter__(self) -> Supervisor:
        self._install_signal_handlers()
        return self

    def __exit__(self, *exc_info) -> None:
        # Teardown on *every* path, including exceptions and KeyboardInterrupt.
        self.stop_all()
        self._restore_signal_handlers()

    # ---- signals ---------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Take over the shutdown signals for the lifetime of the run.

        Explicit handlers rather than ``except KeyboardInterrupt`` because that
        only covers one of the three ways this process gets asked to stop, and
        it does not even cover SIGINT reliably: a process started from a
        non-interactive shell inherits SIGINT as ``SIG_IGN``, and Python then
        never installs its default handler, so no ``KeyboardInterrupt`` is ever
        raised. Setting the handler unconditionally overrides that inheritance.
        """

        def handler(signum: int, _frame) -> None:
            self._shutdown.set()

        for sig in SHUTDOWN_SIGNALS:
            try:
                self._previous_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, handler)
            except (ValueError, OSError):
                # Not the main thread, or unsupported on this platform.
                pass

    def _restore_signal_handlers(self) -> None:
        for sig, previous in self._previous_handlers.items():
            try:
                signal.signal(sig, previous)  # type: ignore[arg-type]
            except (ValueError, OSError, TypeError):
                pass
        self._previous_handlers.clear()

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown.is_set()

    def start(
        self,
        specs: list[ProcessSpec],
        on_wait: Callable[[ProcessSpec, float], None] | None = None,
    ) -> None:
        """Start each spec in order, gating on health before moving to the next."""
        for spec in specs:
            proc = ManagedProcess(spec, self.console, self._write_lock)
            self.processes.append(proc)
            proc.start()

            if spec.health_url is None:
                # No gate: still catch an immediate crash (bad flag, missing module).
                time.sleep(0.3)
                if not proc.is_running():
                    raise StartupFailure(
                        proc, f"exited immediately with code {proc.returncode}"
                    )
                continue

            result = self._await_health(proc, spec, on_wait)
            if not result.ok:
                raise StartupFailure(proc, result.last_error or "did not become healthy")

    def _await_health(
        self,
        proc: ManagedProcess,
        spec: ProcessSpec,
        on_wait: Callable[[ProcessSpec, float], None] | None,
    ) -> WaitResult:
        def abort_if_dead() -> str | None:
            # Short-circuit the wait when the child is already gone, so an import
            # error surfaces in a second instead of after the full timeout.
            if not proc.is_running():
                return f"process exited with code {proc.returncode} before becoming ready"
            return None

        return wait_for_http(
            spec.health_url or "",
            timeout=spec.health_timeout,
            on_progress=(lambda e: on_wait(spec, e)) if on_wait else None,
            should_abort=abort_if_dead,
        )

    def wait(self, poll_interval: float = 0.25) -> ManagedProcess | None:
        """Block until any child exits or shutdown is requested.

        Returns the process that exited first, or None for a requested shutdown.
        """
        try:
            while not self._shutdown.is_set():
                for proc in self.processes:
                    if not proc.is_running():
                        return proc
                # Event.wait rather than sleep: a signal handler setting the
                # event wakes this immediately instead of up to poll_interval late.
                self._shutdown.wait(poll_interval)
        except KeyboardInterrupt:
            # Still possible if a handler could not be installed.
            pass
        return None

    def stop_all(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        # Reverse order: dependents (frontend) go down before dependencies (agent),
        # which avoids a burst of proxy connection errors in the final log lines.
        for proc in reversed(self.processes):
            proc.stop()
