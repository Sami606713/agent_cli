"""Scaffolding for a single tool module."""

from __future__ import annotations

import re

TOOL_TEMPLATE = '''"""The {name} tool."""

from __future__ import annotations

from langchain.tools import tool


@tool
def {symbol}(query: str) -> str:
    """One line saying when the model should call this.

    This docstring is prompt text — the model reads it to decide whether this
    tool applies. Describe the situation it is for, not how it works.

    Args:
        query: What to look up.
    """
    raise NotImplementedError("Implement {symbol}")
'''


def module_name(name: str) -> str:
    """'lookup order' or 'lookupOrder' -> 'lookup_order'."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", spaced).strip("_").lower()
    if not slug:
        raise ValueError(f"cannot derive a module name from {name!r}")
    if slug[0].isdigit():
        slug = f"tool_{slug}"
    return slug


def symbol_name(name: str) -> str:
    """Python function name for the tool. Same rules as the module."""
    return module_name(name)
