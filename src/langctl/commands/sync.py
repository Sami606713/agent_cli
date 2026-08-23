"""`langctl sync` — regenerate derived files from agent.yaml."""

from __future__ import annotations

import json

import typer

from ..core.generate import package_json as ts_deps
from ..core.generate import pyproject as py_deps
from ..core.generate.frontend_sync import (
    add_frontend_dependencies,
    missing_frontend_dependencies,
    sync_frontend_files,
)
from ..core.generate.scaffold import config_drift, write_langgraph_config
from ..core.project.manifest import Project
from ..core.ui.theme import CHECK, CROSS, WARN, console


def _sync_frontend(project: Project) -> None:
    """Add template files/dependencies the project's `web/` is missing.

    Never overwrites an existing file — see `frontend_sync`'s module
    docstring for why that is the only safe behavior here.
    """
    if not project.frontend_dir.is_dir():
        console.print(f"{WARN} no frontend directory — nothing to sync")
        return

    result = sync_frontend_files(project.spec, project.frontend_dir)
    if result.written:
        console.print(f"{CHECK} added {len(result.written)} new frontend file(s):")
        for path in result.written:
            console.print(f"  [green]+[/green] {path.relative_to(project.frontend_dir)}")
    else:
        console.print(f"{CHECK} frontend files are already up to date")

    missing = missing_frontend_dependencies(project.spec, project.frontend_dir)
    if missing:
        add_frontend_dependencies(project.frontend_dir, missing)
        console.print(f"{CHECK} added dependencies to package.json:")
        for section, entries in missing.items():
            for name, version in entries.items():
                console.print(f"  [green]+[/green] {name}@{version} [dim]({section})[/dim]")
        console.print("[dim]run `pnpm install` (or `npm install`) in web/ to install them[/dim]")


def sync(
    frontend: bool = typer.Option(
        False, "--frontend", help="Add missing vendored frontend files/dependencies instead."
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite owned keys in langgraph.json that were edited by hand."
    ),
    check: bool = typer.Option(
        False, "--check", help="Report drift and exit non-zero; change nothing. For CI."
    ),
) -> None:
    """Regenerate langgraph.json from agent.yaml, preserving hand-written keys."""
    project = Project.load()

    if frontend:
        _sync_frontend(project)
        return

    path = project.langgraph_config_path

    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            console.print(f"{WARN} langgraph.json is not valid JSON — regenerating")

    is_python = project.spec.runtime == "python"
    deps_module = py_deps if is_python else ts_deps
    manifest_name = "pyproject.toml" if is_python else "package.json"
    manifest_path = project.root / manifest_name

    # encoding is explicit: the generated pyproject.toml contains an em dash,
    # which the locale codec on Windows cannot always decode.
    manifest_text = manifest_path.read_text(encoding="utf-8")
    missing, extra = deps_module.dependency_drift(project.spec, manifest_text)
    if missing or extra:
        console.print(f"{WARN} {manifest_name} dependencies are out of date:")
        for package in missing:
            console.print(f"  [green]+[/green] {package}")
        for package in extra:
            console.print(f"  [red]-[/red] {package}")

    drift = config_drift(project.spec, existing)
    if drift and not force:
        console.print(f"{WARN} langgraph.json differs from agent.yaml:")
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
            console.print(f"\n{CROSS} dependencies differ from agent.yaml")
            raise typer.Exit(1)
        console.print(f"{CHECK} langgraph.json and {manifest_name} are in sync")
        return

    write_langgraph_config(project.spec, path)
    console.print(f"{CHECK} wrote {path.relative_to(project.root)}")

    # Config alone is not enough: a feature whose package is missing starts the
    # server and then dies on import, while `langgraph validate` still says the
    # config is fine.
    if deps_module.sync_dependencies(project.spec, manifest_path):
        console.print(f"{CHECK} wrote {manifest_name} (dependencies)")
        install_hint = "uv sync" if is_python else "npm install"
        console.print(f"[dim]run `{install_hint}` to install the change[/dim]")
