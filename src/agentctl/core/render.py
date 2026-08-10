"""Template rendering.

A template is a directory tree shipped inside the package. Rendering rules:

* ``*.j2``            → rendered with Jinja2, suffix stripped
* everything else     → copied verbatim (binary-safe)
* a path segment that is *exactly* ``__name__`` → replaced from the context
* ``dot.foo``         → written as ``.foo``

Placeholders must be a whole segment. Matching them anywhere in a name would
capture ``__init__.py``, which is a real filename, not a placeholder.

The ``dot.`` prefix exists for packaging, not style: a template literally named
``.gitignore`` or ``.env.example`` gets dropped from the built wheel by
VCS-aware build backends and by the repo's own ignore rules, so the scaffold
would silently ship without them.

Verbatim copy matters: frontend templates contain ``{{ }}`` in TSX and ``${...}``
in CSS that must not be interpreted, so only files explicitly marked ``.j2`` are
treated as templates.
"""

from __future__ import annotations

import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates"

_PLACEHOLDER = re.compile(r"__([a-z_]+)__")


@dataclass
class RenderResult:
    written: list[Path]
    skipped: list[Path]


def _jinja() -> Environment:
    # StrictUndefined: a typo in a template must fail the scaffold, not silently
    # emit an empty string into someone's production config.
    return Environment(
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def substitute_path(name: str, context: dict[str, Any]) -> str:
    """Resolve one path segment.

    Only a segment that is entirely ``__key__`` is treated as a placeholder, so
    ``__init__.py`` and ``__main__.py`` survive untouched.
    """
    match = _PLACEHOLDER.fullmatch(name)
    if match:
        key = match.group(1)
        if key not in context:
            raise KeyError(f"template path placeholder __{key}__ has no value in context")
        return str(context[key])
    if name.startswith("dot."):
        return name[3:]
    return name


def render_tree(
    template: str | Path,
    dest: Path,
    context: dict[str, Any],
    *,
    overwrite: bool = False,
) -> RenderResult:
    """Render one template directory into *dest*.

    Args:
        template: Name of a directory under ``templates/``, or an absolute path.
        dest: Destination directory; created if absent.
        context: Jinja context, also used for ``__placeholder__`` path segments.
        overwrite: When False, existing files are left alone and reported as
            skipped. `agentctl add` relies on this to be non-destructive.
    """
    src = Path(template)
    if not src.is_absolute():
        src = TEMPLATE_ROOT / template
    if not src.is_dir():
        raise FileNotFoundError(f"template not found: {src}")

    env = _jinja()
    written: list[Path] = []
    skipped: list[Path] = []

    for path in sorted(src.rglob("*")):
        if path.is_dir():
            continue
        if any(part in {"__pycache__", ".DS_Store"} for part in path.parts):
            continue

        rel = path.relative_to(src)
        out_parts = [substitute_path(p, context) for p in rel.parts]
        out = dest.joinpath(*out_parts)
        is_template = out.name.endswith(".j2")
        if is_template:
            out = out.with_name(out.name[:-3])

        if out.exists() and not overwrite:
            skipped.append(out)
            continue

        out.parent.mkdir(parents=True, exist_ok=True)
        if is_template:
            text = env.from_string(path.read_text(encoding="utf-8")).render(**context)
            out.write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(path, out)

        # Preserve the executable bit so shipped shell scripts stay runnable.
        if path.stat().st_mode & stat.S_IXUSR:
            out.chmod(out.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        written.append(out)

    return RenderResult(written=written, skipped=skipped)


def available_templates(kind: str) -> list[str]:
    """List template names under ``templates/<kind>/``."""
    root = TEMPLATE_ROOT / kind
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())
