"""Rewriting a project's generated files after its spec changes.

A plain `overwrite=False` render is wrong for this: a file the template already
produced for the *old* spec exists, so it would be skipped, leaving the project
pointing at stale code. That is worse than an error — it silently yields a
project whose langgraph.json promises Postgres persistence while store.py still
returns a SQLite store.

So the comparison is against what the template *would have written before*.
Identical means untouched and safe to regenerate; different means the user
edited it, and it is left alone and reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..project.spec import AgentSpec
from .render import plan_layers
from .scaffold import backend_template, render_context


@dataclass
class Regenerated:
    written: list[Path]
    skipped: list[Path]


def apply_spec_change(root: Path, old: AgentSpec, new: AgentSpec) -> Regenerated:
    """Rewrite the files the backend template owns, for a changed spec.

    Args:
        root: Project root.
        old: The spec the existing files were generated from.
        new: The spec they should match now.

    Returns:
        Which files were rewritten, and which were left alone because the user
        had edited them.
    """
    layers = [backend_template(new)]
    before = plan_layers(layers, root, render_context(old))
    after = plan_layers(layers, root, render_context(new))

    written: list[Path] = []
    skipped: list[Path] = []
    for path, content in sorted(after.items()):
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if current == content:
                continue  # already correct
            if current != before.get(path):
                skipped.append(path)  # user-modified: never clobbered
                continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)

    return Regenerated(written=written, skipped=skipped)
