"""Shutdown-signal handling.

Found by running the real thing: `except KeyboardInterrupt` is not enough.
SIGTERM was not handled at all (CI, `timeout`, `docker stop`, IDE stop buttons
all send it), and a process started from a non-interactive shell inherits
SIGINT as SIG_IGN, so Python never raises KeyboardInterrupt either. Both cases
left `langgraph dev` and `next dev` orphaned with their ports held.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.timeout(90),
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal semantics"),
]

# A supervisor run in a child interpreter, so we can signal it like a real user
# or CI runner would. The child writes a marker file only if teardown ran.
DRIVER = textwrap.dedent(
    """
    import os, sys, time
    from pathlib import Path
    from rich.console import Console
    from agentctl.core.supervisor import ProcessSpec, Supervisor

    marker = Path(sys.argv[1])
    pidfile = Path(sys.argv[2])
    console = Console(file=open(os.devnull, "w"))

    spec = ProcessSpec(name="child", command=[sys.executable, "-c",
        "import time\\nwhile True: time.sleep(0.2)"], cwd=Path.cwd())

    with Supervisor(console) as sup:
        sup.start([spec])
        pidfile.write_text(str(sup.processes[0].popen.pid))
        Path(str(marker) + ".ready").write_text("1")
        sup.wait()
    marker.write_text("torn-down")
    """
)


def _run_driver(tmp_path: Path, preexec=None) -> tuple[subprocess.Popen, Path, Path]:
    marker = tmp_path / "marker"
    pidfile = tmp_path / "child.pid"
    driver = tmp_path / "driver.py"
    driver.write_text(DRIVER)
    proc = subprocess.Popen(
        [sys.executable, str(driver), str(marker), str(pidfile)],
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=preexec,
    )
    for _ in range(200):
        if (tmp_path / "marker.ready").exists():
            break
        time.sleep(0.05)
    return proc, marker, pidfile


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _assert_clean_shutdown(proc, marker, pidfile):
    child_pid = int(pidfile.read_text())
    proc.wait(timeout=30)
    assert marker.exists(), "teardown never ran — the signal was not handled"
    for _ in range(40):
        if not _pid_alive(child_pid):
            break
        time.sleep(0.1)
    assert not _pid_alive(child_pid), "child survived — this is the port-leak bug"


def test_sigterm_tears_down(tmp_path):
    """SIGTERM previously killed us outright, orphaning every child."""
    proc, marker, pidfile = _run_driver(tmp_path)
    proc.send_signal(signal.SIGTERM)
    _assert_clean_shutdown(proc, marker, pidfile)


def test_sigint_tears_down(tmp_path):
    proc, marker, pidfile = _run_driver(tmp_path)
    proc.send_signal(signal.SIGINT)
    _assert_clean_shutdown(proc, marker, pidfile)


def test_sighup_tears_down(tmp_path):
    """Closing the terminal must not leave the agent running."""
    proc, marker, pidfile = _run_driver(tmp_path)
    proc.send_signal(signal.SIGHUP)
    _assert_clean_shutdown(proc, marker, pidfile)


def test_sigint_works_when_inherited_as_ignored(tmp_path):
    """The exact condition that broke end-to-end teardown.

    A non-interactive shell sets SIGINT to SIG_IGN for background children.
    Python then skips installing its default handler, so `except
    KeyboardInterrupt` can never fire; the handler must be set unconditionally.
    """

    def ignore_sigint():
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    proc, marker, pidfile = _run_driver(tmp_path, preexec=ignore_sigint)
    proc.send_signal(signal.SIGINT)
    _assert_clean_shutdown(proc, marker, pidfile)
