"""Child process output must decode identically on every platform.

`text=True` without an explicit encoding uses the locale codec. On Linux and
macOS that is UTF-8; on Windows it is the ANSI codepage, and every tool langctl
supervises emits UTF-8 — Next.js opens with "▲ Next.js" and "✓ Ready in".

The failure has two shapes, both reproduced below against real subprocesses:

    cp1252 / cp1251   silently garbles the line
    cp932  / cp949    raises UnicodeDecodeError on the first line

The second is why this file exists. `UnicodeDecodeError` subclasses
`ValueError`, so the supervisor's `except (ValueError, OSError)` caught it and
the log-reader thread died on line one — no crash, no logs, and an empty error
panel when a child failed to start.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from langctl.core.runtime.process import TEXT_IO, run

SRC = Path(__file__).resolve().parents[1] / "src" / "langctl"

#: What Next.js prints within the first second of `next dev`.
NEXT_BANNER = "▲ Next.js 15.5.4"
READY = "✓ Ready in 1200ms"


def emitter() -> list[str]:
    return [sys.executable, "-c", f"print({NEXT_BANNER!r}); print({READY!r}); print('third')"]


class TestTheFailureIsReal:
    """Guard rails are worthless if the bug they guard against cannot happen."""

    @pytest.mark.parametrize("codec", ["cp932", "cp949"])
    def test_a_windows_codec_kills_the_reader(self, codec):
        proc = subprocess.Popen(
            emitter(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, encoding=codec,
        )
        lines, died = [], None
        try:
            for line in proc.stdout:
                lines.append(line)
        except ValueError as exc:  # the supervisor's own handler
            died = exc
        proc.wait()
        assert isinstance(died, UnicodeDecodeError)
        assert lines == [], "the reader dies before the first line is delivered"

    def test_a_western_codec_garbles_instead(self):
        proc = subprocess.Popen(
            emitter(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, encoding="cp1252",
        )
        out = proc.stdout.read()
        proc.wait()
        assert "â–²" in out and NEXT_BANNER not in out


class TestTheFixHolds:
    def test_utf8_survives_the_same_input(self):
        proc = subprocess.Popen(
            emitter(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, **TEXT_IO
        )
        lines = [line.rstrip("\n") for line in proc.stdout]
        proc.wait()
        assert lines == [NEXT_BANNER, READY, "third"]

    def test_undecodable_bytes_replace_rather_than_raise(self):
        # A truncated multi-byte sequence: real when a child is killed mid-write.
        argv = [
            sys.executable, "-c",
            "import sys; sys.stdout.buffer.write(b'ok \\xe2\\x96 broken\\n')",
        ]
        result = run(argv)
        assert result.returncode == 0
        assert "ok" in result.stdout and "broken" in result.stdout

    def test_run_captures_stderr_too(self):
        argv = [sys.executable, "-c", "import sys; sys.stderr.write('▲ boom')"]
        assert "▲ boom" in run(argv).stderr


class TestNoCallSiteForgets:
    """A grep test, because the bug is an omission rather than a wrong value."""

    def test_no_bare_text_true_anywhere_in_the_package(self):
        offenders = []
        for path in SRC.rglob("*.py"):
            if path.name == "process.py":
                continue  # documents the anti-pattern in prose
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                keywords = {k.arg for k in node.keywords if k.arg}
                if "text" in keywords and "encoding" not in keywords:
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
        assert not offenders, (
            "pass **TEXT_IO (or use process.run) instead of a bare text=True: "
            + ", ".join(offenders)
        )

    def test_no_read_text_without_encoding(self):
        offenders = []
        for path in SRC.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("read_text", "write_text")
                    and not any(k.arg == "encoding" for k in node.keywords)
                ):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
        assert not offenders, (
            "Path.read_text/write_text default to the locale codec on Windows: "
            + ", ".join(offenders)
        )
