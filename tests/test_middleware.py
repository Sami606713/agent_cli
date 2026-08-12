"""Middleware registry, ordering, and rendering.

The parameter names here were wrong on the first attempt — taken from docs
headings rather than the constructors — and only a real import caught it. These
tests pin the corrected shapes.
"""

from __future__ import annotations

import pytest

from langctl.core.middleware import (
    EXCLUDED,
    REGISTRY,
    call_expressions,
    conflicts_in,
    default_config,
    missing_config,
    ordered,
)
from langctl.core.scaffold import middleware_context, scaffold
from langctl.core.spec import AgentSpec

CHAT = "anthropic:claude-opus-5"


def spec(**middleware) -> AgentSpec:
    return AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"},
                     middleware=middleware or None) if middleware else AgentSpec(
        name="demo-agent", frontend={"enabled": False, "kind": "none"})


class TestDefaults:
    def test_cost_and_reliability_guards_are_on(self):
        # A generated agent must not be able to loop indefinitely.
        assert set(default_config()) == {"model_call_limit", "tool_call_limit", "tool_retry"}

    def test_limits_have_a_value(self):
        assert default_config()["model_call_limit"]["run_limit"] == 20
        assert default_config()["tool_call_limit"]["run_limit"] == 30


class TestOrdering:
    def test_execution_order_is_semantic(self):
        # Redaction must precede summarization, or raw content reaches the
        # summarizing model.
        keys = [m.key for m in ordered(["summarization", "pii", "tool_retry", "todo_list"])]
        assert keys.index("pii") < keys.index("summarization") < keys.index("tool_retry")
        assert keys[-1] == "todo_list"

    def test_order_is_independent_of_input_order(self):
        a = [m.key for m in ordered(["todo_list", "pii", "model_call_limit"])]
        b = [m.key for m in ordered(["model_call_limit", "todo_list", "pii"])]
        assert a == b

    def test_unknown_keys_are_ignored(self):
        assert [m.key for m in ordered(["pii", "not_a_middleware"])] == ["pii"]


class TestRendering:
    """Signatures verified against the installed classes, not the docs."""

    def test_limits_use_run_limit_not_max_calls(self):
        mw = REGISTRY["model_call_limit"]
        assert call_expressions(mw, {"run_limit": 20}, CHAT) == [
            "ModelCallLimitMiddleware(run_limit=20)"
        ]

    def test_summarization_defaults_to_the_project_chat_model(self):
        # `model` is required; asking the user to name it twice is friction.
        mw = REGISTRY["summarization"]
        assert call_expressions(mw, {}, CHAT) == [f"SummarizationMiddleware(model={CHAT!r})"]

    def test_pii_emits_one_instance_per_type(self):
        # PIIMiddleware takes a single pii_type, not a dict of strategies.
        mw = REGISTRY["pii"]
        calls = call_expressions(mw, {"types": ["email", "phone"], "strategy": "redact"}, CHAT)
        assert calls == [
            "PIIMiddleware('email', strategy='redact')",
            "PIIMiddleware('phone', strategy='redact')",
        ]

    def test_model_fallback_is_positional(self):
        mw = REGISTRY["model_fallback"]
        assert call_expressions(mw, {"models": ["openai:gpt-5.5", "x:y"]}, CHAT) == [
            "ModelFallbackMiddleware('openai:gpt-5.5', 'x:y')"
        ]

    def test_unset_options_are_omitted(self):
        # Absent means "use the library default", not "pass a value we invented".
        assert call_expressions(REGISTRY["todo_list"], {}, CHAT) == ["TodoListMiddleware()"]


class TestRequiredConfig:
    @pytest.mark.parametrize("key,field", [("model_fallback", "models"),
                                           ("human_in_the_loop", "interrupt_on")])
    def test_missing_required_config_is_reported(self, key, field):
        assert missing_config(key, {}) == [field]

    def test_satisfied_config_reports_nothing(self):
        assert missing_config("model_fallback", {"models": ["a"]}) == []

    def test_incomplete_middleware_is_omitted_from_the_generated_list(self):
        # Emitting the call would raise at import; the constructor has no default.
        s = spec(model_fallback={"enabled": True})
        expressions = [e["expression"] for e in middleware_context(s)["middleware_entries"]]
        assert not any("ModelFallback" in e for e in expressions)

    def test_tool_error_is_not_offered(self):
        # Its required on_error is a callable — not expressible in YAML.
        assert "tool_error" not in REGISTRY
        assert "tool_error" in EXCLUDED


class TestConflicts:
    def test_overlapping_middleware_are_reported(self):
        assert conflicts_in(["summarization", "context_editing"]) == [
            ("summarization", "context_editing")
        ]

    def test_each_pair_is_reported_once(self):
        assert len(conflicts_in(["summarization", "context_editing"])) == 1

    def test_no_false_positives(self):
        assert conflicts_in(["pii", "todo_list"]) == []


class TestGeneratedProject:
    def test_middleware_package_is_written(self, tmp_path):
        scaffold(spec(), tmp_path)
        assert (tmp_path / "src/demo_agent/middleware/__init__.py").is_file()
        assert (tmp_path / "src/demo_agent/middleware/custom.py").is_file()

    def test_agent_receives_the_list(self, tmp_path):
        scaffold(spec(), tmp_path)
        agent = (tmp_path / "src/demo_agent/agent.py").read_text()
        assert "middleware=MIDDLEWARE" in agent

    def test_group_labels_are_not_repeated(self, tmp_path):
        s = spec(model_call_limit={"enabled": True, "run_limit": 5},
                 tool_call_limit={"enabled": True, "run_limit": 5})
        groups = [e["group"] for e in middleware_context(s)["middleware_entries"]]
        assert groups == ["limits", ""]

    def test_long_import_lists_wrap(self, tmp_path):
        # Generated projects lint at 100 columns; a long import must not break it.
        s = spec(**{k: {"enabled": True} for k in
                    ("model_call_limit", "tool_call_limit", "tool_retry", "model_retry")})
        scaffold(s, tmp_path)
        source = (tmp_path / "src/demo_agent/middleware/__init__.py").read_text()
        assert all(len(line) <= 100 for line in source.splitlines())

    def test_anthropic_only_middleware_is_flagged(self):
        assert REGISTRY["prompt_caching"].requires_provider == "anthropic"
        assert REGISTRY["prompt_caching"].package == "langchain-anthropic>=1.0"


class TestCustomScaffold:
    def test_no_hooks_are_generated(self):
        """The user picks their own hooks; stubbing all six is dead code."""
        from langctl.core.middleware_scaffold import render

        source = render("rate limit")
        for hook in ("def before_model", "def after_model", "def wrap_model_call",
                     "def wrap_tool_call", "def before_agent", "def after_agent"):
            assert hook not in source
        assert "def __init__" in source

    def test_class_name_derivation(self):
        from langctl.core.middleware_scaffold import class_name

        assert class_name("rate limit") == "RateLimitMiddleware"
        assert class_name("auditLog") == "AuditLogMiddleware"
        assert class_name("my_thing_middleware") == "MyThingMiddleware"

    def test_hooks_are_documented_even_though_absent(self):
        from langctl.core.middleware_scaffold import render

        source = render("x")
        for hook in ("before_agent", "wrap_model_call", "wrap_tool_call", "after_agent"):
            assert hook in source
