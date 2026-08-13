"""Turning an AgentSpec into files on disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .deps import required_env_vars, runtime_packages
from .middleware import ORDER_LABEL, call_expressions, missing_config, ordered
from .render import render_layers, render_tree
from .spec import AgentSpec

#: Vercel's Hobby plan caps serverless functions at 60s. Agent runs regularly
#: exceed that, so this is surfaced in the template rather than buried.
DEFAULT_MAX_DURATION = 60


def render_context(spec: AgentSpec) -> dict[str, Any]:
    """Jinja context shared by every template."""
    return {
        "name": spec.name,
        "name_upper": spec.package_name.upper(),
        "pkg": spec.package_name,
        "runtime": spec.runtime,
        "mode": spec.mode,
        "graph_id": spec.graph_id,
        "model_provider": spec.model.provider,
        "model_name": spec.model.name,
        "model_key_env": spec.model.api_key_env,
        "model_base_url": spec.model.base_url,
        "model_options": spec.model.options,
        # A "provider:model" string carries no endpoint or options, so those
        # projects construct the model object instead.
        "model_needs_construction": spec.model.needs_construction,
        "langsmith": spec.observability.langsmith,
        "langsmith_project": spec.observability.project or spec.name,
        "backend_port": spec.backend.port,
        "frontend_port": spec.frontend.port,
        # agent-chat-ui mounts its passthrough at /api and we vendor its source
        # unmodified, so the prefix is fixed rather than configurable.
        "proxy_prefix": "/api",
        "max_duration": DEFAULT_MAX_DURATION,
        # memory
        "short_term_backend": spec.memory.short_term.backend,
        "short_term_path": spec.memory.short_term.path,
        "long_term_enabled": spec.memory.long_term.enabled,
        "long_term_backend": spec.memory.long_term.backend,
        "long_term_path": spec.memory.long_term.path,
        "semantic_search": spec.memory.long_term.semantic_search,
        "embedding_mode": spec.memory.long_term.embeddings.mode,
        "embedding_identifier": spec.memory.long_term.embeddings.identifier,
        "embedding_dims": spec.memory.long_term.embeddings.dims,
        "embedding_fields": spec.memory.long_term.embeddings.fields,
        # dependency fan-out: a feature and its package must never drift
        "runtime_packages": runtime_packages(spec),
        "required_env": required_env_vars(spec),
        **middleware_context(spec),
    }


def middleware_context(spec: AgentSpec) -> dict[str, Any]:
    """Imports and constructor calls for the middleware list, in execution order.

    Imports are grouped per module so the generated file has one import line per
    source rather than one per class.
    """
    entries = ordered(spec.middleware.enabled_keys())

    by_module: dict[str, list[str]] = {}
    rendered: list[dict[str, str]] = []
    previous_group: str | None = None
    for mw in entries:
        settings = spec.middleware.settings(mw.key)
        if missing_config(mw.key, settings):
            # Enabled without a required setting. Emitting the call would make
            # the project fail at import; leaving it out keeps it runnable, and
            # `sync` reports the omission.
            continue
        by_module.setdefault(mw.module, []).append(mw.cls)
        group = ORDER_LABEL[mw.order]
        # A middleware can produce several instances — PIIMiddleware takes one
        # pii_type each, so three types mean three entries in the list.
        for expression in call_expressions(mw, settings, spec.model.identifier):
            rendered.append(
                {
                    # Label the group only when it changes, so the list reads as
                    # sections rather than a repeated comment on every line.
                    "group": "" if group == previous_group else group,
                    "expression": expression,
                }
            )
            previous_group = group

    imports = [
        (module, _import_names(sorted(names))) for module, names in sorted(by_module.items())
    ]
    custom = [
        {"name": name, "cls": _custom_class_name(name)} for name in spec.middleware.custom
    ]
    return {
        "middleware_imports": imports,
        "middleware_entries": rendered,
        # Execution order follows agent.yaml, but imports and __all__ are sorted
        # so the generated package passes the ruff config it ships with.
        "middleware_custom": custom,
        "middleware_custom_sorted": sorted(custom, key=lambda entry: entry["name"]),
        "middleware_custom_names": _import_names(sorted(e["cls"] for e in custom)),
        "middleware_enabled": [m.key for m in entries],
    }


def _import_names(names: list[str]) -> str:
    """Render an import list, wrapping when it would exceed the line limit.

    Generated projects lint themselves at 100 columns, so a long single-line
    import would fail the user's own `ruff check`.
    """
    single = ", ".join(names)
    if len(single) <= 60:
        return single
    body = "".join(f"    {name},\n" for name in names)
    return f"(\n{body})"


def _custom_class_name(name: str) -> str:
    """rate_limit -> RateLimitMiddleware."""
    base = "".join(part.title() for part in name.replace("-", "_").split("_") if part)
    return base if base.endswith("Middleware") else f"{base}Middleware"


def backend_template(spec: AgentSpec) -> str:
    return f"backend/{spec.runtime}"


def frontend_templates(spec: AgentSpec) -> list[str]:
    """Template layers for the frontend.

    A single layer now. agent-chat-ui is a complete application with its own
    passthrough route, layout and build config, so there is nothing to share
    with it — the previous `_shared` layer existed to keep one proxy route
    across three hand-built UIs.
    """
    if not spec.frontend.enabled or spec.frontend.kind == "none":
        return []
    return [f"frontend/{spec.frontend.kind}"]


def scaffold(spec: AgentSpec, dest: Path, *, overwrite: bool = False) -> list[Path]:
    """Render every template for *spec* into *dest*."""
    context = render_context(spec)
    written: list[Path] = []

    result = render_tree(backend_template(spec), dest, context, overwrite=overwrite)
    written += result.written

    # The frontend is a separate npm project under web/ so its node_modules and
    # build output never tangle with the Python package.
    layers = frontend_templates(spec)
    if layers:
        result = render_layers(layers, dest / "web", context, overwrite=overwrite)
        written += result.written

    spec.save(dest / "agent.yaml")
    written.append(dest / "agent.yaml")

    written.append(write_langgraph_config(spec, dest / "langgraph.json"))
    return written


def merge_langgraph_config(spec: AgentSpec, existing: dict[str, Any]) -> dict[str, Any]:
    """Overlay the keys we own onto an existing config, preserving the rest.

    Hand-added keys (`auth`, `dockerfile_lines`, `checkpointer`, custom `http`
    settings…) must survive `langctl sync`, or editing langgraph.json becomes a
    trap.
    """
    merged = dict(existing)
    merged.update(spec.to_langgraph_config())
    return merged


def config_drift(spec: AgentSpec, existing: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Owned keys whose on-disk value differs from what the spec would generate."""
    generated = spec.to_langgraph_config()
    drift: dict[str, tuple[Any, Any]] = {}
    for key, value in generated.items():
        if key in existing and existing[key] != value:
            drift[key] = (existing[key], value)
    return drift


def write_langgraph_config(spec: AgentSpec, path: Path) -> Path:
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    path.write_text(
        json.dumps(merge_langgraph_config(spec, existing), indent=2) + "\n", encoding="utf-8"
    )
    return path
