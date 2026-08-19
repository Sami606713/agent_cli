"""`langctl build` — a fast "does this even compile" check.

`deploy --build-only` builds the Docker images, which is the real answer but
costs minutes and needs Docker running. This is the check that fits before
that: validate `langgraph.json` and, if the project has a frontend, run its
real `next build` — no Docker, no deployment.

Not a substitute for `deploy --build-only`; a cheaper first gate before it.
"""

from __future__ import annotations

import subprocess

import typer

from ..core.errors import LangctlError
from ..core.generate.scaffold import write_langgraph_config
from ..core.project.manifest import Project
from ..core.runtime.executables import package_manager
from ..core.runtime.langgraph_cli import find_langgraph, validate_command
from ..core.ui.theme import CHECK, console


def build(
    skip_frontend: bool = typer.Option(
        False, "--skip-frontend", help="Only validate the agent, not the UI."
    ),
) -> None:
    """Validate the agent config and, if present, build the frontend."""
    project = Project.load()
    spec = project.spec

    console.print("[bold]agent[/bold]")
    write_langgraph_config(spec, project.langgraph_config_path)
    langgraph = find_langgraph(project.root)
    argv = validate_command(langgraph, project.langgraph_config_path)
    result = subprocess.run(argv, cwd=project.root)
    if result.returncode != 0:
        raise LangctlError(
            "langgraph.json is not valid",
            fix="The output above has the details. Try `langctl sync` first.",
        )
    console.print(f"  {CHECK} langgraph.json valid, graph imports")

    if skip_frontend or not spec.frontend.enabled:
        return

    web = project.frontend_dir
    if not (web / "node_modules").is_dir():
        raise LangctlError(
            "frontend dependencies are not installed",
            fix=f"cd {web.relative_to(project.root)} && npm install",
        )

    pm = package_manager()
    if pm is None:
        raise LangctlError(
            "no npm or pnpm found — cannot build the frontend",
            fix="Install Node.js 20+: https://nodejs.org, or pass --skip-frontend.",
        )

    console.print("\n[bold]web[/bold]")
    result = subprocess.run([pm, "run", "build"], cwd=web)
    if result.returncode != 0:
        raise LangctlError(
            "the frontend build failed",
            fix="The output above has the details.",
        )
    console.print(f"  {CHECK} next build succeeded")
