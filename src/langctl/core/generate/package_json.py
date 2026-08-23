"""Keeping the generated package.json's dependencies in step with agent.yaml.

The typescript-runtime counterpart to `pyproject.py`. Same reasoning: turning a
feature on in `agent.yaml` changes generated code *and* what it needs
installed, so `langgraph.json` alone is not enough — a project that passes
`langgraph validate` can still die at startup with a missing module.

Only the `dependencies` object is touched. `devDependencies`, scripts, and
anything else in the file — including anything hand-added — are left alone,
because package.json is a file a user is expected to edit.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..project.spec import AgentSpec
from .deps import npm_packages


def current_dependencies(text: str) -> dict[str, str] | None:
    """Parse the `dependencies` object currently in the file, or None if absent."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    deps = data.get("dependencies")
    return dict(deps) if isinstance(deps, dict) else None


def dependency_drift(spec: AgentSpec, text: str) -> tuple[list[str], list[str]]:
    """(missing, extra) package names relative to what the spec requires.

    `extra` is reported, never removed: a user may have added packages of
    their own, and deleting those would be destructive.
    """
    present = current_dependencies(text) or {}
    required = npm_packages(spec)
    missing = [name for name in required if name not in present]
    extra = [name for name in present if name not in required]
    return missing, extra


def sync_dependencies(spec: AgentSpec, path: Path) -> bool:
    """Rewrite the `dependencies` object to match *spec*. Returns True if changed."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False

    required = npm_packages(spec)
    existing = data.get("dependencies") if isinstance(data.get("dependencies"), dict) else {}
    # Keep the user's own extras; only the packages langctl manages are synced
    # to what the spec currently requires.
    merged = {**existing, **required}
    if merged == existing:
        return False
    data["dependencies"] = merged
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True
