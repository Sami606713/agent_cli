"""`langctl dev` — run the agent and the frontend as one application."""

from __future__ import annotations

import webbrowser
from urllib.parse import quote

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..core.errors import BackendStartFailed, LangctlError, MissingDependency, PortInUse
from ..core.generate.scaffold import write_langgraph_config
from ..core.project.manifest import Project
from ..core.runtime.executables import find as find_executable
from ..core.runtime.health import describe_port_holder, find_free_port, is_port_free
from ..core.runtime.langgraph_cli import dev_command, find_langgraph, up_command
from ..core.runtime.supervisor import ProcessSpec, StartupFailure, Supervisor

console = Console()

#: `langgraph up` (Docker) serves on 8123; `langgraph dev` on 2024.
DOCKER_PORT = 8123


def _resolve_port(preferred: int, role: str, auto: bool) -> int:
    if is_port_free(preferred):
        return preferred
    if not auto:
        raise PortInUse(preferred, role, describe_port_holder(preferred))
    chosen = find_free_port(preferred + 1)
    console.print(f"[yellow]![/yellow] port {preferred} ({role}) is busy — using {chosen} instead")
    return chosen


def _backend_command(project: Project, port: int, docker: bool, tunnel: bool) -> list[str]:
    # Prefers the project's own venv: `langgraph dev` imports the graph in-process,
    # so it has to run where the agent's dependencies are installed.
    langgraph = find_langgraph(project.root)
    if docker:
        # `up` takes its port from its own compose config, not a flag.
        return up_command(langgraph, project.langgraph_config_path)
    return dev_command(langgraph, project.langgraph_config_path, port, tunnel=tunnel)


def _frontend_command(project: Project, port: int) -> list[str]:
    """Argv for the frontend dev server, with the binary resolved to a path.

    Resolved rather than named because npm and pnpm ship as `.cmd` shims on
    Windows, which cannot be launched from a bare name.
    """
    pnpm = find_executable("pnpm")
    if pnpm and (project.frontend_dir / "pnpm-lock.yaml").exists():
        return [pnpm, "dev", "--port", str(port)]

    npm = find_executable("npm")
    if npm is None:
        raise MissingDependency("npm", "Install Node.js 20+: https://nodejs.org")
    # `npm run` needs `--` to pass flags through to the underlying next command.
    return [npm, "run", "dev", "--", "--port", str(port)]


def _summary(spec_name: str, web_url: str | None, api_url: str, docker: bool) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    if web_url:
        table.add_row("app", f"[bold cyan]{web_url}[/bold cyan]")
    table.add_row("agent api", api_url)
    table.add_row("api docs", f"{api_url}/docs")
    table.add_row(
        "studio",
        f"https://smith.langchain.com/studio/?baseUrl={quote(api_url, safe='')}",
    )
    if docker:
        table.add_row("mode", "docker (langgraph up)")
    return Panel(
        table,
        title=f"[bold]{spec_name}[/bold] is running",
        border_style="green",
        title_align="left",
    )


def dev(
    backend_only: bool = typer.Option(False, "--backend-only", help="Run only the agent server."),
    frontend_only: bool = typer.Option(False, "--frontend-only", help="Run only the frontend."),
    port: int | None = typer.Option(None, "--port", help="Frontend port."),
    backend_port: int | None = typer.Option(None, "--backend-port", help="Agent server port."),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open a browser."),
    docker: bool = typer.Option(False, "--docker", help="Run the agent via `langgraph up`."),
    tunnel: bool = typer.Option(False, "--tunnel", help="Expose the agent via a public tunnel."),
    auto_port: bool = typer.Option(
        True, "--auto-port/--strict-port", help="Pick the next free port if one is busy."
    ),
) -> None:
    """Run the agent and frontend together, already wired to each other."""
    project = Project.load()
    spec = project.spec

    if backend_only and frontend_only:
        raise LangctlError("--backend-only and --frontend-only are mutually exclusive")

    has_frontend = spec.frontend.enabled and spec.frontend.kind != "none" and not backend_only
    wants_backend = spec.uses_agent_server and not frontend_only

    if has_frontend and not project.frontend_dir.is_dir():
        raise LangctlError(
            f"agent.yaml enables a frontend but {project.frontend_dir} does not exist",
            fix="Run `langctl add frontend`, or set frontend.enabled: false in agent.yaml.",
        )
    if has_frontend and not (project.frontend_dir / "node_modules").is_dir():
        raise LangctlError(
            "Frontend dependencies are not installed",
            fix=f"cd {project.frontend_dir.name} && npm install",
        )

    # Keep langgraph.json current so a spec edit does not need a manual sync.
    write_langgraph_config(spec, project.langgraph_config_path)

    api_port = DOCKER_PORT if docker else (backend_port or spec.ports.agent)
    if wants_backend and not docker:
        api_port = _resolve_port(api_port, "agent", auto_port)
    web_port = (
        _resolve_port(port or spec.ports.frontend, "web", auto_port) if has_frontend else None
    )

    api_url = f"http://127.0.0.1:{api_port}"

    specs: list[ProcessSpec] = []
    if wants_backend:
        specs.append(
            ProcessSpec(
                name="agent",
                command=_backend_command(project, api_port, docker, tunnel),
                cwd=project.root,
                color="green",
                # The gate: the frontend does not start until this answers.
                health_url=f"{api_url}/ok",
                health_timeout=180.0 if docker else 90.0,
            )
        )
    if has_frontend and web_port is not None:
        specs.append(
            ProcessSpec(
                name="web",
                command=_frontend_command(project, web_port),
                cwd=project.frontend_dir,
                color="cyan",
                # agent-chat-ui's passthrough reads LANGGRAPH_API_URL; the
                # browser only ever sees NEXT_PUBLIC_API_URL="/api", so the
                # agent's address and any key stay server-side. Both are set
                # here so the chat's setup screen is never reached.
                env={
                    "LANGGRAPH_API_URL": api_url,
                    "NEXT_PUBLIC_API_URL": "/api",
                    "NEXT_PUBLIC_ASSISTANT_ID": spec.graph_id,
                },
                health_url=f"http://127.0.0.1:{web_port}/",
                health_timeout=120.0,
            )
        )

    if not specs:
        raise LangctlError(
            "Nothing to run",
            fix="Check `mode` and `frontend.enabled` in agent.yaml.",
        )

    web_url = f"http://localhost:{web_port}" if web_port else None

    with Supervisor(console) as sup:
        with console.status("[dim]starting agent…[/dim]", spinner="dots") as status:

            def progress(spec_, elapsed: float) -> None:
                status.update(f"[dim]waiting for {spec_.name} … {elapsed:0.0f}s[/dim]")

            try:
                sup.start(specs, on_wait=progress)
            except StartupFailure as failure:
                raise BackendStartFailed(failure.reason, failure.process.log_tail()) from failure
            except FileNotFoundError as exc:
                raise LangctlError(
                    str(exc),
                    fix="Install the missing tool, then run `langctl doctor`.",
                ) from exc

        console.print(_summary(spec.name, web_url, api_url, docker))
        console.print("[dim]press Ctrl-C to stop everything[/dim]\n")

        if web_url and not no_open:
            webbrowser.open(web_url)

        exited = sup.wait()
        if exited is not None:
            console.print(
                f"\n[red]{exited.spec.name} exited with code {exited.returncode}[/red] "
                "— shutting down."
            )
            raise typer.Exit(exited.returncode or 1)
        console.print("\n[dim]stopped.[/dim]")
