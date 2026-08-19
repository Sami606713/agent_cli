"""`langctl env` — what this project needs set, and whether it is.

Two commands, matching `app env pull`/`app env show`:

    env show   read-only: required variables, and whether `.env` sets them
    env pull   regenerate `.env.example` from the current agent.yaml

Neither ever touches `.env` itself beyond creating it once if it is entirely
missing — it holds real secrets, `.env.example` does not.
"""

from __future__ import annotations

import typer
from ..core.ui.theme import console, CHECK, CROSS, WARN
from rich.table import Table

from ..core.generate.deps import required_env_vars
from ..core.generate.render import plan_layers
from ..core.generate.scaffold import backend_template, render_context
from ..core.project.manifest import Project


app = typer.Typer(name="env", help="Inspect and regenerate required environment variables.")


def _env_file_values(path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


@app.command("show")
def show() -> None:
    """List required variables and whether `.env` sets each one."""
    project = Project.load()
    required = required_env_vars(project.spec)

    if not required:
        console.print("[dim]This project needs no environment variables.[/dim]")
        return

    current = _env_file_values(project.env_file)
    table = Table(box=None, show_header=True, padding=(0, 2, 0, 0))
    table.add_column("")
    table.add_column("variable")
    table.add_column("needed for")

    for var, why in required.items():
        value = current.get(var, "").strip()
        if value:
            mark = "[green]✓ set[/green]"
        elif var in current:
            mark = "[yellow]· empty[/yellow]"
        else:
            mark = "[red]✗ missing[/red]"
        table.add_row(mark, var, why)

    console.print(table)
    missing = [v for v in required if not current.get(v, "").strip()]
    if missing:
        console.print(
            f"\n[dim]{len(missing)} unset — add "
            f"{'them' if len(missing) > 1 else 'it'} to .env[/dim]"
        )
    else:
        console.print("\n{CHECK} everything required is set")


@app.command("pull")
def pull() -> None:
    """Regenerate `.env.example` from the current agent.yaml.

    Safe to run any time: `.env.example` carries no secrets, so it is always
    fully regenerated rather than merged. `.env` itself is only ever created,
    once, from that fresh example — never overwritten once it exists.
    """
    project = Project.load()
    spec = project.spec

    planned = plan_layers([backend_template(spec)], project.root, render_context(spec))
    example_path = next((p for p in planned if p.name == ".env.example"), None)
    if example_path is None:
        console.print("[dim]No .env.example is generated for this project.[/dim]")
        return

    example_path.parent.mkdir(parents=True, exist_ok=True)
    example_path.write_text(planned[example_path], encoding="utf-8")
    console.print(f"{CHECK} wrote {example_path.relative_to(project.root)}")

    if not project.env_file.is_file():
        project.env_file.write_text(planned[example_path], encoding="utf-8")
        console.print(f"{CHECK} created {project.env_file.name} — fill it in")
    else:
        console.print(
            "[dim].env already exists and was not touched — "
            "run `langctl env show` to see what it is missing[/dim]"
        )
