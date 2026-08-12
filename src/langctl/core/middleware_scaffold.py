"""Boilerplate for a user-written middleware class.

Deliberately ships **no hook methods**. Which hooks a middleware needs is the
whole design decision, and pre-stubbing all six produces a file that is mostly
dead code someone has to read and delete. The docstring lists the available
hooks with their real signatures so the choice can be made without leaving the
file.
"""

from __future__ import annotations

import re

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
