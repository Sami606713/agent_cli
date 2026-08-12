"""Keeping the generated pyproject.toml's dependencies in step with agent.yaml.

Turning a feature on in `agent.yaml` changes generated code *and* what it needs
installed. Rewriting only `langgraph.json` leaves a project that passes
`langgraph validate` and then fails at server startup with a ModuleNotFoundError
— the exact trap recorded in plan 09.

Only the `dependencies = [...]` array inside `[project]` is touched. Everything
else in the file, including anything hand-added, is left byte-for-byte alone,
because this file is one a user is expected to edit.
"""

from __future__ import annotations

import re
from pathlib import Path

from .deps import runtime_packages
from .spec import AgentSpec

#: Matches the `dependencies = [ ... ]` array. Non-greedy up to the first
#: closing bracket at the start of a line, which is how we emit it.
_DEPENDENCIES = re.compile(
    r"(?P<head>^dependencies\s*=\s*\[)(?P<body>.*?)(?P<tail>^\])",
    re.M | re.S,
)


def render_dependencies(spec: AgentSpec) -> str:
    lines = "".join(f'    "{package}",\n' for package in runtime_packages(spec))
    return f"dependencies = [\n{lines}]"


def current_dependencies(text: str) -> list[str] | None:
    """Parse the dependency array currently in the file, or None if absent."""
    match = _DEPENDENCIES.search(text)
    if not match:
        return None
    return re.findall(r'"([^"]+)"', match.group("body"))


def dependency_drift(spec: AgentSpec, text: str) -> tuple[list[str], list[str]]:
    """(missing, extra) relative to what the spec requires.

    `extra` is reported, never removed: a user may legitimately have added
    packages of their own, and deleting those would be destructive.
    """
    present = current_dependencies(text) or []
    required = runtime_packages(spec)
    missing = [p for p in required if p not in present]
    # Only flag packages we manage; ignore anything the user added themselves.
    managed = {p.split(">=")[0].split("==")[0] for p in required}
    extra = [
        p
        for p in present
        if p not in required and p.split(">=")[0].split("==")[0] in managed
    ]
    return missing, extra


def sync_dependencies(spec: AgentSpec, path: Path) -> bool:
    """Rewrite the dependency array to match *spec*. Returns True if changed."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    match = _DEPENDENCIES.search(text)
    if not match:
        return False

    replacement = render_dependencies(spec)
    updated = text[: match.start()] + replacement + text[match.end() :]
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True
