"""`langctl sync` — regenerate derived files from agent.yaml."""

from __future__ import annotations

import json

import typer
from rich.console import Console

from ..core.manifest import Project
from ..core.scaffold import config_drift, write_langgraph_config

console = Console()


def sync(
    force: bool = typer.Option(
        False, "--force", help="Overwrite owned keys in langgraph.json that were edited by hand."
    ),
    check: bool = typer.Option(
        False, "--check", help="Report drift and exit non-zero; change nothing. For CI."
    ),
) -> None:
    """Regenerate langgraph.json from agent.yaml, preserving hand-written keys."""
    project = Project.load()
    path = project.langgraph_config_path

    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            console.print("[yellow]![/yellow] langgraph.json is not valid JSON — regenerating")

    drift = config_drift(project.spec, existing)
    if drift and not force:
        console.print("[yellow]![/yellow] langgraph.json differs from agent.yaml:")
        for key, (on_disk, generated) in drift.items():
            console.print(f"  [bold]{key}[/bold]")
            console.print(f"    [dim]on disk  [/dim] {json.dumps(on_disk)}")
            console.print(f"    [dim]generated[/dim] {json.dumps(generated)}")
        console.print(
            "\nEdit agent.yaml to match, or run [bold]langctl sync --force[/bold] "
            "to overwrite the file."
        )
        raise typer.Exit(1)

    if check:
        console.print("[green]✓[/green] langgraph.json is in sync with agent.yaml")
        return

    write_langgraph_config(project.spec, path)
    console.print(f"[green]✓[/green] wrote {path.relative_to(project.root)}")
