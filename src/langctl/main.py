"""langctl — build, run, and deploy LangChain agents."""

from __future__ import annotations

import sys

import typer
from rich.console import Console

from . import __version__
from .commands.dev import dev
from .commands.doctor import doctor
from .commands.new import new
from .commands.sync import sync
from .core.errors import LangctlError

console = Console()

cli = typer.Typer(
    name="langctl",
    help="Build, run, and deploy LangChain agents. Frontend and agent in one command.",
    add_completion=False,
    pretty_exceptions_show_locals=False,
)

cli.command("new")(new)
cli.command("dev")(dev)
cli.command("sync")(sync)
cli.command("doctor")(doctor)


# invoke_without_command is required for `--version`: Click does not run a
# group's callback at all when no subcommand is present, so the flag would be
# unreachable and `langctl --version` would fail with "Missing command".
@cli.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show the version and exit."),
) -> None:
    if version:
        console.print(f"langctl {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


def app() -> None:
    """Console-script entry point.

    Anticipated failures are rendered as a panel with a fix rather than a
    traceback; anything else is a bug in langctl and keeps its traceback.
    """
    try:
        cli()
    except LangctlError as error:
        error.render(console)
        sys.exit(error.exit_code)
    except KeyboardInterrupt:
        console.print("\n[dim]interrupted.[/dim]")
        sys.exit(130)


if __name__ == "__main__":
    app()
