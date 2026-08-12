"""Surgical edits to an existing agent.yaml.

`AgentSpec.save()` rewrites the whole file from the model, which is right for
`langctl new` and wrong for `langctl add`: it would silently drop any comment or
key ordering the user cared about. These helpers change one subtree and leave
the rest alone as far as the YAML round-trip allows.

PyYAML cannot preserve comments. Rather than add a dependency for it, we detect
comments and keep a backup, so a user who annotated the file can recover it.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml

#: A line whose first non-space character is `#`, ignoring the leading document
#: marker. Inline trailing comments are not detected — they are rare in a
#: generated file and would produce noisy false positives.
_COMMENT_LINE = re.compile(r"^\s*#", re.M)


def has_comments(text: str) -> bool:
    return bool(_COMMENT_LINE.search(text))


def backup(path: Path) -> Path:
    """Copy the file next to itself, so an unwanted rewrite is recoverable."""
    target = path.with_suffix(path.suffix + ".bak")
    shutil.copyfile(path, target)
    return target


def merge_section(path: Path, key: str, value: Any) -> tuple[bool, Path | None]:
    """Replace one top-level section of agent.yaml.

    Returns (changed, backup_path). The backup is only made when the file has
    comments that the round-trip would discard.
    """
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}

    if data.get(key) == value:
        return False, None

    made_backup = backup(path) if has_comments(text) else None

    data[key] = value
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return True, made_backup


def register_tool(path: Path, module: str, symbol: str) -> bool:
    """Add a tool to the generated TOOLS registry.

    Returns False when the registry no longer looks like the one we generated —
    the user has restructured it, and guessing where to splice would be worse
    than telling them the two lines to add.
    """
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")

    if symbol in text:
        return False  # already registered

    import_match = re.search(r"^from [\w.]+\.tools\.[\w.]+ import .*$", text, re.M)
    list_match = re.search(r"^TOOLS = \[\n", text, re.M)
    if not import_match or not list_match:
        return False

    package = re.match(r"^from ([\w.]+)\.tools\.", import_match.group(0)).group(1)
    new_import = f"from {package}.tools.{module} import {symbol}\n"

    text = text[: import_match.end() + 1] + new_import + text[import_match.end() + 1 :]
    list_match = re.search(r"^TOOLS = \[\n", text, re.M)
    text = text[: list_match.end()] + f"    {symbol},\n" + text[list_match.end() :]

    path.write_text(text, encoding="utf-8")
    return True
