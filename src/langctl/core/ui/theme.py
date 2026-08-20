"""One console, one palette, one set of symbols — used by every command.

Before this, each command file created its own bare ``Console()``. Nothing was
wrong with that individually, but it meant no two commands' checkmarks, colors
or spacing were guaranteed to match — the CLI read as fourteen small tools
rather than one product. Importing from here instead of instantiating
``Console()`` is the entire fix; nothing else has to change.
"""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

#: One accent hue, calm neutrals — the same restraint `AgentSpec.brand_hue`
#: applies to a generated project's own mark. A CLI in every Rich named color
#: reads as unstyled, not styled.
THEME = Theme(
    {
        "brand": "bold cyan",
        "muted": "dim",
        "ok": "green",
        "warn": "yellow",
        "error": "bold red",
        "bullet": "cyan",
        "value": "bold white",
    }
)

#: The one Console every command should import. Rich already detects a
#: non-terminal (a pipe, a log file, CI) and drops color and animation on its
#: own — nothing here has to special-case that.
console = Console(theme=THEME)

#: Symbols, defined once so "success" and "failure" look identical everywhere
#: they appear, in every command's output.
CHECK = "[ok]✓[/ok]"
CROSS = "[error]✗[/error]"
WARN = "[warn]![/warn]"
BULLET = "[bullet]◆[/bullet]"
ARROW = "[muted]›[/muted]"


def interactive() -> bool:
    """True when it is worth spending a banner or a styled prompt here.

    A script piping `langctl new --yes` through CI, or output redirected to a
    file, gets plain text either way — Rich already handles that. This is the
    coarser question: is anyone actually watching this run right now? A
    banner in a log file is noise, not polish.
    """
    return console.is_terminal
