"""Styled `ask`/`confirm`/`select` — the diamond-bullet look, one place.

`ask` and `confirm` wrap Rich's own `Prompt`/`Confirm` rather than
reimplementing input handling: arrow keys, backspace, EOF, Ctrl-C during a
plain text prompt are all things Rich has already gotten right. Only the
surface — the bullet, the color, the question layout — is different from
calling `Prompt.ask` directly.

`select` is different: a fixed list of choices is exactly the case where
typing the option back is friction, so on a real terminal it renders as a
menu the user drives with the arrow keys (or `j`/`k`, or the number keys) and
confirms with Enter. Off a real terminal — piped input, `CliRunner` in tests,
CI — there is no cursor to move, so it falls back to the same typed-choice
`Prompt.ask` `ask` has always used; a test feeding `input="node\n"` keeps
working unchanged.
"""

from __future__ import annotations

import sys
from typing import Any

from rich.live import Live
from rich.prompt import Confirm, Prompt
from rich.text import Text

from .theme import BULLET, console

#: Rich's own sentinel for "no default was given" is `...`, not `None` — it
#: treats `default=None` as a *real* default value of `None`, so a bare
#: Enter would be accepted and return it. Passing `default=None` through this
#: wrapper would have silently turned every required prompt optional; caught
#: by reading `PromptBase.ask`'s actual signature rather than assuming.
_REQUIRED: Any = ...


def ask(question: str, *, default: Any = _REQUIRED, choices: list[str] | None = None) -> str:
    """A styled `Prompt.ask`.

    ``◆ Model provider (anthropic):``
    """
    label = f"{BULLET} {question}"
    return Prompt.ask(label, default=default, choices=choices, console=console)


def confirm(question: str, *, default: bool = True) -> bool:
    """A styled `Confirm.ask`."""
    label = f"{BULLET} {question}"
    return Confirm.ask(label, default=default, console=console)


def _read_key() -> str:
    """Block for one keypress, return a normalised name.

    Returns one of ``"up"``, ``"down"``, ``"enter"``, ``"interrupt"``, or the
    raw character for anything else (used for the ``j``/``k``/digit
    shortcuts). Escape sequences for arrow keys differ by platform, so this
    is the one place that has to know both.
    """
    if sys.platform == "win32":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):  # extended-key prefix
            ch2 = msvcrt.getwch()
            return {"H": "up", "P": "down"}.get(ch2, "other")
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03":
            return "interrupt"
        return ch

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            # Arrow keys arrive as ESC [ A/B/C/D; a lone ESC (menus, Alt-key
            # combos) must not block waiting for two bytes that never come.
            rest = sys.stdin.read(1)
            if rest == "[":
                final = sys.stdin.read(1)
                return {"A": "up", "B": "down"}.get(final, "other")
            return "other"
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03":
            return "interrupt"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _render_menu(question: str, choices: list[str], index: int) -> Text:
    body = Text()
    body.append(f"{BULLET} {question}\n", style="none")
    for i, choice in enumerate(choices):
        if i == index:
            body.append("    › ", style="bullet")
            body.append(f"{choice}\n", style="value")
        else:
            body.append("      ")
            body.append(f"{choice}\n", style="muted")
    body.append("  ↑/↓ to move, enter to select", style="muted")
    return body


def select(question: str, choices: list[str], *, default: Any = _REQUIRED) -> str:
    """`ask`, but for a fixed list of choices.

    On a real terminal this is an arrow-key menu: ↑/↓ (also `k`/`j`) move the
    highlighted choice, digits jump straight to an option, and Enter confirms
    it. Off a terminal — a pipe, `CliRunner` in tests — there is no cursor to
    move, so this falls back to Rich's typed `Prompt.ask(choices=...)`,
    listing the options first since more than two or three wraps badly
    inline.
    """
    if not choices:
        raise ValueError("select() needs at least one choice")

    if not console.is_terminal:
        console.print(f"{BULLET} {question}")
        for choice in choices:
            marker = "[value]›[/value]" if choice == default else " "
            console.print(f"    {marker} {choice}")
        return Prompt.ask(
            "  choose", default=default, choices=choices, console=console, show_choices=False
        )

    index = choices.index(default) if default in choices else 0
    with Live(
        _render_menu(question, choices, index), console=console, transient=True, auto_refresh=False
    ) as live:
        while True:
            key = _read_key()
            if key == "interrupt":
                raise KeyboardInterrupt
            elif key in ("up", "k"):
                index = (index - 1) % len(choices)
            elif key in ("down", "j"):
                index = (index + 1) % len(choices)
            elif key.isdigit() and 1 <= int(key) <= len(choices):
                index = int(key) - 1
            elif key == "enter":
                break
            live.update(_render_menu(question, choices, index), refresh=True)

    chosen = choices[index]
    console.print(f"{BULLET} {question} [value]{chosen}[/value]")
    return chosen
