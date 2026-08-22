"""Sync new/updated vendored frontend files into an existing project.

A project's `web/` directory is a snapshot taken at scaffold time — nothing
re-copies it when the template changes (e.g. a new langctl release adding a
route like `/studio`). This gives `langctl sync --frontend` something to do
about that, using the same non-destructive semantics `langctl add` already
relies on: a file that exists in the project is left alone, only files the
template has that the project doesn't get written.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..project.spec import AgentSpec
from .render import RenderResult, plan_layers, render_layers
from .scaffold import frontend_templates, render_context


def sync_frontend_files(spec: AgentSpec, frontend_dir: Path) -> RenderResult:
    """Add any template files missing from *frontend_dir*.

    Never overwrites a file that already exists — a project's own edits
    (rebranding, customized components) are indistinguishable from vendored
    files once written, so the only safe move is to add what's missing.
    """
    layers = frontend_templates(spec)
    if not layers:
        return RenderResult(written=[], skipped=[])
    context = render_context(spec)
    return render_layers(layers, frontend_dir, context, overwrite=False)


def missing_frontend_dependencies(spec: AgentSpec, frontend_dir: Path) -> dict[str, dict[str, str]]:
    """Dependencies the current template declares that the project's
    package.json does not, grouped by `dependencies`/`devDependencies`.
    """
    layers = frontend_templates(spec)
    package_json_path = frontend_dir / "package.json"
    if not layers or not package_json_path.is_file():
        return {}

    context = render_context(spec)
    planned = plan_layers(layers, frontend_dir, context)
    template_text = planned.get(package_json_path)
    if template_text is None:
        return {}

    template_pkg = json.loads(template_text)
    actual_pkg = json.loads(package_json_path.read_text(encoding="utf-8"))

    missing: dict[str, dict[str, str]] = {}
    for section in ("dependencies", "devDependencies"):
        actual_section = actual_pkg.get(section, {})
        new_entries = {
            name: version
            for name, version in template_pkg.get(section, {}).items()
            if name not in actual_section
        }
        if new_entries:
            missing[section] = new_entries
    return missing


def add_frontend_dependencies(frontend_dir: Path, missing: dict[str, dict[str, str]]) -> None:
    """Write *missing* into package.json, leaving everything else untouched."""
    package_json_path = frontend_dir / "package.json"
    data = json.loads(package_json_path.read_text(encoding="utf-8"))
    for section, entries in missing.items():
        data.setdefault(section, {}).update(entries)
    package_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
