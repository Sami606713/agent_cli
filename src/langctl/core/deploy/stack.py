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
    "web/Dockerfile",
    "web/.dockerignore",
)


def deploy_context(
    spec: AgentSpec, *, web_host_port: int, domain: str | None, licensed: bool = False
) -> dict[str, Any]:
    """Scaffold context plus the values only deployment needs."""
    return {
        **render_context(spec),
        "web_host_port": web_host_port,
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
    overwrite: bool = False,
) -> RenderResult:
    """Write the stack into *root*.

    Existing files are kept unless *overwrite*, so a tuned compose file is not
    silently replaced on the next deploy.
    """
    context = deploy_context(
        spec, web_host_port=web_host_port, domain=domain, licensed=licensed
    )
    result = render_tree(LAYER, root, context, overwrite=overwrite)
    if licensed:
        # `langgraph dockerfile` writes this one instead; ours would be
        # overwritten anyway, and shipping both would be confusing.
        dockerfile = root / AGENT_DOCKERFILE
        dockerfile.unlink(missing_ok=True)
        result = RenderResult(
            written=[p for p in result.written if p != dockerfile],
            skipped=[p for p in result.skipped if p != dockerfile],
        )
    if domain:
        return result
    # Without a domain there is no Caddy service to read it, and a stray
    # Caddyfile in the repo would imply TLS that is not actually configured.
    caddyfile = root / "Caddyfile"
    caddyfile.unlink(missing_ok=True)
    return RenderResult(
        written=[p for p in result.written if p != caddyfile],
        skipped=[p for p in result.skipped if p != caddyfile],
    )


def missing_files(root: Path, *, domain: str | None = None) -> list[str]:
    """Which stack files are absent from *root*."""
    expected = [*STACK_FILES, *(["Caddyfile"] if domain else [])]
    return [rel for rel in expected if not (root / rel).exists()]
