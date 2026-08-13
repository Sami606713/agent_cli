"""`langctl new` — scaffold a project."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from ..core.errors import LangctlError
from ..core.executables import find as find_executable
from ..core.executables import package_manager
from ..core.memory_wizard import (
    EMBEDDING_MODES,
    MEMORY_BACKENDS,
    ask_memory,
    memory_from_flags,
)
from ..core.scaffold import scaffold
from ..core.spec import AgentSpec

console = Console()

#: One chat UI: LangChain's own agent-chat-ui, vendored unmodified.
UI_CHOICES = {"agent-chat-ui": "agent_chat_ui"}

MODEL_DEFAULTS = {
    "anthropic": "claude-opus-5",
    "openai": "gpt-5.5",
    "google": "gemini-2.5-pro",
}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def _install(dest: Path) -> None:
    """Install dependencies, but never fail the scaffold over it."""
    uv = find_executable("uv")
    if uv:
        console.print("[dim]installing python dependencies (uv)…[/dim]")
        result = subprocess.run(
            [uv, "sync", "--extra", "dev"], cwd=dest, capture_output=True, text=True
        )
        if result.returncode != 0:
            console.print("[yellow]![/yellow] uv sync failed; run it yourself later")
            console.print(f"[dim]{result.stderr.strip()[:400]}[/dim]")
    else:
        console.print("[yellow]![/yellow] uv not found — skipping python install")

    web = dest / "web"
    if web.is_dir():
        # The resolved path, not the bare name: on Windows npm and pnpm are
        # .cmd shims, which CreateProcess cannot launch by name.
        pm = package_manager()
        if pm is None:
            console.print("[yellow]![/yellow] no npm/pnpm found — skipping frontend install")
            return
        label = Path(pm).stem
        console.print(
            f"[dim]installing frontend dependencies ({label})… this takes a minute[/dim]"
        )
        result = subprocess.run([pm, "install"], cwd=web, capture_output=True, text=True)
        if result.returncode != 0:
            console.print(f"[yellow]![/yellow] {label} install failed; run it yourself in web/")
            console.print(f"[dim]{result.stderr.strip()[:400]}[/dim]")


def new(
    name: str = typer.Argument(None, help="Project name (lowercase, hyphens)."),
    directory: Path = typer.Option(None, "--dir", help="Where to create it. Default: ./<name>"),
    runtime: str = typer.Option(None, "--runtime", help="python or node."),
    model_provider: str = typer.Option(None, "--model-provider"),
    model_name: str = typer.Option(None, "--model"),
    frontend: bool = typer.Option(None, "--frontend/--no-frontend"),
    ui: str = typer.Option(
        None, "--ui", help="Chat UI. Only agent-chat-ui is available."
    ),
    memory: bool = typer.Option(
        None, "--memory/--no-memory", help="Long-term memory. Default: enabled."
    ),
    memory_backend: str = typer.Option(
        None, "--memory-backend", help=f"Where memories live: {', '.join(MEMORY_BACKENDS)}."
    ),
    semantic_search: bool = typer.Option(
        None, "--semantic-search/--no-semantic-search", help="Recall memories by meaning."
    ),
    embeddings: str = typer.Option(
        None, "--embeddings", help=f"Embeddings mode: {', '.join(EMBEDDING_MODES)}."
    ),
    embedding_model: str = typer.Option(None, "--embedding-model"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept defaults, ask nothing."),
    install: bool = typer.Option(True, "--install/--no-install"),
    git: bool = typer.Option(True, "--git/--no-git"),
) -> None:
    """Create a new agent project."""
    if name is None:
        if yes:
            raise LangctlError(
                "A project name is required with --yes", fix="langctl new my-agent"
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

    if frontend:
        # Only one UI, so nothing is asked; the flag stays for scripts that
        # already pass it and for a second UI later.
        if ui is not None and ui not in UI_CHOICES:
            raise LangctlError(
                f"Unknown --ui value {ui!r}",
                fix=f"Choose one of: {', '.join(UI_CHOICES)}",
            )
        frontend_kind = "agent_chat_ui"
    else:
        frontend_kind = "none"

    if model_provider is None:
        model_provider = (
            "anthropic"
            if yes
            else Prompt.ask(
                "Model provider", choices=list(MODEL_DEFAULTS), default="anthropic"
            )
        )
    model_name = model_name or MODEL_DEFAULTS.get(model_provider, "claude-opus-5")

    # Asked after the chat provider is known: the embeddings default depends on
    # it, and Anthropic in particular has no embeddings API of its own.
    flags_given = (
        memory is not None
        or semantic_search is not None
        or embeddings is not None
        or memory_backend is not None
    )
    if yes or flags_given:
        if embeddings is not None and embeddings not in EMBEDDING_MODES:
            raise LangctlError(
                f"Unknown --embeddings value {embeddings!r}",
                fix=f"Choose one of: {', '.join(EMBEDDING_MODES)}",
            )
        if memory_backend is not None and memory_backend not in MEMORY_BACKENDS:
            raise LangctlError(
                f"Unknown --memory-backend value {memory_backend!r}",
                fix=f"Choose one of: {', '.join(MEMORY_BACKENDS)}",
            )
        memory_config = memory_from_flags(
            model_provider,
            memory_enabled=True if memory is None else memory,
            semantic_search=bool(semantic_search),
            embeddings_mode=embeddings,
            embedding_model=embedding_model,
            backend=memory_backend or "sqlite",
        )
    else:
        memory_config = ask_memory(model_provider)

    spec = AgentSpec(
        name=name,
        runtime=runtime,  # type: ignore[arg-type]
        mode="proxy",
        model={"provider": model_provider, "name": model_name},  # type: ignore[arg-type]
        frontend={"enabled": frontend, "kind": frontend_kind},  # type: ignore[arg-type]
        memory=memory_config,  # type: ignore[arg-type]
        observability={"langsmith": True, "project": name},  # type: ignore[arg-type]
    )

    dest = (directory or Path.cwd() / name).resolve()
    if dest.exists() and any(dest.iterdir()):
        raise LangctlError(
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

    git_exe = find_executable("git")
    if git and git_exe and not (dest / ".git").exists():
        subprocess.run([git_exe, "init", "-q"], cwd=dest, check=False)

    if install:
        _install(dest)

    rel = dest.name if dest.parent == Path.cwd() else str(dest)
    console.print(
        Panel(
            f"[bold]1.[/bold] cd {rel}\n"
            f"[bold]2.[/bold] add your {spec.model.api_key_env} to [cyan].env[/cyan]\n"
            f"[bold]3.[/bold] langctl dev",
            title="[bold]next steps[/bold]",
            border_style="cyan",
            title_align="left",
        )
    )
