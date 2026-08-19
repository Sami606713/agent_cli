"""`langctl share` — put the locally running app on a public URL.

Everything still runs on this machine; a tunnel client forwards traffic to it.
That makes it the one "deploy" path with no hosting bill, no licence question,
and no infrastructure — and equally, nothing that survives closing the laptop.

Only the frontend is tunnelled. The agent stays on localhost, reachable solely
through the frontend's proxy route, so the public URL cannot hit the agent API
directly and no API key is exposed.
"""

from __future__ import annotations

import threading
import time

import typer
from rich.panel import Panel

from ..core.errors import LangctlError
from ..core.generate.scaffold import write_langgraph_config
from ..core.project.manifest import Project
from ..core.runtime.health import find_free_port, is_port_free
from ..core.runtime.langgraph_cli import dev_command, find_langgraph
from ..core.runtime.supervisor import ProcessSpec, StartupFailure, Supervisor
from ..core.runtime.tunnel import PROVIDERS, available, extract_url, resolve
from ..core.ui.theme import console

#: How long to wait for the tunnel client to announce its URL.
URL_TIMEOUT = 60.0


def share(
    provider: str = typer.Option(
        None, "--provider", help=f"Tunnel provider: {', '.join(PROVIDERS)}."
    ),
    port: int = typer.Option(None, "--port", help="Frontend port."),
    backend_port: int = typer.Option(None, "--backend-port", help="Agent server port."),
    backend_only: bool = typer.Option(
        False, "--backend-only", help="Tunnel the agent API instead of the app."
    ),
) -> None:
    """Run the app and expose it on a public URL."""
    project = Project.load()
    spec = project.spec

    tunnel = resolve(provider)
    if tunnel is None:
        found = available()
        raise LangctlError(
            f"No tunnel provider found (looked for: {', '.join(PROVIDERS)})"
            if not found
            else f"{provider!r} is not installed",
            fix=(
                "Install cloudflared — quick tunnels need no account:\n  "
                "https://developers.cloudflare.com/cloudflare-one/connections/"
                "connect-networks/downloads/"
            ),
        )

    has_frontend = spec.frontend.enabled and spec.frontend.kind != "none" and not backend_only
    if not has_frontend and not backend_only:
        raise LangctlError(
            "This project has no frontend, so there is nothing to share.",
            fix="Run `langctl add frontend`, or `langctl share --backend-only` "
            "to expose the agent API itself.",
        )

    write_langgraph_config(spec, project.langgraph_config_path)

    api_port = backend_port or spec.backend.port
    if not is_port_free(api_port):
        api_port = find_free_port(api_port + 1)
    web_port = port or spec.frontend.port
    if has_frontend and not is_port_free(web_port):
        web_port = find_free_port(web_port + 1)

    api_url = f"http://127.0.0.1:{api_port}"
    exposed_port = api_port if backend_only else web_port

    if backend_only:
        console.print(
            "[yellow]![/yellow] --backend-only exposes the agent API directly. "
            "Anyone with the URL can start runs against it."
        )

    specs = [
        ProcessSpec(
            name="agent",
            command=dev_command(
                find_langgraph(project.root), project.langgraph_config_path, api_port
            ),
            cwd=project.root,
            color="green",
            health_url=f"{api_url}/ok",
        )
    ]
    if has_frontend:
        from .dev import _frontend_command

        specs.append(
            ProcessSpec(
                name="web",
                command=_frontend_command(project, web_port),
                cwd=project.frontend_dir,
                color="cyan",
                env={
                    "LANGGRAPH_API_URL": api_url,
                    "NEXT_PUBLIC_API_URL": "/api",
                    "NEXT_PUBLIC_ASSISTANT_ID": spec.graph_id,
                },
                health_url=f"http://127.0.0.1:{web_port}/",
                health_timeout=120.0,
            )
        )

    public_url: list[str] = []
    found_url = threading.Event()

    def watch(line: str) -> None:
        if not public_url and (url := extract_url(line)):
            public_url.append(url)
            found_url.set()

    specs.append(
        ProcessSpec(
            name="tunnel",
            command=tunnel.command(exposed_port),
            cwd=project.root,
            color="magenta",
            on_line=watch,
            # Tunnel clients log heavily; the URL is the only interesting part.
            echo=False,
        )
    )

    with Supervisor(console) as sup:
        with console.status("[dim]starting…[/dim]", spinner="dots") as status:

            def progress(spec_, elapsed: float) -> None:
                status.update(f"[dim]waiting for {spec_.name} … {elapsed:0.0f}s[/dim]")

            try:
                sup.start(specs, on_wait=progress)
            except StartupFailure as failure:
                raise LangctlError(
                    f"{failure.process.spec.name} failed to start: {failure.reason}",
                    fix="Run `langctl doctor`.",
                    detail=failure.process.log_tail(),
                ) from failure

            status.update("[dim]waiting for the tunnel URL…[/dim]")
            deadline = time.monotonic() + URL_TIMEOUT
            while not found_url.is_set() and time.monotonic() < deadline:
                if not sup.processes[-1].is_running():
                    raise LangctlError(
                        f"{tunnel.name} exited before giving a URL",
                        fix=(f"Check the tunnel client is configured ({tunnel.install_hint})."),
                        detail=sup.processes[-1].log_tail(),
                    )
                found_url.wait(0.25)

        if not public_url:
            raise LangctlError(
                f"{tunnel.name} did not report a URL within {URL_TIMEOUT:.0f}s",
                detail=sup.processes[-1].log_tail(),
            )

        console.print(
            Panel(
                f"[bold cyan]{public_url[0]}[/bold cyan]\n\n"
                f"[dim]local  [/dim] http://localhost:{exposed_port}\n"
                f"[dim]agent  [/dim] {api_url} [dim](not exposed)[/dim]\n"
                f"[dim]tunnel [/dim] {tunnel.name}",
                title="[bold]public URL[/bold]",
                border_style="magenta",
                title_align="left",
            )
        )
        console.print(
            "[yellow]![/yellow] This URL is public and unauthenticated. Anyone with "
            "it can talk to your agent and spend your API credits.\n"
            "[dim]press Ctrl-C to stop everything[/dim]\n"
        )

        exited = sup.wait()
        if exited is not None:
            console.print(f"\n[red]{exited.spec.name} exited[/red] — shutting down.")
            raise typer.Exit(exited.returncode or 1)
        console.print("\n[dim]stopped.[/dim]")
