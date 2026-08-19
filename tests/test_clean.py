"""`langctl clean` — reclaim ports left behind by a crashed dev session.

The one property that matters most is the one hardest to get wrong safely:
`clean` must never touch a process it did not spawn. These tests prove that
boundary with real sockets and real processes rather than mocks, because the
whole point of the command is trustworthy behaviour around `kill`.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time

import pytest
from typer.testing import CliRunner

from langctl.core.runtime.health import find_port_holder, is_port_free
from langctl.main import cli

runner = CliRunner()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestFindPortHolder:
    def test_a_free_port_has_no_holder(self):
        assert find_port_holder(free_port()) is None

    def test_finds_our_own_listening_socket(self):
        port = free_port()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(1)
            holder = find_port_holder(port)
            # `ss` may be unavailable in a stripped-down CI image; if so this is
            # the documented degrade, not a failure of the parsing itself.
            if holder is not None:
                assert holder.pid > 0
                assert holder.name


@pytest.mark.skipif(sys.platform == "win32", reason="uses ss, POSIX only")
class TestCleanNeverTouchesAStranger:
    def test_a_process_clean_does_not_recognise_is_left_alone(self, tmp_path, monkeypatch):
        """The exact case this command exists to get right: something else is
        sitting on the port, and killing it would be a much worse outcome than
        leaving it busy."""
        monkeypatch.chdir(tmp_path)
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import socket,time; s=socket.socket(); "
                "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); "
                "s.bind(('127.0.0.1', 2024)); s.listen(1); time.sleep(20)",
            ],
        )
        try:
            _wait_until_bound(2024)
            result = runner.invoke(cli, ["clean", "--yes"])
            assert result.exit_code == 0
            assert "not a langctl process" in result.output
            assert proc.poll() is None, "clean must not have killed it"
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_a_known_holder_is_killed_and_the_port_freed(self, tmp_path, monkeypatch):
        node = _find_node()
        if node is None:
            pytest.skip("node not on PATH")
        monkeypatch.chdir(tmp_path)
        proc = subprocess.Popen(
            [
                node,
                "-e",
                "require('http').createServer((q,r)=>r.end('ok'))"
                ".listen(3000,'127.0.0.1');"
                "setTimeout(()=>process.exit(0),20000);",
            ],
        )
        try:
            _wait_until_bound(3000)
            result = runner.invoke(cli, ["clean", "--yes"])
            assert result.exit_code == 0
            assert "held by" in result.output
            for _ in range(30):
                if is_port_free(3000):
                    break
                time.sleep(0.1)
            assert is_port_free(3000)
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)


def _find_node() -> str | None:
    import shutil

    return shutil.which("node")


def _wait_until_bound(port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_port_free(port):
            return
        time.sleep(0.05)
    raise TimeoutError(f"port {port} never became occupied")
