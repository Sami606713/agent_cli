"""Running Node CLIs (npx) as an optional post-scaffold step.

Some UI libraries ship components through a registry CLI rather than npm — the
files are copied into the project. That means a network call during `langctl
new`, which must never be able to fail or hang the scaffold: a project on a
plane, behind a corporate proxy, or in an air-gapped CI box still has to come
out complete and valid.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Registry CLIs prompt when they detect a TTY. Scaffolding must stay
#: non-interactive or `langctl new` hangs forever in CI.
NON_INTERACTIVE_ENV = {"CI": "1", "NPM_CONFIG_YES": "true", "ADBLOCK": "1"}

DEFAULT_TIMEOUT = 180.0


@dataclass
class CommandResult:
    ok: bool
    command: str
    output: str
    reason: str | None = None

    @property
    def manual_hint(self) -> str:
        return self.command


def npx_available() -> bool:
    return shutil.which("npx") is not None


def run_npx(
    args: list[str],
    cwd: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> CommandResult:
    """Run `npx <args>` in *cwd*, never raising.

    Returns a result the caller can report; the caller decides whether a failure
    is fatal. For scaffolding it never is — we print the command so the user can
    finish the job by hand.
    """
    command = "npx " + " ".join(args)

    if not npx_available():
        return CommandResult(False, command, "", "npx not found (Node.js is not installed)")

    try:
        completed = subprocess.run(
            ["npx", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**NON_INTERACTIVE_ENV, **_inherited_env()},
            stdin=subprocess.DEVNULL,  # a prompt gets EOF instead of hanging
        )
    except subprocess.TimeoutExpired:
        return CommandResult(False, command, "", f"timed out after {timeout:.0f}s")
    except OSError as exc:
        return CommandResult(False, command, "", str(exc))

    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        tail = output.strip().splitlines()[-3:]
        return CommandResult(False, command, output, " / ".join(tail) or "non-zero exit")
    return CommandResult(True, command, output)


def _inherited_env() -> dict[str, str]:
    import os

    return dict(os.environ)


#: Components the AI Elements template's Chat.tsx imports. Keep in sync with it.
AI_ELEMENTS_COMPONENTS = [
    "conversation",
    "message",
    "prompt-input",
    "tool",
    "reasoning",
]


def add_ai_elements(web_dir: Path, timeout: float = DEFAULT_TIMEOUT) -> CommandResult:
    """Copy AI Elements component source into the project."""
    return run_npx(
        ["--yes", "ai-elements@latest", "add", *AI_ELEMENTS_COMPONENTS],
        web_dir,
        timeout=timeout,
    )
