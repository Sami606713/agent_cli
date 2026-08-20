"""Styled `ask`/`confirm`/`select` — the diamond-bullet look, one place.

These wrap Rich's own `Prompt`/`Confirm` rather than reimplementing input
handling: arrow keys, backspace, EOF, Ctrl-C during a prompt are all things
Rich has already gotten right. Only the surface — the bullet, the color, the
question layout — is different from calling `Prompt.ask` directly.
"""

from __future__ import annotations

from typing import Any

from rich.prompt import Confirm, Prompt

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


def select(question: str, choices: list[str], *, default: Any = _REQUIRED) -> str:
    """`ask`, but the choices are shown on their own line first.

    Rich's `Prompt.ask(choices=...)` already lists them inline in parentheses,
    which is fine for two or three short options; past that it wraps badly.
    This is for the longer lists — providers, deploy targets.
    """
    console.print(f"{BULLET} {question}")
    for choice in choices:
        marker = "[value]›[/value]" if choice == default else " "
        console.print(f"    {marker} {choice}")
    return Prompt.ask(
        "  choose", default=default, choices=choices, console=console, show_choices=False
    )
