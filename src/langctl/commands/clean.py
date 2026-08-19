"""`langctl clean` — reclaim ports a crashed dev session left behind.

`langctl dev` normally tears down its whole process group on exit, but a
`kill -9`, a crashed terminal, or a Ctrl-C swallowed by a debugger can all skip
that — after which `langctl dev` reports the port busy and points here.

Only ever offers to kill processes the current user owns, which is also all
`ss` can see without root: this can never be pointed at someone else's
process by accident.
"""

from __future__ import annotations

import os
import signal
import sys
import time

import typer
from ..core.ui.theme import console, CHECK, CROSS, WARN

from ..core.project.manifest import Project
from ..core.runtime.health import PortHolder, find_port_holder, is_port_free

console = Console()

#: Checked when no project is found, or a project does not set one of these.
DEFAULT_BACKEND_PORT = 2024
DEFAULT_FRONTEND_PORT = 3000

#: Names a `langctl dev` session actually spawns. A port held by something
#: else — a database, another app entirely — is reported but never touched:
#: killing an unrelated process because it happens to sit on 3000 would be a
#: much worse outcome than leaving the port busy.
KNOWN_HOLDERS = {"langgraph", "node", "next-server", "next-server (v1"}


def _looks_like_ours(holder: PortHolder) -> bool:
    return any(holder.name.startswith(prefix) for prefix in KNOWN_HOLDERS)


def _ports_to_check() -> dict[int, str]:
    try:
        spec = Project.load().spec
        return {spec.backend.port: "agent", spec.frontend.port: "web"}
    except Exception:
        # No project here, or a spec that fails to load — check the defaults
        # anyway, since that is almost always what the user means by "clean".
        return {DEFAULT_BACKEND_PORT: "agent", DEFAULT_FRONTEND_PORT: "web"}


def clean(
    yes: bool = typer.Option(False, "--yes", "-y", help="Kill without asking."),
    port: list[int] = typer.Option(
        None, "--port", help="Also check this port. May be given more than once."
    ),
) -> None:
    """Find and optionally kill processes left behind by a crashed dev session."""
    targets = _ports_to_check()
    for extra in port or []:
        targets.setdefault(extra, "extra")

    found_any = False
    for port_number, role in sorted(targets.items()):
        if is_port_free(port_number):
            continue
        found_any = True
        holder = find_port_holder(port_number)

        if holder is None:
            console.print(
                f"{WARN} port {port_number} ({role}) is busy, but "
                "langctl cannot tell by what — nothing to do here"
            )
            continue

        if not _looks_like_ours(holder):
            console.print(
                f"{WARN} port {port_number} ({role}) is held by "
                f"[bold]{holder.name}[/bold] (pid {holder.pid}) — not a langctl "
                "process, leaving it alone"
            )
            continue

        console.print(
            f"[red]✗[/red] port {port_number} ({role}) held by [bold]{holder.name}"
            f"[/bold] (pid {holder.pid}), orphaned from a previous `langctl dev`"
        )
        if yes or typer.confirm(f"  Kill pid {holder.pid}?", default=False):
            _kill(holder.pid)
            if is_port_free(port_number):
                console.print(f"  {CHECK} port {port_number} is free")
            else:
                console.print(
                    f"  {WARN} pid {holder.pid} did not exit in time; "
                    f"try again or kill it yourself"
                )

    if not found_any:
        console.print("{CHECK} nothing to clean — every checked port is free")


def _kill(pid: int) -> None:
    """SIGTERM, then SIGKILL if it has not gone after a short grace period."""
    try:
        if sys.platform == "win32":
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                time.sleep(0.1)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # already gone
    except PermissionError:
        console.print(f"  {WARN} no permission to kill pid {pid}")
