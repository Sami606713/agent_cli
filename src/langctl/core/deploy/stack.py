"""Emitting the deployment stack into a project.

Four containers on one host — web, agent, Postgres, Redis — with only the
frontend published. That is the same single-origin topology `langctl dev`
runs, so nothing about the frontend changes between development and
production: it reaches the agent by a service name that never moves, and there
is no deployment URL for anyone to copy or forget to update.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..generate.render import RenderResult, render_tree
from ..generate.scaffold import render_context
from ..project.spec import AgentSpec

#: Template layer, rendered into the project root.
LAYER = "deploy/compose"

#: Templated for the default stack; written by `langgraph dockerfile` for the
#: licensed one, which needs the base image langgraph.json knows about.
AGENT_DOCKERFILE = "Dockerfile.agent"

#: Everything the stack needs, relative to the project root. Used to check that
#: a deploy has all its parts before it starts building images.
STACK_FILES = (
    "docker-compose.yml",
    ".dockerignore",
    ".env.deploy.example",
)

#: Only meaningful when the deployment includes the chat UI.
FRONTEND_FILES = ("web/Dockerfile", "web/.dockerignore")


def deploy_context(
    spec: AgentSpec,
    *,
    web_host_port: int,
    domain: str | None,
    licensed: bool = False,
    frontend: bool | None = None,
) -> dict[str, Any]:
    """Scaffold context plus the values only deployment needs."""
    return {
        **render_context(spec),
        "web_host_port": web_host_port,
        # Whether this deployment carries the chat UI. Defaults to what the
        # project has; `--backend-only` overrides it. With no UI there is no
        # proxy, so the agent publishes the port itself.
        "frontend": spec.frontend.enabled if frontend is None else frontend,
        # When set, Caddy fronts the stack and terminates TLS; web stops
        # publishing a port of its own.
        "domain": domain,
        # False: the in-memory agent server, which needs no licence, no
        # Postgres and no Redis. True: LangChain's production Agent Server,
        # which needs all three.
        "licensed": licensed,
    }


def emit(
    spec: AgentSpec,
    root: Path,
    *,
    web_host_port: int = 3000,
    domain: str | None = None,
    licensed: bool = False,
    frontend: bool | None = None,
    overwrite: bool = False,
) -> RenderResult:
    """Write the stack into *root*.

    Existing files are kept unless *overwrite*, so a tuned compose file is not
    silently replaced on the next deploy.
    """
    context = deploy_context(
        spec,
        web_host_port=web_host_port,
        domain=domain,
        licensed=licensed,
        frontend=frontend,
    )
    result = render_tree(LAYER, root, context, overwrite=overwrite)
    if not context["frontend"]:
        # A backend-only deployment has no web service, and a stray web/
        # Dockerfile with no application beside it only invites a failed build.
        result = _drop(result, [root / rel for rel in FRONTEND_FILES], unlink=True)
    if licensed:
        # `langgraph dockerfile` writes this one instead; ours would be
        # overwritten anyway, and shipping both would be confusing.
        result = _drop(result, [root / AGENT_DOCKERFILE], unlink=True)
    if not domain:
        # Without a domain there is no Caddy service to read it, and a stray
        # Caddyfile would imply TLS that is not actually configured.
        result = _drop(result, [root / "Caddyfile"], unlink=True)
    return result


def _drop(result: RenderResult, paths: list[Path], *, unlink: bool) -> RenderResult:
    """Remove *paths* from disk and from the report of what was written."""
    if unlink:
        for path in paths:
            path.unlink(missing_ok=True)
            # Take the directory too if we emptied it — a bare `web/` with
            # nothing in it looks like a half-finished scaffold.
            parent = path.parent
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
    return RenderResult(
        written=[p for p in result.written if p not in paths],
        skipped=[p for p in result.skipped if p not in paths],
    )


def missing_files(root: Path, *, domain: str | None = None, frontend: bool = True) -> list[str]:
    """Which stack files are absent from *root*."""
    expected = [*STACK_FILES]
    if frontend:
        expected += FRONTEND_FILES
    if domain:
        expected.append("Caddyfile")
    return [rel for rel in expected if not (root / rel).exists()]
