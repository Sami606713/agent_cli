"""The one brand moment: a wordmark shown at the start of `new` and `dev`.

Deliberately not shown on every command — `doctor`, `info`, `env show` and the
rest are consulted mid-task, not launched, and a banner there is noise. This
is reserved for the two moments someone is actually starting something and
watching the terminal do it.
"""

from __future__ import annotations

from pyfiglet import Figlet

from .theme import console, interactive

#: "small" reads clean at 80 columns and does not dominate the terminal the
#: way "standard" or "slant" do — checked against all three before choosing.
_FONT = "small"


def show(version: str) -> None:
    """Print the wordmark, unless nobody would see it."""
    if not interactive():
        return
    art = Figlet(font=_FONT).renderText("langctl").rstrip("\n")
    console.print(f"[brand]{art}[/brand]")
    console.print(f"[muted]v{version}[/muted]\n")
