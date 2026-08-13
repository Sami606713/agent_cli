"""Resolving programs to a path before spawning them.

On Windows, `npm`, `pnpm`, `npx`, and many other Node tools are installed as
`.cmd` shims rather than `.exe` files. `CreateProcess` cannot launch those from
a bare name, so `subprocess.run(["npm", ...])` fails with

    FileNotFoundError: [WinError 2] The system cannot find the file specified

even though `npm` works fine in the same shell, and even though
`shutil.which("npm")` finds it. The fix is to spawn the *resolved path*
(`C:\\...\\npm.cmd`) rather than the name — `which` already knows the extension
because it consults PATHEXT.

POSIX is unaffected either way, so everything goes through here rather than
having two spawn paths that can drift.
"""

from __future__ import annotations

import shutil

from .errors import MissingDependency

#: Where to point someone whose tool is missing.
INSTALL_HINTS: dict[str, str] = {
    "npm": "Install Node.js 20+: https://nodejs.org",
    "pnpm": "Install pnpm: https://pnpm.io/installation",
    "npx": "Install Node.js 20+: https://nodejs.org",
    "uv": "Install uv: https://docs.astral.sh/uv/getting-started/installation/",
    "git": "Install git: https://git-scm.com/downloads",
    "docker": "Install Docker: https://docs.docker.com/get-docker/",
}


def find(name: str) -> str | None:
    """Absolute path to *name*, or None.

    Returns the path rather than the name so callers can hand it straight to
    subprocess — see the module docstring for why that matters on Windows.
    """
    return shutil.which(name)


def require(name: str) -> str:
    """Absolute path to *name*, or a typed error naming how to install it."""
    resolved = find(name)
    if resolved is None:
        raise MissingDependency(name, INSTALL_HINTS.get(name, f"Install {name}."))
    return resolved


def command(name: str, *args: str) -> list[str] | None:
    """Build an argv with *name* resolved, or None when it is not installed."""
    resolved = find(name)
    return None if resolved is None else [resolved, *args]


def package_manager() -> str | None:
    """Resolved path to pnpm, else npm, else None."""
    return find("pnpm") or find("npm")
