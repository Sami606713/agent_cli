"""Typed errors.

Every failure the user can hit should be an ``LangctlError`` carrying a *fix* —
the concrete next command or edit. Bare tracebacks are for bugs in langctl, not
for conditions we anticipated.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel


class LangctlError(Exception):
    """Base class for anticipated failures.

    Args:
        message: What went wrong, in one line.
        fix: What the user should do about it. Shown verbatim, so make it copy-pasteable.
        detail: Optional extra context (a log tail, a path, upstream stderr).
    """

    exit_code = 1

    def __init__(self, message: str, fix: str | None = None, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.fix = fix
        self.detail = detail

    def render(self, console: Console) -> None:
        body = [f"[bold red]{self.message}[/bold red]"]
        if self.detail:
            body.append("")
            body.append(f"[dim]{self.detail}[/dim]")
        if self.fix:
            body.append("")
            body.append(f"[bold]Fix:[/bold] {self.fix}")
        console.print(Panel("\n".join(body), border_style="red", title="error", title_align="left"))


class ProjectNotFound(LangctlError):
    """No agent.yaml in this directory or any parent."""

    def __init__(self, start: str):
        super().__init__(
            f"No langctl project found at or above {start}",
            fix="Run `langctl new <name>` to create one, or cd into an existing project.",
        )


class PortInUse(LangctlError):
    def __init__(self, port: int, role: str, holder: str | None = None):
        detail = f"Port {port} is held by: {holder}" if holder else None
        super().__init__(
            f"Port {port} ({role}) is already in use",
            fix=(
                f"Stop whatever is using it, or pass "
                f"`--{'backend-port' if role == 'agent' else 'port'} <other>`."
            ),
            detail=detail,
        )


class BackendStartFailed(LangctlError):
    """The Agent Server never became healthy.

    The backend's own output is the useful part here, so it is always attached:
    a bad import or a missing key shows up there, not in anything we could say.
    """

    def __init__(self, reason: str, log_tail: str | None = None):
        super().__init__(
            f"The agent server failed to start: {reason}",
            fix="Check the agent log above. Run `langctl doctor` to verify your environment.",
            detail=log_tail,
        )


class MissingDependency(LangctlError):
    def __init__(self, binary: str, install: str):
        super().__init__(
            f"Required program not found: {binary}",
            fix=f"Install it: {install}",
        )


class SpecError(LangctlError):
    """agent.yaml is malformed or internally inconsistent."""

    def __init__(self, message: str, fix: str | None = None):
        super().__init__(message, fix=fix or "Edit agent.yaml, then run `langctl sync`.")
