"""Source text for the single-file things a user adds.

A tool and a custom middleware are both "one module, one symbol, registered
somewhere" — same shape, same escaping concerns, so they live together rather
than in two modules that would drift apart.
"""

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


CUSTOM_TEMPLATE = '''"""Custom middleware: {name}."""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware


class {cls}(AgentMiddleware):
    """One line on what this middleware does.

    Add only the hooks you need — every one is optional, and each has an async
    twin (prefix `a`, e.g. `abefore_model`) used automatically when the agent
    runs asynchronously.

        before_agent(self, state, runtime) -> dict | None
            Once, before the run starts. Return a state update, or None.

        before_model(self, state, runtime) -> dict | None
            Before each model call. Inject context, or short-circuit.

        wrap_model_call(self, request, handler) -> ModelResponse | AIMessage
            Around each model call. Call handler(request) to proceed; you may
            retry it, alter request first, or return without calling it.

        wrap_tool_call(self, request, handler) -> ToolMessage | Command
            Around each tool call. Same shape as wrap_model_call.

        after_model(self, state, runtime) -> dict | None
            After each model response. Validate or record.

        after_agent(self, state, runtime) -> dict | None
            Once, when the run finishes.
    """

    name = "{name}"

    def __init__(self) -> None:
        super().__init__()
        # Configuration goes here. The instance is created for you in
        # middleware/__init__.py, after every built-in has run.
'''


def class_name(name: str) -> str:
    """rate_limit -> RateLimitMiddleware."""
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_")
    if not slug:
        raise ValueError(f"cannot derive a class name from {name!r}")
    base = "".join(part[:1].upper() + part[1:] for part in slug.split("_") if part)
    return base if base.endswith("Middleware") else f"{base}Middleware"


def module_key(name: str) -> str:
    """Normalised key recorded under `middleware.custom` in agent.yaml."""
    slug = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", slug).strip("_").lower()
    if not slug:
        raise ValueError(f"cannot derive a name from {name!r}")
    return slug


def render(name: str) -> str:
    return CUSTOM_TEMPLATE.format(name=module_key(name), cls=class_name(name))
