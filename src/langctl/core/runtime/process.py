"""Running child processes the same way on every platform.

`subprocess` with `text=True` and no explicit encoding decodes child output
using the *locale* encoding. On Linux and macOS that is UTF-8 and nothing goes
wrong. On Windows it is the ANSI codepage, and the tools langctl supervises —
npm, Next.js, uv, langgraph — all emit UTF-8:

    ▲ Next.js 15.5.4
    ✓ Ready in 1200ms

Decoding those bytes with the wrong codec fails in two different ways, and
both were reproduced before this module existed:

    cp1252, cp1251   mojibake — "â–² Next.js"; no exception
    cp932, cp949     UnicodeDecodeError on the first line

The second case is the damaging one. `UnicodeDecodeError` is a subclass of
`ValueError`, so the log pump's `except (ValueError, OSError)` swallowed it and
the reader thread died on the first line of output. Nothing crashed and nothing
was logged: a failing child produced an empty error panel, and `langctl share`
never saw the URL it was waiting for.

Reading UTF-8 explicitly, and replacing anything undecodable rather than
raising, makes child output behave identically everywhere.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

#: Decode child output as UTF-8 on every platform. `errors="replace"` because a
#: stray byte in a log line must never take down the process reading it.
TEXT_IO: dict[str, Any] = {
    "text": True,
    "encoding": "utf-8",
    "errors": "replace",
}


def run(
    argv: list[str],
    *,
    cwd: Path | str | None = None,
    capture: bool = True,
    timeout: float | None = None,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run *argv* to completion, decoding its output as UTF-8.

    A thin wrapper rather than a framework: it exists so no call site can
    forget the encoding, which is the whole bug this module addresses.
    """
    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=capture,
        timeout=timeout,
        check=check,
        env=env,
        **TEXT_IO,
    )
