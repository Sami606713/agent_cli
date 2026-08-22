"""`langctl studio` — open a project's real file structure for browsing."""

from __future__ import annotations

import webbrowser
from pathlib import Path
from urllib.parse import quote

import typer

from ..core.errors import LangctlError, MissingDependency
from ..core.project.manifest import Project
from ..core.runtime.executables import find as find_executable
from ..core.runtime.health import find_free_port, is_port_free
from ..core.runtime.supervisor import ProcessSpec, StartupFailure, Supervisor
from ..core.ui.theme import console

#: Deliberately not the frontend's own dev port (`spec.frontend.port`,
#: usually 3000) — `langctl studio` and `langctl dev` run the same
#: underlying Next.js app on two different routes, so they need separate
#: default ports to run side by side without colliding.
DEFAULT_PORT = 9595


def _frontend_command(project: Project, port: int) -> list[str]:
    """Same resolution `dev` uses: npm/pnpm ship as `.cmd` shims on Windows."""
    pnpm = find_executable("pnpm")
    if pnpm and (project.frontend_dir / "pnpm-lock.yaml").exists():
        return [pnpm, "dev", "--port", str(port)]

    npm = find_executable("npm")
    if npm is None:
        raise MissingDependency("npm", "Install Node.js 20+: https://nodejs.org")
    return [npm, "run", "dev", "--", "--port", str(port)]


def studio(
    path: Path | None = typer.Argument(
        None, help="Project to open. Defaults to the current directory."
    ),
    port: int | None = typer.Option(None, "--port", help="Frontend port."),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open a browser."),
) -> None:
    """Open a langctl project's real file structure in the browser, read-only."""
    project_dir = (path or Path.cwd()).resolve()
    project = Project.load(project_dir)

    if not project.frontend_dir.is_dir():
        raise LangctlError(
            f"No frontend found at {project.frontend_dir}",
            fix="Run `langctl add frontend`, or check that this is a langctl project.",
        )
    if not (project.frontend_dir / "node_modules").is_dir():
        raise LangctlError(
            "Frontend dependencies are not installed",
            fix=f"cd {project.frontend_dir.name} && npm install",
        )

    web_port = port or DEFAULT_PORT
    if not is_port_free(web_port):
        web_port = find_free_port(web_port + 1)

    spec = ProcessSpec(
        name="studio",
        command=_frontend_command(project, web_port),
        cwd=project.frontend_dir,
        color="cyan",
        health_url=f"http://127.0.0.1:{web_port}/studio",
        health_timeout=120.0,
    )

    web_url = f"http://localhost:{web_port}/studio?path={quote(str(project_dir))}"

    with Supervisor(console) as sup:
        with console.status("[dim]starting studio…[/dim]", spinner="dots") as status:

            def progress(spec_, elapsed: float) -> None:
                status.update(f"[dim]waiting for {spec_.name} … {elapsed:0.0f}s[/dim]")

            try:
                sup.start([spec], on_wait=progress)
            except StartupFailure as failure:
                raise LangctlError(
                    f"studio failed to start: {failure.reason}",
                    fix=failure.process.log_tail(),
                ) from failure

        console.print(f"[bold]studio[/bold] running at [bold cyan]{web_url}[/bold cyan]")
        console.print("[dim]press Ctrl-C to stop[/dim]\n")

        if not no_open:
            webbrowser.open(web_url)

        exited = sup.wait()
        if exited is not None:
            console.print(f"\n[red]studio exited with code {exited.returncode}[/red]")
            raise typer.Exit(exited.returncode or 1)
        console.print("\n[dim]stopped.[/dim]")
