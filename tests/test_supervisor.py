"""Supervisor tests using real child processes.

These deliberately avoid mocks: the failure modes we care about (orphaned
grandchildren, ports left held, signals that do not reach the whole group) only
exist at the OS level and a mocked Popen would pass while the real thing leaks.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from rich.console import Console

from langctl.core.health import find_free_port, is_port_free, wait_for_http
from langctl.core.supervisor import ProcessSpec, StartupFailure, Supervisor

pytestmark = pytest.mark.timeout(60)

POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")


@pytest.fixture
def console() -> Console:
    # Quiet console: tests assert on behaviour, not on rendered output.
    return Console(file=open(os.devnull, "w"), force_terminal=False)


def http_server_spec(name: str, port: int, tmp_path: Path, delay: float = 0.0) -> ProcessSpec:
    """A child that serves /ok after *delay* seconds."""
    script = tmp_path / f"{name}_server.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import time, http.server, socketserver
            time.sleep({delay})
            class H(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200 if self.path == "/ok" else 404)
                    self.end_headers()
                    self.wfile.write(b"ok")
                def log_message(self, *a): pass
            socketserver.TCPServer.allow_reuse_address = True
            with socketserver.TCPServer(("127.0.0.1", {port}), H) as s:
                print("listening", flush=True)
                s.serve_forever()
            """
        )
    )
    return ProcessSpec(
        name=name,
        command=[sys.executable, str(script)],
        cwd=tmp_path,
        health_url=f"http://127.0.0.1:{port}/ok",
        health_timeout=20.0,
    )


class TestHealthGate:
    def test_second_process_starts_only_after_first_is_healthy(self, tmp_path, console):
        port = find_free_port(18100)
        marker = tmp_path / "started.txt"
        second = ProcessSpec(
            name="web",
            command=[sys.executable, "-c",
                     f"open({str(marker)!r},'w').write('x'); import time; time.sleep(30)"],
            cwd=tmp_path,
        )
        with Supervisor(console) as sup:
            sup.start([http_server_spec("agent", port, tmp_path, delay=1.0), second])
            # If the gate works, by the time start() returns the agent is serving.
            assert wait_for_http(f"http://127.0.0.1:{port}/ok", timeout=2).ok
            assert marker.exists(), "frontend should have started after the gate opened"

    def test_slow_backend_is_waited_for_not_failed(self, tmp_path, console):
        port = find_free_port(18110)
        with Supervisor(console) as sup:
            sup.start([http_server_spec("agent", port, tmp_path, delay=2.5)])
            assert sup.processes[0].is_running()

    def test_progress_callback_fires_while_waiting(self, tmp_path, console):
        port = find_free_port(18120)
        seen: list[float] = []
        with Supervisor(console) as sup:
            sup.start(
                [http_server_spec("agent", port, tmp_path, delay=1.5)],
                on_wait=lambda spec, elapsed: seen.append(elapsed),
            )
        assert seen, "on_wait should be called while the backend is starting"


class TestCrashHandling:
    def test_backend_crash_aborts_before_timeout(self, tmp_path, console):
        """A dead child must short-circuit the health wait, not burn the timeout."""
        spec = ProcessSpec(
            name="agent",
            command=[sys.executable, "-c", "import sys; sys.stderr.write('boom\\n'); sys.exit(3)"],
            cwd=tmp_path,
            health_url=f"http://127.0.0.1:{find_free_port(18130)}/ok",
            health_timeout=30.0,
        )
        started = time.monotonic()
        with Supervisor(console) as sup:
            with pytest.raises(StartupFailure) as excinfo:
                sup.start([spec])
        assert time.monotonic() - started < 10, "should abort on exit, not wait out the timeout"
        assert "exited with code 3" in excinfo.value.reason

    def test_crash_report_includes_child_output(self, tmp_path, console):
        """The backend's own traceback is the useful part of the error."""
        spec = ProcessSpec(
            name="agent",
            command=[sys.executable, "-c", "raise RuntimeError('bad import of my_tool')"],
            cwd=tmp_path,
            health_url=f"http://127.0.0.1:{find_free_port(18140)}/ok",
            health_timeout=15.0,
        )
        with Supervisor(console) as sup:
            with pytest.raises(StartupFailure) as excinfo:
                sup.start([spec])
            time.sleep(0.2)  # let the log pump drain
            assert "bad import of my_tool" in excinfo.value.process.log_tail()

    def test_immediate_exit_detected_without_health_url(self, tmp_path, console):
        spec = ProcessSpec(
            name="web", command=[sys.executable, "-c", "raise SystemExit(1)"], cwd=tmp_path
        )
        with Supervisor(console) as sup:
            with pytest.raises(StartupFailure, match="exited immediately"):
                sup.start([spec])

    def test_missing_binary_names_the_process(self, tmp_path, console):
        spec = ProcessSpec(name="web", command=["definitely-not-a-real-binary-xyz"], cwd=tmp_path)
        with Supervisor(console) as sup:
            with pytest.raises(FileNotFoundError, match="web"):
                sup.start([spec])

    def test_wait_returns_the_process_that_died(self, tmp_path, console):
        port = find_free_port(18150)
        short = ProcessSpec(
            name="web",
            command=[sys.executable, "-c", "import time; time.sleep(0.6)"],
            cwd=tmp_path,
        )
        with Supervisor(console) as sup:
            sup.start([http_server_spec("agent", port, tmp_path), short])
            dead = sup.wait(poll_interval=0.05)
            assert dead is not None and dead.spec.name == "web"


class TestTeardown:
    @POSIX_ONLY
    def test_grandchildren_are_killed(self, tmp_path, console):
        """`langgraph dev` spawns a reloader child; killing only the parent leaks it."""
        pidfile = tmp_path / "grandchild.pid"
        script = tmp_path / "parent.sh"
        script.write_text(
            f"#!/bin/sh\nsleep 300 &\necho $! > {pidfile}\nwait\n"
        )
        script.chmod(0o755)
        spec = ProcessSpec(name="agent", command=["/bin/sh", str(script)], cwd=tmp_path)

        with Supervisor(console) as sup:
            sup.start([spec])
            for _ in range(50):
                if pidfile.exists():
                    break
                time.sleep(0.1)
            grandchild = int(pidfile.read_text().strip())
            assert _pid_alive(grandchild)

        time.sleep(0.5)
        assert not _pid_alive(grandchild), "grandchild survived teardown — this leaks ports"

    def test_port_is_released_after_teardown(self, tmp_path, console):
        port = find_free_port(18160)
        with Supervisor(console) as sup:
            sup.start([http_server_spec("agent", port, tmp_path)])
            assert not is_port_free(port)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not is_port_free(port):
            time.sleep(0.1)
        assert is_port_free(port), "port still held after teardown"

    def test_teardown_runs_when_body_raises(self, tmp_path, console):
        port = find_free_port(18170)
        proc = None
        with pytest.raises(ValueError):
            with Supervisor(console) as sup:
                sup.start([http_server_spec("agent", port, tmp_path)])
                proc = sup.processes[0]
                raise ValueError("simulated failure inside dev command")
        assert proc is not None and not proc.is_running()

    def test_ignores_sigterm_child_and_escalates_to_sigkill(self, tmp_path, console):
        """A child that traps SIGTERM must still die."""
        script = tmp_path / "stubborn.py"
        script.write_text(
            textwrap.dedent(
                """
                import signal, time
                signal.signal(signal.SIGTERM, lambda *a: None)
                print("ready", flush=True)
                while True: time.sleep(0.2)
                """
            )
        )
        spec = ProcessSpec(name="agent", command=[sys.executable, str(script)], cwd=tmp_path)
        sup = Supervisor(console)
        sup.start([spec])
        proc = sup.processes[0]
        time.sleep(0.5)
        started = time.monotonic()
        sup.stop_all()
        assert not proc.is_running()
        assert time.monotonic() - started < 15

    def test_stop_all_is_idempotent(self, tmp_path, console):
        port = find_free_port(18180)
        sup = Supervisor(console)
        sup.start([http_server_spec("agent", port, tmp_path)])
        sup.stop_all()
        sup.stop_all()  # must not raise


class TestLogging:
    def test_rich_markup_in_child_output_does_not_crash(self, tmp_path, console):
        """Agent logs contain things like '[INFO]' and '[/path]'."""
        spec = ProcessSpec(
            name="agent",
            command=[sys.executable, "-c", r"print('[INFO] [/not-a-tag] [bold]x')"],
            cwd=tmp_path,
        )
        sup = Supervisor(console)
        proc_specs = [spec]
        with sup:
            try:
                sup.start(proc_specs)
            except StartupFailure:
                pass  # exits immediately by design; we only care that logging survived
            time.sleep(0.3)
            assert "[INFO]" in sup.processes[0].log_tail()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


class TestPortHelpers:
    def test_is_port_free_detects_bound_port(self):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            assert not is_port_free(s.getsockname()[1])

    def test_find_free_port_skips_occupied(self):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            taken = s.getsockname()[1]
            assert find_free_port(taken) != taken

    @pytest.mark.skipif(not shutil.which("ss"), reason="ss not available")
    def test_describe_port_holder_never_raises(self):
        from langctl.core.health import describe_port_holder

        assert describe_port_holder(1) is None or isinstance(describe_port_holder(1), str)


def test_wait_for_http_times_out_cleanly():
    port = find_free_port(18190)
    result = wait_for_http(f"http://127.0.0.1:{port}/ok", timeout=1.0)
    assert not result.ok and result.last_error


def test_subprocess_baseline_sanity():
    """Guard against a broken sandbox making every other test here meaningless."""
    assert subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True).returncode == 0
