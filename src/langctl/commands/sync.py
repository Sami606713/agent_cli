"""`langctl sync` — regenerate derived files from agent.yaml."""

from __future__ import annotations

import json

import typer
from rich.console import Console

from ..core.generate.pyproject import dependency_drift, sync_dependencies
from ..core.generate.scaffold import config_drift, write_langgraph_config
from ..core.project.manifest import Project

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

    # encoding is explicit: the generated pyproject.toml contains an em dash,
    # which the locale codec on Windows cannot always decode.
    pyproject = (project.root / "pyproject.toml").read_text(encoding="utf-8")
    missing, extra = dependency_drift(project.spec, pyproject)
    if missing or extra:
        console.print("[yellow]![/yellow] pyproject.toml dependencies are out of date:")
        for package in missing:
            console.print(f"  [green]+[/green] {package}")
        for package in extra:
            console.print(f"  [red]-[/red] {package}")

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
        if missing or extra:
            console.print("\n[red]✗[/red] dependencies differ from agent.yaml")
            raise typer.Exit(1)
        console.print("[green]✓[/green] langgraph.json and pyproject.toml are in sync")
        return

    write_langgraph_config(project.spec, path)
    console.print(f"[green]✓[/green] wrote {path.relative_to(project.root)}")

    # Config alone is not enough: a feature whose package is missing starts the
    # server and then dies on import, while `langgraph validate` still says the
    # config is fine.
    pyproject = project.root / "pyproject.toml"
    if sync_dependencies(project.spec, pyproject):
        console.print("[green]✓[/green] wrote pyproject.toml (dependencies)")
        console.print("[dim]run `uv sync` to install the change[/dim]")
