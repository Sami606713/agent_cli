"""`agentctl new` — scaffold a project."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from ..core.errors import AgentctlError
from ..core.scaffold import scaffold
from ..core.spec import AgentSpec

console = Console()

MODEL_DEFAULTS = {
    "anthropic": "claude-opus-5",
    "openai": "gpt-5.5",
    "google": "gemini-2.5-pro",
}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def _install(dest: Path, spec: AgentSpec) -> None:
    """Install dependencies, but never fail the scaffold over it."""
    if shutil.which("uv"):
        console.print("[dim]installing python dependencies (uv)…[/dim]")
        result = subprocess.run(
            ["uv", "sync", "--extra", "dev"], cwd=dest, capture_output=True, text=True
        )
        if result.returncode != 0:
            console.print("[yellow]![/yellow] uv sync failed; run it yourself later")
            console.print(f"[dim]{result.stderr.strip()[:400]}[/dim]")
    else:
        console.print("[yellow]![/yellow] uv not found — skipping python install")

    web = dest / "web"
    if web.is_dir():
        pm = "pnpm" if shutil.which("pnpm") else ("npm" if shutil.which("npm") else None)
        if pm is None:
            console.print("[yellow]![/yellow] no npm/pnpm found — skipping frontend install")
            return
        console.print(f"[dim]installing frontend dependencies ({pm})… this takes a minute[/dim]")
        result = subprocess.run([pm, "install"], cwd=web, capture_output=True, text=True)
        if result.returncode != 0:
            console.print(f"[yellow]![/yellow] {pm} install failed; run it yourself in web/")
            console.print(f"[dim]{result.stderr.strip()[:400]}[/dim]")


def new(
    name: str = typer.Argument(None, help="Project name (lowercase, hyphens)."),
    directory: Path = typer.Option(None, "--dir", help="Where to create it. Default: ./<name>"),
    runtime: str = typer.Option(None, "--runtime", help="python or node."),
    model_provider: str = typer.Option(None, "--model-provider"),
    model_name: str = typer.Option(None, "--model"),
    frontend: bool = typer.Option(None, "--frontend/--no-frontend"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept defaults, ask nothing."),
    install: bool = typer.Option(True, "--install/--no-install"),
    git: bool = typer.Option(True, "--git/--no-git"),
) -> None:
    """Create a new agent project."""
    if name is None:
        if yes:
            raise AgentctlError(
                "A project name is required with --yes", fix="agentctl new my-agent"
            )
        name = Prompt.ask("Project name", default="my-agent")
    name = slugify(name)

    if runtime is None:
        runtime = (
            "python"
            if yes
            else Prompt.ask("Runtime", choices=["python", "node"], default="python")
        )

    if frontend is None:
        frontend = True if yes else Confirm.ask("Include a chat frontend?", default=True)

    if model_provider is None:
        model_provider = (
            "anthropic"
            if yes
            else Prompt.ask(
                "Model provider", choices=list(MODEL_DEFAULTS), default="anthropic"
            )
        )
    model_name = model_name or MODEL_DEFAULTS.get(model_provider, "claude-opus-5")

    spec = AgentSpec(
        name=name,
        runtime=runtime,  # type: ignore[arg-type]
        mode="proxy",
        model={"provider": model_provider, "name": model_name},  # type: ignore[arg-type]
        frontend={  # type: ignore[arg-type]
            "enabled": frontend,
            "kind": "nextjs_proxy" if frontend else "none",
        },
        observability={"langsmith": True, "project": name},  # type: ignore[arg-type]
    )

    dest = (directory or Path.cwd() / name).resolve()
    if dest.exists() and any(dest.iterdir()):
        raise AgentctlError(
            f"{dest} already exists and is not empty",
            fix="Pick another name, or pass --dir to a fresh directory.",
        )
    dest.mkdir(parents=True, exist_ok=True)

    written = scaffold(spec, dest)
    console.print(f"[green]✓[/green] created {len(written)} files in [bold]{dest}[/bold]")

    env_example = dest / ".env.example"
    if env_example.is_file() and not (dest / ".env").exists():
        shutil.copyfile(env_example, dest / ".env")
        console.print("[green]✓[/green] created .env from .env.example")

    if git and shutil.which("git") and not (dest / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=dest, check=False)

    if install:
        _install(dest, spec)

    rel = dest.name if dest.parent == Path.cwd() else str(dest)
    console.print(
        Panel(
            f"[bold]1.[/bold] cd {rel}\n"
            f"[bold]2.[/bold] add your {spec.model.api_key_env} to [cyan].env[/cyan]\n"
            f"[bold]3.[/bold] agentctl dev",
            title="[bold]next steps[/bold]",
            border_style="cyan",
            title_align="left",
        )
    )
