"""`langctl add` — bring a feature into a project that already exists.

`new` decides everything once; `add` is the same machinery scoped to one
feature, on a directory that already has code in it. The difference that
matters is destructiveness: every render here runs with ``overwrite=False``, so
a file you have edited is skipped and reported, never rewritten.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from ..core.errors import LangctlError
from ..core.manifest import Project
from ..core.memory_wizard import MEMORY_BACKENDS, ask_memory, memory_from_flags
from ..core.middleware import REGISTRY, conflicts_in, missing_config, ordered
from ..core.middleware_scaffold import class_name, module_key
from ..core.middleware_scaffold import render as render_custom
from ..core.pyproject import sync_dependencies
from ..core.render import plan_layers, render_layers
from ..core.scaffold import (
    backend_template,
    frontend_templates,
    render_context,
    write_langgraph_config,
)
from ..core.spec import AgentSpec
from ..core.spec_edit import merge_section, register_tool
from ..core.tool_scaffold import TOOL_TEMPLATE, module_name, symbol_name

console = Console()

app = typer.Typer(
    name="add",
    help="Add a feature to an existing project.",
    no_args_is_help=True,
)


def _report(written: list, skipped: list) -> None:
    for path in written:
        console.print(f"  [green]+[/green] {path.name}")
    if skipped:
        console.print(
            f"  [dim]{len(skipped)} file(s) already existed and were left alone:[/dim]"
        )
        for path in skipped:
            console.print(f"    [dim]· {path.name}[/dim]")


def _warn_shadowed_modules(project: Project) -> None:
    """Flag a legacy `X.py` now shadowed by a new `X/` package.

    Projects scaffolded before 0.3 kept tools and prompts as single modules.
    Adding a feature renders the package form beside them, and Python resolves
    the package first — so the old file stays on disk, is never imported, and
    silently ignores every edit made to it. Nothing errors; the code just has
    no effect, which is the worst way to find out.
    """
    package_dir = project.root / "src" / project.spec.package_name
    shadowed = [
        module
        for name in ("tools", "prompts", "memory")
        if (module := package_dir / f"{name}.py").is_file() and (package_dir / name).is_dir()
    ]
    if not shadowed:
        return

    console.print(
        "\n[yellow]![/yellow] These files are now shadowed by a package of the "
        "same name and will never be imported:"
    )
    for module in shadowed:
        console.print(f"    [dim]{module.relative_to(project.root)}[/dim]")
    console.print(
        "  [dim]Move anything you still need into the package, then delete "
        "them. Editing them has no effect.[/dim]"
    )


def _apply(project: Project, old: AgentSpec, spec: AgentSpec) -> None:
    """Write derived files for a changed spec.

    A plain overwrite=False render is wrong here: a file the template already
    produced for the *old* spec exists, so it would be skipped, leaving the
    project pointing at stale code. That is worse than an error — it silently
    yields a project whose langgraph.json promises persistence while store.py
    still returns an in-memory store.

    So the comparison is against what the template *would have written before*.
    Identical means untouched and safe to regenerate; different means the user
    edited it and it is left alone.
    """
    layers = [backend_template(spec)]
    before = plan_layers(layers, project.root, render_context(old))
    after = plan_layers(layers, project.root, render_context(spec))

    written: list = []
    skipped: list = []
    for path, content in sorted(after.items()):
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if current == content:
                continue  # already correct
            if current != before.get(path):
                skipped.append(path)  # user-modified
                continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)

    _report(written, skipped)

    write_langgraph_config(spec, project.langgraph_config_path)
    console.print("  [green]✓[/green] langgraph.json")

    if sync_dependencies(spec, project.root / "pyproject.toml"):
        console.print("  [green]✓[/green] pyproject.toml (dependencies)")


@app.command("memory")
def add_memory(
    backend: str = typer.Option(None, "--backend", help=f"{', '.join(MEMORY_BACKENDS)}"),
    semantic_search: bool = typer.Option(None, "--semantic-search/--no-semantic-search"),
    embeddings: str = typer.Option(None, "--embeddings", help="local, provider or custom"),
    embedding_model: str = typer.Option(None, "--embedding-model"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept defaults, ask nothing."),
) -> None:
    """Add or reconfigure long-term memory."""
    project = Project.load()
    spec = project.spec

    if spec.memory.long_term.enabled and not (yes or backend or semantic_search is not None):
        current = spec.memory.long_term
        console.print(
            f"[yellow]![/yellow] Long-term memory is already enabled "
            f"({current.backend}"
            f"{', semantic search on' if current.semantic_search else ''})."
        )
        if not typer.confirm("Reconfigure it?", default=False):
            raise typer.Exit()

    flags_given = backend is not None or semantic_search is not None or embeddings is not None
    if yes or flags_given:
        memory = memory_from_flags(
            spec.model.provider,
            memory_enabled=True,
            semantic_search=bool(semantic_search),
            embeddings_mode=embeddings,
            embedding_model=embedding_model,
            backend=backend or spec.memory.long_term.backend,
        )
    else:
        memory = ask_memory(spec.model.provider)

    # Keep whatever short_term setting the project already had.
    memory["short_term"] = spec.memory.short_term.model_dump()
    updated = spec.model_copy(update={"memory": type(spec.memory)(**memory)})

    changed, backup_path = merge_section(project.spec_path, "memory", memory)
    if backup_path:
        console.print(
            f"  [dim]comments in agent.yaml were dropped; backup at {backup_path.name}[/dim]"
        )
    if not changed:
        console.print("[dim]agent.yaml already matched — writing derived files anyway.[/dim]")

    _apply(project, spec, updated)
    console.print(
        Panel(
            "[bold]1.[/bold] uv sync\n"
            + (
                "[bold]2.[/bold] set POSTGRES_URI in .env\n[bold]3.[/bold] langctl dev"
                if updated.memory.long_term.backend == "postgres"
                else "[bold]2.[/bold] langctl dev"
            ),
            title="[bold]next[/bold]",
            border_style="cyan",
            title_align="left",
        )
    )


@app.command("frontend")
def add_frontend(
    ui: str = typer.Option("assistant-ui", "--ui", help="assistant-ui, minimal or ai-elements"),
) -> None:
    """Add a chat frontend to a backend-only project."""
    from .new import UI_CHOICES

    project = Project.load()
    if ui not in UI_CHOICES:
        raise LangctlError(
            f"Unknown --ui value {ui!r}", fix=f"Choose one of: {', '.join(UI_CHOICES)}"
        )

    spec = project.spec
    if spec.frontend.enabled and project.frontend_dir.is_dir():
        console.print(f"[yellow]![/yellow] A frontend already exists ({spec.frontend.kind}).")
        if not typer.confirm("Add the new one alongside it?", default=False):
            raise typer.Exit()

    frontend = {**spec.frontend.model_dump(), "enabled": True, "kind": UI_CHOICES[ui]}
    updated = spec.model_copy(update={"frontend": type(spec.frontend)(**frontend)})

    _, backup_path = merge_section(project.spec_path, "frontend", frontend)
    if backup_path:
        console.print(f"  [dim]backup at {backup_path.name}[/dim]")

    result = render_layers(
        frontend_templates(updated),
        project.frontend_dir,
        render_context(updated),
        overwrite=False,
    )
    _report(result.written, result.skipped)
    write_langgraph_config(updated, project.langgraph_config_path)

    console.print(
        Panel(
            "[bold]1.[/bold] cd web && npm install\n[bold]2.[/bold] langctl dev",
            title="[bold]next[/bold]",
            border_style="cyan",
            title_align="left",
        )
    )


@app.command("tool")
def add_tool(
    name: str = typer.Argument(..., help="Tool name, e.g. 'lookup order' or lookup_order."),
) -> None:
    """Scaffold a new tool and register it."""
    project = Project.load()
    module = module_name(name)
    symbol = symbol_name(name)

    tools_dir = project.root / "src" / project.spec.package_name / "tools"
    if not tools_dir.is_dir():
        raise LangctlError(
            f"No tools package at {tools_dir}",
            fix="This project predates langctl 0.3. Create src/<pkg>/tools/ first.",
        )

    target = tools_dir / f"{module}.py"
    if target.exists():
        raise LangctlError(
            f"{target.name} already exists", fix="Pick another name, or edit that file."
        )

    target.write_text(TOOL_TEMPLATE.format(symbol=symbol, name=name), encoding="utf-8")
    console.print(f"  [green]+[/green] tools/{target.name}")

    if register_tool(tools_dir / "__init__.py", module, symbol):
        console.print("  [green]✓[/green] registered in TOOLS")
    else:
        # The registry has been restructured; splicing blindly would be worse
        # than telling the user exactly what to add.
        console.print(
            "  [yellow]![/yellow] could not auto-register — add these to tools/__init__.py:"
        )
        console.print(
            f"      [cyan]from {project.spec.package_name}.tools.{module} "
            f"import {symbol}[/cyan]"
        )
        console.print(f"      [cyan]TOOLS = [..., {symbol}][/cyan]")

    console.print(f"\n[dim]Edit tools/{target.name}, then `langctl dev`.[/dim]")


@app.command("middleware")
def add_middleware(
    name: str = typer.Argument(None, help="Built-in middleware key, e.g. summarization."),
    custom: str = typer.Option(None, "--custom", help="Scaffold your own middleware class."),
    list_available: bool = typer.Option(False, "--list", help="Show the registry."),
) -> None:
    """Enable a built-in middleware, or scaffold a custom one."""
    project = Project.load()
    spec = project.spec

    if list_available:
        enabled = set(spec.middleware.enabled_keys())
        for mw in ordered(list(REGISTRY)):
            mark = "[green]on [/green]" if mw.key in enabled else "[dim]off[/dim]"
            console.print(f"  {mark} [cyan]{mw.key:20s}[/cyan] {mw.summary}")
        if spec.middleware.custom:
            console.print(f"  [green]on [/green] [cyan]custom[/cyan]: "
                          f"{', '.join(spec.middleware.custom)}")
        return

    if custom:
        _add_custom_middleware(project, custom)
        return

    if not name:
        raise LangctlError(
            "Give a middleware name, or --custom <name> to write your own",
            fix="langctl add middleware --list",
        )

    mw = REGISTRY.get(name)
    if mw is None:
        raise LangctlError(
            f"Unknown middleware {name!r}", fix="langctl add middleware --list"
        )
    if mw.requires_provider and spec.model.provider != mw.requires_provider:
        raise LangctlError(
            f"{name} requires the {mw.requires_provider} provider; "
            f"this project uses {spec.model.provider}",
            fix="Change model.provider in agent.yaml, or pick another middleware.",
        )

    block = spec.middleware.model_dump()
    if block.get(name, {}).get("enabled"):
        console.print(f"[yellow]![/yellow] {name} is already enabled.")
        raise typer.Exit()

    settings = {"enabled": True, **mw.defaults}
    absent = missing_config(name, settings)
    if absent:
        # Emitting the call anyway would produce a file that fails at import —
        # the constructor raises rather than defaulting.
        raise LangctlError(
            f"{name} needs {' and '.join(absent)} before it can be enabled",
            fix=(
                f"Add it under middleware.{name} in agent.yaml, then run "
                "`langctl sync`."
            ),
        )

    block[name] = settings
    _write_middleware(project, spec, block)

    if mw.note:
        console.print(f"  [dim]{mw.note}[/dim]")
    for a, b in conflicts_in([k for k, v in block.items()
                              if isinstance(v, dict) and v.get("enabled")]):
        console.print(
            f"  [yellow]![/yellow] {a} and {b} overlap in purpose; "
            "enabling both may produce surprising behaviour."
        )


def _add_custom_middleware(project: Project, name: str) -> None:
    """Write one module per middleware, mirroring how tools/ works.

    A file each rather than a shared module: middleware grow, and a single
    custom.py becomes a merge-conflict site the moment two people add one.
    """
    key = module_key(name)
    package = project.root / "src" / project.spec.package_name / "middleware" / "custom"
    if not package.is_dir():
        raise LangctlError(
            f"No custom middleware package at {package}",
            fix="This project predates middleware support. Run `langctl sync` first.",
        )

    cls = class_name(key)
    target = package / f"{key}.py"
    if target.exists():
        raise LangctlError(
            f"middleware/custom/{target.name} already exists",
            fix="Pick another name, or edit that file.",
        )

    target.write_text(render_custom(key), encoding="utf-8")
    console.print(f"  [green]+[/green] middleware/custom/{target.name} :: {cls}")

    block = project.spec.middleware.model_dump()
    block.setdefault("custom", [])
    if key not in block["custom"]:
        block["custom"].append(key)
    _write_middleware(project, project.spec, block)
    console.print(f"\n[dim]Add the hooks you need to {cls}, then `langctl dev`.[/dim]")


def _write_middleware(project: Project, spec: AgentSpec, block: dict) -> None:
    """Persist the middleware block and regenerate the derived list."""
    _, backup_path = merge_section(project.spec_path, "middleware", block)
    if backup_path:
        console.print(f"  [dim]backup at {backup_path.name}[/dim]")

    updated = spec.model_copy(update={"middleware": type(spec.middleware)(**block)})
    _apply(project, spec, updated)
