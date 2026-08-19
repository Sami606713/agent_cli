"""`langctl init` — adopt an existing LangGraph project.

`new` creates a project from nothing; `init` is the other direction — it
looks at a project that already exists, infers what it safely can, asks for
what it cannot, and writes `agent.yaml`. Nothing else on disk changes: every
other langctl command becomes available, but no source file moves.

All the inference lives in `core.project.adopt.ProjectAdopter`; this module
only drives it and talks to the user.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from ..core.catalog.models import WIZARD_PROVIDERS, is_known
from ..core.catalog.models import get as get_provider
from ..core.errors import LangctlError
from ..core.project.adopt import Findings, ProjectAdopter

console = Console()


def init(
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Accept every inferred or defaulted value; ask nothing."
    ),
) -> None:
    """Turn the current directory into a langctl project, in place."""
    adopter = ProjectAdopter(Path.cwd())

    if adopter.already_a_langctl_project:
        raise LangctlError(
            "This is already a langctl project",
            fix="agent.yaml exists here. Run `langctl info` to see it.",
        )

    adopter.detect()
    findings = adopter.infer()

    _report(adopter, findings)
    provider, model = _settle_model(findings, yes=yes)

    if not findings.graph_path_is_conventional and not yes:
        proceed = typer.confirm(
            "Continue anyway? langctl will not move or rename anything.",
            default=False,
        )
        if not proceed:
            raise typer.Abort()

    spec = adopter.build_spec(findings, provider=provider, model=model)
    path = adopter.write(spec)

    console.print(
        Panel(
            f"[green]✓[/green] wrote {path.relative_to(adopter.root)}\n\n"
            "[bold]next[/bold]\n"
            "  langctl info              — see what was recorded\n"
            "  langctl add frontend       — add the chat UI\n"
            "  langctl add memory         — add long-term memory\n"
            "  langctl dev                — run it",
            title="[bold]adopted[/bold]",
            border_style="green",
            title_align="left",
        )
    )


def _report(adopter: ProjectAdopter, findings: Findings) -> None:
    console.print("[bold]detected[/bold]")
    console.print(f"  [green]✓[/green] name: {findings.name} [dim]({findings.name_source})[/dim]")

    if not adopter.found_langgraph_config:
        console.print("  [yellow]![/yellow] no langgraph.json found")
    elif findings.graph_id:
        marker = "[green]✓[/green]" if findings.graph_path_is_conventional else "[yellow]![/yellow]"
        console.print(f"  {marker} graph: {findings.graph_id} → {findings.graph_target}")
        if not findings.graph_path_is_conventional:
            console.print(
                f"    [yellow]langctl expects {findings.expected_graph_target!r}.[/yellow]\n"
                "    [dim]`sync`/`dev`/`deploy` will rewrite langgraph.json's "
                "`graphs` key to that path — your code is not moved, so it "
                "will point at a path that does not exist until you either "
                f"move the graph there or rename the package to match.[/dim]"
            )

    if findings.provider:
        console.print(
            f"  [green]✓[/green] model provider: {findings.provider} "
            f"[dim](from {findings.provider_source} in pyproject.toml)[/dim]"
        )
    else:
        console.print("  [yellow]![/yellow] could not infer a model provider")
    console.print()


def _settle_model(findings: Findings, *, yes: bool) -> tuple[str, str | None]:
    """The one thing worth asking about: which provider, since a wrong guess
    means every generated `.env.example` names the wrong key."""
    if findings.provider and is_known(findings.provider):
        return findings.provider, None

    if yes:
        # Nothing to infer and nothing to ask: anthropic is the same fallback
        # `new --yes` uses, for the same reason — a working default beats a
        # blocked command.
        return "anthropic", None

    provider = Prompt.ask(
        "Model provider"
        + (f" (guessed {findings.provider!r} but unrecognised)" if findings.provider else ""),
        choices=list(WIZARD_PROVIDERS),
        default="anthropic",
    )
    known = get_provider(provider)
    return provider, known.default_model if known else None
