"""`langctl info` — what this project is, at a glance.

Everything shown here already lives in `agent.yaml`; this is a formatted read,
not new logic. Its job is to answer "what did I set up here again?" without
opening the YAML — the same question `shopify app info` answers for an app.
"""

from __future__ import annotations

from ..core.ui.theme import console, WARN
from rich.table import Table

from ..core.deploy import catalog
from ..core.project.manifest import Project
from ..core.runtime.health import is_port_free



def _row(table: Table, label: str, value: str) -> None:
    table.add_row(f"[dim]{label}[/dim]", value)


def info() -> None:
    """Summarise the current project: model, memory, frontend, deploy target."""
    project = Project.load()
    spec = project.spec

    table = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
    table.add_column(justify="right")
    table.add_column()

    _row(table, "project", f"[bold]{spec.name}[/bold]  ({project.root})")
    _row(table, "runtime", f"{spec.runtime}, {spec.mode} mode")

    model = spec.model
    model_line = f"{model.provider} / {model.name}" if model.name else model.provider
    if model.base_url:
        model_line += f"  [dim]({model.base_url})[/dim]"
    _row(table, "model", model_line)

    long_term = spec.memory.long_term
    if long_term.enabled:
        memory_line = f"{long_term.backend}"
        if long_term.semantic_search:
            memory_line += ", semantic search on"
    else:
        memory_line = "disabled"
    _row(table, "memory", memory_line)

    if spec.frontend.enabled:
        frontend_line = f"{spec.frontend.kind}, port {spec.frontend.port}"
    else:
        frontend_line = "none (--no-frontend)"
    _row(table, "frontend", frontend_line)

    _row(table, "backend port", str(spec.backend.port))

    enabled_middleware = [
        name
        for name, cfg in spec.middleware.model_dump().items()
        if name != "custom" and isinstance(cfg, dict) and cfg.get("enabled")
    ]
    enabled_middleware += spec.middleware.custom
    _row(table, "middleware", ", ".join(enabled_middleware) if enabled_middleware else "none")

    if spec.deploy.target:
        target = catalog.get(spec.deploy.target)
        label = target.label if target else spec.deploy.target
        _row(table, "deploy target", label)
    else:
        _row(table, "deploy target", "[dim]not chosen yet — `langctl deploy` will ask[/dim]")

    ports = []
    for port, role in ((spec.backend.port, "agent"), (spec.frontend.port, "web")):
        state = "[dim]free[/dim]" if is_port_free(port) else "[yellow]in use[/yellow]"
        ports.append(f"{port} ({role}) {state}")
    _row(table, "ports", "  ·  ".join(ports))

    console.print(table)
