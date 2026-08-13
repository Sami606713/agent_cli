"""Locating and invoking the langgraph CLI.

Kept in one module because `langgraph deploy` is beta and its flags move: when
upstream changes, this is the only file that needs to.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from ..errors import MissingDependency

#: Flags and behaviour verified against langgraph-cli 0.4.x.
MIN_SUPPORTED = (0, 4)

INSTALL_HINT = (
    "Add it to your project: `uv add --dev 'langgraph-cli[inmem]'`, "
    "or install globally: `uv tool install 'langgraph-cli[inmem]'`."
)


def _bin_dir(venv: Path) -> Path:
    return venv / ("Scripts" if sys.platform == "win32" else "bin")


def find_langgraph(project_root: Path) -> str:
    """Resolve the langgraph executable to use for *project_root*.

    The project's own virtualenv wins over PATH. This matters for correctness,
    not just tidiness: `langgraph dev` imports and runs the graph in-process, so
    it must execute in the environment where the agent's dependencies are
    installed. A globally installed CLI would fail to import the project.
    """
    exe = "langgraph.exe" if sys.platform == "win32" else "langgraph"
    for venv_name in (".venv", "venv"):
        candidate = _bin_dir(project_root / venv_name) / exe
        if candidate.is_file():
            return str(candidate)

    found = shutil.which("langgraph")
    if found:
        return found

    raise MissingDependency("langgraph", INSTALL_HINT)


def dev_command(
    langgraph: str,
    config: Path,
    port: int,
    *,
    host: str = "127.0.0.1",
    tunnel: bool = False,
    no_reload: bool = False,
) -> list[str]:
    """Build the `langgraph dev` argv.

    `--no-browser` is always passed: langctl opens a single tab pointed at the
    frontend, and letting the server open Studio too would open two.
    """
    cmd = [
        langgraph,
        "dev",
        "--config",
        str(config),
        "--host",
        host,
        "--port",
        str(port),
        "--no-browser",
    ]
    if tunnel:
        cmd.append("--tunnel")
    if no_reload:
        cmd.append("--no-reload")
    return cmd


def up_command(langgraph: str, config: Path) -> list[str]:
    """Build the `langgraph up` argv (Docker; serves on 8123)."""
    return [langgraph, "up", "--config", str(config), "--wait"]


def validate_command(langgraph: str, config: Path) -> list[str]:
    return [langgraph, "validate", "--config", str(config)]
