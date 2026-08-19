"""`langctl versions` — every deploy recorded for this project, newest first."""

from __future__ import annotations

from datetime import datetime

from ..core.ui.theme import console
from rich.table import Table

from ..core.deploy.version import current_tag, deploy_history
from ..core.project.manifest import Project



def _human(at: str) -> str:
    """`2026-08-19T08:25:05.654321+00:00` -> `2026-08-19 08:25 UTC`.

    Falls back to the raw value for any timestamp that does not parse — a
    display quirk must never be the reason `versions` cannot list a deploy.
    """
    try:
        return datetime.fromisoformat(at).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return at


def versions() -> None:
    """List recorded deploys, most recent first."""
    project = Project.load()
    history = deploy_history(project)

    if not history:
        console.print(
            "[dim]No recorded deploys yet. `langctl deploy` records a version "
            "on every successful run.[/dim]"
        )
        return

    current = current_tag(project)
    table = Table(box=None, show_header=True, padding=(0, 2, 0, 0))
    table.add_column("")
    table.add_column("tag")
    table.add_column("deployed")
    table.add_column("images")

    for record in reversed(history):
        is_current = record.tag == current
        marker = "[green]●[/green]" if is_current else " "
        tag = f"[bold]{record.tag}[/bold]" if is_current else record.tag
        if record.dirty:
            tag += " [yellow](uncommitted changes)[/yellow]"
        table.add_row(marker, tag, _human(record.at), ", ".join(record.images))

    console.print(table)
    console.print(
        f"\n[dim]roll back with `langctl rollback <tag>` — "
        f"{len(history)} version{'s' if len(history) != 1 else ''} recorded[/dim]"
    )
