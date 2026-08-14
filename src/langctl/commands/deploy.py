"""`langctl deploy` — put the whole app on one host, in one operation.

Frontend, agent, Postgres and Redis go up together behind one URL. That is the
point of the command. Deploying the two halves separately means pasting the
agent's address into the frontend's configuration and re-pasting it on every
redeploy — here the frontend reaches the agent by a service name on a private
network, so there is no address for anyone to get wrong.

    langctl deploy                        # this machine
    langctl deploy --host user@1.2.3.4    # a host you already own
    langctl deploy --host … --domain x.io # the same, with automatic TLS

Both targets build the same images from the same compose file, so what runs on
the server is what you tested locally.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from ..core.deploy.stack import AGENT_DOCKERFILE, emit, missing_files
from ..core.deploy.targets import (
    ENV_FILE,
    LICENCE_KEY,
    Remote,
    compose_build,
    compose_down,
    compose_logs,
    compose_up,
    missing_secrets,
    over_ssh,
    parse_remote,
    read_env_file,
    remote_has_env_file,
    remote_mkdir,
    rsync_project,
    write_agent_dockerfile,
)
from ..core.errors import LangctlError
from ..core.generate.scaffold import write_langgraph_config
from ..core.project.manifest import Project
from ..core.runtime.executables import require
from ..core.runtime.langgraph_cli import find_langgraph

console = Console()


def _run(argv: list[str], cwd: Path, what: str) -> None:
    """Run a step, streaming its output, and stop the deploy if it fails."""
    result = subprocess.run(argv, cwd=cwd)
    if result.returncode != 0:
        raise LangctlError(
            f"{what} failed (exit {result.returncode})",
            fix="The output above has the details.",
        )


def _quiet(argv: list[str]) -> bool:
    """Run a probe, discarding output. True when it exits 0."""
    return (
        subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        == 0
    )


def deploy(
    host: str = typer.Option(
        None, "--host", help="ssh destination to deploy to. Omit to deploy locally."
    ),
    remote_path: str = typer.Option(
        None, "--path", help="Directory on the remote host. Default: ~/<project>."
    ),
    domain: str = typer.Option(
        None, "--domain", help="Serve on this domain over HTTPS. Adds Caddy to the stack."
    ),
    port: int = typer.Option(
        3000, "--port", help="Host port to publish on. Ignored with --domain."
    ),
    build_only: bool = typer.Option(
        False, "--build-only", help="Write the stack and build images; do not start."
    ),
    down: bool = typer.Option(False, "--down", help="Stop the stack."),
    volumes: bool = typer.Option(
        False, "--volumes", help="With --down, also delete the database. Destructive."
    ),
    logs: bool = typer.Option(False, "--logs", help="Follow logs from the stack."),
    service: str = typer.Option(
        None, "--service", help="With --logs: agent, web, postgres, redis."
    ),
    licensed: bool = typer.Option(
        False,
        "--licensed",
        help="Use LangChain's production Agent Server. Needs a licence key, Postgres and Redis.",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite stack files you have edited."),
) -> None:
    """Deploy the app — frontend, agent and databases — to one host."""
    project = Project.load()
    root, spec = project.root, project.spec

    remote: Remote | None = parse_remote(host, remote_path, spec.name) if host else None
    where = remote.destination if remote else "this machine"
    docker = require("docker")

    # ---- lifecycle shortcuts --------------------------------------------
    if logs:
        argv = compose_logs(docker, service, follow=True)
        _run(over_ssh(remote, argv) if remote else argv, root, "docker compose logs")
        return

    if down:
        if volumes and not typer.confirm(
            f"Delete the database volume on {where}? Every conversation and "
            "memory is lost permanently.",
            default=False,
        ):
            raise typer.Abort()
        argv = compose_down(docker, volumes)
        _run(over_ssh(remote, argv) if remote else argv, root, "docker compose down")
        console.print(f"[green]✓[/green] stack stopped on {where}")
        return

    # ---- write the stack -------------------------------------------------
    console.print("[bold]stack[/bold]")
    result = emit(
        spec, root, web_host_port=port, domain=domain, licensed=licensed, overwrite=force
    )
    for path in result.written:
        console.print(f"  [green]✓[/green] {path.relative_to(root)}")
    for path in result.skipped:
        console.print(f"  [dim]· {path.relative_to(root)} (yours, kept)[/dim]")

    write_langgraph_config(spec, project.langgraph_config_path)
    if licensed:
        # Only the production image needs a generated Dockerfile: langgraph.json
        # is the sole thing that knows its base image and Python version. The
        # default stack ships its own, templated above.
        langgraph = find_langgraph(root)
        _run(
            write_agent_dockerfile(langgraph, root / AGENT_DOCKERFILE),
            root,
            "langgraph dockerfile",
        )
        console.print(f"  [green]✓[/green] {AGENT_DOCKERFILE}")

    absent = missing_files(root, domain=domain)
    if absent:
        raise LangctlError(
            f"Stack is incomplete: {', '.join(absent)}",
            fix="Re-run with --force to regenerate the missing files.",
        )

    # ---- secrets, before anything expensive ------------------------------
    env_path = root / ENV_FILE
    if not env_path.is_file():
        env_path.write_text(
            (root / f"{ENV_FILE}.example").read_text(encoding="utf-8"), encoding="utf-8"
        )
        # Name what this stack actually needs. The licence-free stack wants
        # only a model key; naming Postgres and LangSmith there sent people
        # hunting for credentials they do not need.
        needed = [spec.model.api_key_env] if spec.model.api_key_env else []
        if licensed:
            needed += ["POSTGRES_PASSWORD", "a licence key"]
        raise LangctlError(
            f"Created {ENV_FILE} — fill it in, then deploy again",
            fix=(
                f"Set {', '.join(needed)} in {ENV_FILE}. Nothing was built."
                if needed
                else f"Review {ENV_FILE}, then deploy again. Nothing was built."
            ),
        )

    env = read_env_file(env_path)
    if gaps := missing_secrets(env, spec.model.api_key_env, licensed=licensed):
        raise LangctlError(
            f"Still unset in {ENV_FILE}: {', '.join(gaps)}",
            fix="Fill those in and deploy again. Nothing was built.",
        )
    if licensed and not env.get(LICENCE_KEY, "").strip():
        console.print(
            f"\n[yellow]![/yellow] [bold]{LICENCE_KEY} is not set.[/bold] The Agent Server "
            "will try your LangSmith API key instead, and refuses to start if that "
            "account has no Agent Server access."
        )

    if build_only:
        console.print("\n[bold]build[/bold]")
        _run(compose_build(docker), root, "docker compose build")
        console.print("[green]✓[/green] images built; nothing started (--build-only)")
        return

    # ---- ship and start --------------------------------------------------
    if remote:
        require("rsync")
        require("ssh")
        console.print(f"\n[bold]ship[/bold] → {remote.destination}:{remote.path}")
        _run(remote_mkdir(remote), root, "ssh mkdir")
        _run(rsync_project(root, remote), root, "rsync")

        # Secrets are never uploaded, so the host must already have them. This
        # is checked here rather than after a ten-minute remote image build.
        if not _quiet(remote_has_env_file(remote)):
            raise LangctlError(
                f"{ENV_FILE} does not exist at {remote.path} on {remote.destination}",
                fix=(
                    f"Copy it once, by hand, so secrets stay out of every later deploy:\n"
                    f"  scp {ENV_FILE} {remote.destination}:{remote.path}/{ENV_FILE}"
                ),
            )

        console.print("\n[bold]start[/bold] [dim]building on the host…[/dim]")
        _run(over_ssh(remote, compose_up(docker)), root, "docker compose up")
        url = f"https://{domain}" if domain else f"http://{remote.host}:{port}"
    else:
        console.print("\n[bold]start[/bold]")
        _run(compose_up(docker), root, "docker compose up")
        url = f"https://{domain}" if domain else f"http://localhost:{port}"

    suffix = f" --host {remote.destination}" if remote else ""
    console.print(
        Panel(
            f"[bold]{url}[/bold]\n"
            f"[dim]the agent has no public route; the app reaches it privately[/dim]\n\n"
            f"[dim]logs[/dim]   langctl deploy --logs{suffix}\n"
            f"[dim]stop[/dim]   langctl deploy --down{suffix}",
            title="[bold]deployed[/bold]",
            border_style="green",
            title_align="left",
        )
    )
