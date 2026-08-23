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


#: `npm install @langchain/langgraph-cli` names its bin `langgraph`, same as
#: the Python package — installing it locally is what makes it show up under
#: node_modules/.bin, exactly like a venv's bin/ for the Python side.
NODE_INSTALL_HINT = "Add it to your project: `npm install --save-dev @langchain/langgraph-cli`."


def find_langgraph(project_root: Path, runtime: str = "python") -> str:
    """Resolve the langgraph executable for *project_root*.

    Only the project's own dependency install is accepted — never PATH.
    `langgraph dev` imports and runs the graph in-process, so it has to
    execute where the agent's dependencies live: a globally installed CLI has
    its own isolated environment and cannot import the project at all.

    Falling back to PATH used to look helpful and was the opposite: a global
    install satisfied every check, then failed at import time with an error
    that pointed at the agent rather than at the install.
    """
    exe = "langgraph.exe" if sys.platform == "win32" else "langgraph"

    if runtime == "typescript":
        candidate = project_root / "node_modules" / ".bin" / exe
        if candidate.is_file():
            return str(candidate)
        if shutil.which("langgraph"):
            raise MissingDependency(
                "langgraph (in this project)",
                "You have a langgraph CLI on PATH, but it cannot import your "
                f"agent. Install it in the project instead:\n  {NODE_INSTALL_HINT}",
            )
        raise MissingDependency("langgraph", NODE_INSTALL_HINT)

    for venv_name in (".venv", "venv"):
        candidate = _bin_dir(project_root / venv_name) / exe
        if candidate.is_file():
            return str(candidate)

    if shutil.which("langgraph"):
        raise MissingDependency(
            "langgraph (in this project)",
            "You have langgraph installed globally, but it cannot import your "
            "agent. Install it in the project instead:\n"
            "  uv add --dev 'langgraph-cli[inmem]'",
        )
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
