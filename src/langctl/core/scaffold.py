"""Turning an AgentSpec into files on disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
        "langsmith": spec.observability.langsmith,
        "langsmith_project": spec.observability.project or spec.name,
        "backend_port": spec.backend.port,
        "frontend_port": spec.frontend.port,
        "proxy_prefix": spec.frontend.proxy_prefix,
        # Route handlers must live at the path the client calls, so the
        # directory is derived from the prefix rather than hardcoded — otherwise
        # changing proxy_prefix in agent.yaml silently 404s every request.
        "proxy_route_dir": spec.frontend.proxy_prefix.lstrip("/"),
        "max_duration": DEFAULT_MAX_DURATION,
    }


def backend_template(spec: AgentSpec) -> str:
    return f"backend/{spec.runtime}"


#: Layer shared by every frontend: the proxy route, layout, Tailwind entry, and
#: build config. Rendered before the UI-specific layer, which may override files
#: (nextjs_ai_elements replaces globals.css to add its design tokens).
SHARED_FRONTEND_TEMPLATE = "frontend/_shared"


def frontend_templates(spec: AgentSpec) -> list[str]:
    """Template layers for the frontend, in render order.

    One shared layer plus one UI layer. Keeping the proxy route in exactly one
    place means a fix to it cannot land in two UIs and miss the third.
    """
    if not spec.frontend.enabled or spec.frontend.kind == "none":
        return []
    return [SHARED_FRONTEND_TEMPLATE, f"frontend/{spec.frontend.kind}"]


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
