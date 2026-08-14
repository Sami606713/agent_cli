"""`langctl new` — scaffold a project."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from ..core.catalog.models import PROVIDERS, WIZARD_PROVIDERS, is_known, suggest
from ..core.catalog.models import get as get_provider
from ..core.errors import LangctlError
from ..core.generate.scaffold import scaffold
from ..core.project.spec import AgentSpec
from ..core.runtime.executables import find as find_executable
from ..core.runtime.executables import package_manager
from ..core.runtime.process import run
from ..core.wizard.memory import (
    EMBEDDING_MODES,
    MEMORY_BACKENDS,
    ask_memory,
    memory_from_flags,
)

console = Console()

#: One chat UI: LangChain's own agent-chat-ui, vendored unmodified.
UI_CHOICES = {"agent-chat-ui": "agent_chat_ui"}




def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def _venv_has_langgraph(dest: Path) -> bool:
    """Did the Agent Server CLI actually land in the project's environment?

    Checked rather than assumed. `langgraph dev` imports the agent in-process,
    so this binary has to exist *here* — and a project missing it looks
    perfectly fine until the first `langctl dev`, which is far too late.
    """
    exe = "langgraph.exe" if sys.platform == "win32" else "langgraph"
    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    return (dest / ".venv" / bin_dir / exe).is_file()


def _install(dest: Path) -> list[str]:
    """Install every dependency into the project itself.

    Nothing goes on the machine globally: the agent's packages and the Agent
    Server CLI both belong to this project's `.venv`, which `uv sync` creates —
    fetching a compatible interpreter itself when the system Python is too new
    for the project's `requires-python`.

    Returns the commands the user still has to run. An empty list means the
    project is ready, and only then does the next-steps panel say so.
    """
    todo: list[str] = []

    uv = find_executable("uv")
    if uv is None:
        console.print("[yellow]![/yellow] uv not found — no Python dependencies installed")
        console.print("[dim]  install uv: https://docs.astral.sh/uv/getting-started/[/dim]")
        todo.append("uv sync --extra dev")
    else:
        console.print("[dim]installing python dependencies into .venv…[/dim]")
        result = run([uv, "sync", "--extra", "dev"], cwd=dest)
        if result.returncode != 0:
            console.print("[red]✗[/red] uv sync failed — the project cannot run yet")
            console.print(f"[dim]{result.stderr.strip()[-600:]}[/dim]")
            todo.append("uv sync --extra dev")
        elif not _venv_has_langgraph(dest):
            console.print("[yellow]![/yellow] the agent server CLI did not land in .venv")
            todo.append("uv add --dev 'langgraph-cli[inmem]'")
        else:
            console.print("[green]✓[/green] python dependencies installed in .venv")

    web = dest / "web"
    if web.is_dir():
        # The resolved path, not the bare name: on Windows npm and pnpm are
        # .cmd shims, which CreateProcess cannot launch by name.
        pm = package_manager()
        if pm is None:
            console.print("[yellow]![/yellow] no npm or pnpm found — the chat UI is not installed")
            console.print("[dim]  install Node.js 20+: https://nodejs.org[/dim]")
            todo.append("cd web && npm install")
        else:
            label = Path(pm).stem
            console.print(f"[dim]installing the chat UI ({label})… this takes a minute[/dim]")
            result = run([pm, "install"], cwd=web)
            if result.returncode != 0:
                console.print(f"[red]✗[/red] {label} install failed — the chat UI will not start")
                console.print(f"[dim]{result.stderr.strip()[-600:]}[/dim]")
                todo.append(f"cd web && {label} install")
            else:
                console.print("[green]✓[/green] chat UI installed")

    return todo


def new(
    name: str = typer.Argument(None, help="Project name (lowercase, hyphens)."),
    directory: Path = typer.Option(None, "--dir", help="Where to create it. Default: ./<name>"),
    runtime: str = typer.Option(None, "--runtime", help="python or node."),
    model_provider: str = typer.Option(None, "--model-provider"),
    model_name: str = typer.Option(None, "--model"),
    model_base_url: str = typer.Option(
        None, "--model-base-url", help="OpenAI-compatible endpoint (LM Studio, vLLM, a proxy)."
    ),
    model_package: str = typer.Option(
        None, "--model-package", help="Package supplying a provider langctl does not know."
    ),
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
                "Model provider",
                # A prompt listing 25 providers is unusable; the rest stay
                # reachable through --model-provider.
                choices=list(WIZARD_PROVIDERS),
                default="anthropic",
            )
        )
    if not is_known(model_provider) and not model_package:
        hint = suggest(model_provider)
        raise LangctlError(
            f"Unknown model provider {model_provider!r}",
            fix=(
                (f"Did you mean {' or '.join(hint)}? " if hint else "")
                + f"Choose one of the {len(PROVIDERS)} known providers, or pass "
                "--model-package so the dependency can be installed."
            ),
        )
    known = get_provider(model_provider)
    model_name = model_name or (known.default_model if known else None)
    if not model_name:
        # No safe default: this provider serves whatever the machine or gateway
        # has. Ask rather than guess a name that fails on the first message.
        if yes:
            raise LangctlError(
                f"--model is required for {model_provider}",
                fix="langctl new my-agent --model-provider "
                f"{model_provider} --model <model-name>",
            )
        if model_provider == "ollama":
            console.print(
                "\n[dim]ollama serves models you have pulled locally — "
                "run `ollama list` to see them.[/dim]"
            )
        model_name = Prompt.ask(f"Model name for {model_provider}").strip()
        if not model_name:
            raise LangctlError(
                f"A model name is required for {model_provider}",
                fix=f"Re-run and give a model {model_provider} serves.",
            )
    if known and known.note:
        console.print(f"[dim]{known.note}[/dim]")

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
        model={  # type: ignore[arg-type]
            "provider": model_provider,
            "name": model_name,
            **({"base_url": model_base_url} if model_base_url else {}),
            **({"package": model_package} if model_package else {}),
        },
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

    # Commands the user must run because an install did not complete. With
    # --no-install that is everything, by request.
    pending = _install(dest) if install else ["uv sync --extra dev"]

    rel = dest.name if dest.parent == Path.cwd() else str(dest)
    steps = [f"cd {rel}"]
    # An unfinished install comes first: the later steps cannot work without it.
    steps += [f"[yellow]{command}[/yellow]" for command in pending]
    # Local runtimes and ambient-credential providers have no key to add, so the
    # step would otherwise read "add your None to .env".
    if spec.model.api_key_env:
        steps.append(f"add your {spec.model.api_key_env} to [cyan].env[/cyan]")
    steps.append("langctl dev")
    console.print(
        Panel(
            "\n".join(f"[bold]{i}.[/bold] {s}" for i, s in enumerate(steps, 1)),
            title="[bold]next steps[/bold]" if not pending else "[bold]almost there[/bold]",
            border_style="cyan" if not pending else "yellow",
            title_align="left",
        )
    )
