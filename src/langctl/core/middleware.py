"""The built-in middleware registry.

`create_agent(middleware=[...])` takes a **sequence**, and the order is the
execution order — so it is semantic, not cosmetic. PII redaction placed after
summarization means raw PII already reached the summarizing model. langctl
therefore emits a fixed order derived from what each middleware does, rather
than the order keys happen to appear in agent.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Execution order, by role. Lower runs earlier.
#:
#: 1 guardrails   redact and block before anything sees the content
#: 2 context      compress or prune what remains
#: 3 limits       cap the work before it is attempted
#: 4 reliability  retries and fallbacks around the attempt
#: 5 human        pause for a person
#: 6 capability   extra tools and abilities
#: 7 custom       always last, so user code sees a fully prepared request
GUARDRAILS, CONTEXT, LIMITS, RELIABILITY, HUMAN, CAPABILITY, CUSTOM = range(1, 8)

ORDER_LABEL = {
    GUARDRAILS: "guardrails",
    CONTEXT: "context",
    LIMITS: "limits",
    RELIABILITY: "reliability",
    HUMAN: "human-in-the-loop",
    CAPABILITY: "capability",
    CUSTOM: "custom",
}


@dataclass(frozen=True)
class Middleware:
    """One built-in, and everything needed to configure and emit it."""

    key: str
    cls: str
    order: int
    summary: str
    #: agent.yaml field -> constructor keyword. Fields absent from the config
    #: are simply not passed, so the library's own default applies.
    params: dict[str, str] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    #: Import module. Defaults to the core middleware namespace.
    module: str = "langchain.agents.middleware"
    #: Extra package this middleware needs, if any.
    package: str | None = None
    #: Restrict to a chat provider (prompt caching is Anthropic-only).
    requires_provider: str | None = None
    #: On for every new project.
    default_enabled: bool = False
    #: Middleware that overlap with this one; enabling both warrants a warning.
    conflicts: tuple[str, ...] = ()
    note: str | None = None
    #: Config keys rendered as positional arguments, in order.
    positional: tuple[str, ...] = ()
    #: When set, one instance is emitted per element of this config list.
    per_item: str | None = None
    #: Substitute the project's chat model when `model` is not set explicitly.
    uses_chat_model: bool = False
    #: Config keys that must be provided; enabling without them is an error.
    requires_config: tuple[str, ...] = ()


REGISTRY: dict[str, Middleware] = {
    m.key: m
    for m in (
        # ---- guardrails ----------------------------------------------------
        Middleware(
            key="pii",
            cls="PIIMiddleware",
            order=GUARDRAILS,
            summary="detect and redact personal data before the model sees it",
            # One instance per PII type: the constructor is
            # PIIMiddleware(pii_type, strategy=...), not a dict of strategies.
            per_item="types",
            positional=("pii_type",),
            params={"strategy": "strategy"},
            defaults={"types": ["email"], "strategy": "redact"},
        ),
        # ---- context -------------------------------------------------------
        Middleware(
            key="summarization",
            cls="SummarizationMiddleware",
            order=CONTEXT,
            summary="compress history once it grows past a threshold",
            # `model` is required and is the *summarizing* model; it accepts the
            # same "provider:model" string as create_agent.
            params={"model": "model", "trigger": "trigger"},
            defaults={"model": None},
            uses_chat_model=True,
            conflicts=("context_editing",),
        ),
        Middleware(
            key="context_editing",
            cls="ContextEditingMiddleware",
            order=CONTEXT,
            summary="prune old tool output from the context window",
            conflicts=("summarization",),
        ),
        # ---- limits --------------------------------------------------------
        Middleware(
            key="model_call_limit",
            cls="ModelCallLimitMiddleware",
            order=LIMITS,
            summary="cap model calls per run — the main runaway-cost guard",
            params={"run_limit": "run_limit", "thread_limit": "thread_limit"},
            defaults={"run_limit": 20},
            default_enabled=True,
        ),
        Middleware(
            key="tool_call_limit",
            cls="ToolCallLimitMiddleware",
            order=LIMITS,
            summary="cap tool calls per run",
            params={"run_limit": "run_limit", "thread_limit": "thread_limit"},
            defaults={"run_limit": 30},
            default_enabled=True,
        ),
        # ---- reliability ---------------------------------------------------
        Middleware(
            key="tool_retry",
            cls="ToolRetryMiddleware",
            order=RELIABILITY,
            summary="retry a failed tool call before giving up",
            params={"max_retries": "max_retries"},
            defaults={"max_retries": 2},
            default_enabled=True,
        ),
        Middleware(
            key="model_retry",
            cls="ModelRetryMiddleware",
            order=RELIABILITY,
            summary="retry a failed model call",
            params={"max_retries": "max_retries"},
            defaults={"max_retries": 2},
        ),
        Middleware(
            key="model_fallback",
            cls="ModelFallbackMiddleware",
            order=RELIABILITY,
            summary="fail over to another model when the primary errors",
            # ModelFallbackMiddleware(first_model, *additional_models) — all
            # positional, so the config is a plain list of model identifiers.
            positional=("models",),
            defaults={"models": []},
            requires_config=("models",),
        ),
        # ---- human ---------------------------------------------------------
        Middleware(
            key="human_in_the_loop",
            cls="HumanInTheLoopMiddleware",
            order=HUMAN,
            summary="pause for approval before chosen tools run",
            params={"interrupt_on": "interrupt_on"},
            defaults={"interrupt_on": {}},
            requires_config=("interrupt_on",),
            note=(
                "Runs pause until a person responds, so the frontend must render "
                "interrupts. The bundled chat UIs do."
            ),
        ),
        # ---- capability ----------------------------------------------------
        Middleware(
            key="llm_tool_selector",
            cls="LLMToolSelectorMiddleware",
            order=CAPABILITY,
            summary="narrow the tool list before each model call",
        ),
        Middleware(
            key="todo_list",
            cls="TodoListMiddleware",
            order=CAPABILITY,
            summary="give the agent a task list it can plan against",
        ),
        Middleware(
            key="llm_tool_emulator",
            cls="LLMToolEmulator",
            order=CAPABILITY,
            summary="fake tool results with the model, for testing",
        ),
        Middleware(
            key="prompt_caching",
            cls="AnthropicPromptCachingMiddleware",
            order=CAPABILITY,
            summary="cache the prompt prefix to cut Anthropic costs",
            module="langchain_anthropic.middleware",
            package="langchain-anthropic>=1.0",
            requires_provider="anthropic",
        ),
    )
}

#: Deliberately absent from the registry.
#:
#: ShellToolMiddleware, the Filesystem* middleware and the execution policies:
#: granting an agent shell or filesystem access is a security decision to make
#: deliberately in code, not by toggling a flag.
#:
#: ToolErrorMiddleware: its required `on_error` is a callable, which cannot be
#: expressed in agent.yaml. Write it as custom middleware instead.
EXCLUDED = ("shell_tool", "filesystem", "execution_policy", "tool_error")


def default_config() -> dict[str, dict[str, Any]]:
    """The middleware block a brand-new project starts with."""
    config: dict[str, dict[str, Any]] = {}
    for key, mw in REGISTRY.items():
        if mw.default_enabled:
            config[key] = {"enabled": True, **mw.defaults}
    return config


def ordered(enabled: list[str]) -> list[Middleware]:
    """Sort enabled keys into execution order.

    Ties are broken by registry position so the output is deterministic and
    does not depend on the order keys appear in agent.yaml.
    """
    positions = {key: index for index, key in enumerate(REGISTRY)}
    known = [REGISTRY[k] for k in enabled if k in REGISTRY]
    return sorted(known, key=lambda m: (m.order, positions[m.key]))


def conflicts_in(enabled: list[str]) -> list[tuple[str, str]]:
    """Pairs of enabled middleware that overlap in purpose."""
    active = set(enabled)
    seen: set[frozenset[str]] = set()
    found: list[tuple[str, str]] = []
    for key in enabled:
        mw = REGISTRY.get(key)
        if not mw:
            continue
        for other in mw.conflicts:
            if other in active and frozenset((key, other)) not in seen:
                seen.add(frozenset((key, other)))
                found.append((key, other))
    return found


def call_expressions(mw: Middleware, config: dict[str, Any], chat_model: str) -> list[str]:
    """Render the constructor call(s) for one middleware.

    A list, not a string, because some middleware take one instance per subject:
    PIIMiddleware handles a single `pii_type`, so three PII types mean three
    instances.

    Only keys present in the config are passed, so anything left unset keeps the
    library's own default instead of us pinning a value we invented.
    """
    subjects = config.get(mw.per_item) or [None] if mw.per_item else [None]
    return [_one_call(mw, config, chat_model, subject) for subject in subjects]


def _one_call(mw: Middleware, config: dict[str, Any], chat_model: str, subject: Any) -> str:
    args: list[str] = []

    for name in mw.positional:
        if name == mw.per_item or (mw.per_item and subject is not None and not config.get(name)):
            args.append(repr(subject))
            continue
        value = config.get(name)
        if isinstance(value, list):
            args.extend(repr(v) for v in value)
        elif value is not None:
            args.append(repr(value))

    for field_name, keyword in mw.params.items():
        value = config.get(field_name)
        # The summarizing model defaults to the project's chat model rather than
        # forcing the user to name it twice.
        if value is None and field_name == "model" and mw.uses_chat_model:
            value = chat_model
        if value in (None, {}, [], ()):
            continue
        args.append(f"{keyword}={value!r}")

    return f"{mw.cls}({', '.join(args)})"


def missing_config(key: str, config: dict[str, Any]) -> list[str]:
    """Required settings this middleware was enabled without."""
    mw = REGISTRY.get(key)
    if not mw:
        return []
    return [name for name in mw.requires_config if not config.get(name)]
