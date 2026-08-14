"""Feature → package and env-var mapping.

A feature that changes generated code almost always needs a dependency too, and
a missing one is a *boot* failure the config validator does not catch: enabling
semantic search without the embeddings package makes the Agent Server exit
during startup while `langgraph validate` still reports the config as valid.

Keeping the mapping here means a template and its requirements cannot drift.
"""

from __future__ import annotations

from ..catalog.middleware import REGISTRY
from ..project.spec import AgentSpec

#: Memory backend → packages supplying its saver and its store.
#:
#: Postgres spells out psycopg's binary wheel. langgraph-checkpoint-postgres
#: depends on bare `psycopg`, which is the pure-Python package and needs a
#: system libpq to do anything at all. libpq is usually present on a developer
#: machine and never in a slim container, so the agent imported cleanly locally
#: and died at start-up in Docker with "no pq wrapper available".
MEMORY_PACKAGES: dict[str, list[str]] = {
    "sqlite": ["langgraph-checkpoint-sqlite>=3.0"],
    "postgres": ["langgraph-checkpoint-postgres>=3.0", "psycopg[binary]>=3.2"],
    "memory": [],  # ships with langgraph
}

#: Embeddings provider → package.
EMBEDDING_PACKAGES: dict[str, str] = {
    "openai": "langchain-openai>=1.0",
    "cohere": "langchain-cohere>=1.0",
    "mistralai": "langchain-mistralai>=1.0",
    "google_vertexai": "langchain-google-vertexai>=3.0",
    "ollama": "langchain-ollama>=1.0",
    "bedrock": "langchain-aws>=1.0",
}

#: Local embeddings pull the whole torch stack — multiple GB. Surfaced in the
#: wizard rather than discovered during a slow first install.
LOCAL_EMBEDDING_PACKAGE = "sentence-transformers>=5.0"


def runtime_packages(spec: AgentSpec) -> list[str]:
    """Third-party packages the generated project needs, deduplicated."""
    packages: list[str] = ["langchain>=1.0", "langgraph>=1.0"]

    # The registry knows 25 providers; an unknown one must declare its package,
    # so this is never a silent no-op.
    provider_package = spec.model.package_requirement
    if provider_package:
        packages.append(provider_package)

    packages += MEMORY_PACKAGES.get(spec.memory.short_term.backend, [])

    if spec.memory.long_term.enabled:
        packages += MEMORY_PACKAGES.get(spec.memory.long_term.backend, [])

        if spec.memory.long_term.semantic_search:
            embeddings = spec.memory.long_term.embeddings
            if embeddings.mode == "local":
                packages.append(LOCAL_EMBEDDING_PACKAGE)
            elif embeddings.mode == "provider":
                embedding_package = EMBEDDING_PACKAGES.get(embeddings.provider)
                if embedding_package:
                    packages.append(embedding_package)

    # A middleware whose package is missing is a startup failure that
    # `langgraph validate` reports as valid — same trap as the embeddings driver.
    for key in spec.middleware.enabled_keys():
        mw = REGISTRY.get(key)
        if mw and mw.package:
            packages.append(mw.package)

    # Preserve order while removing duplicates: the model and embedding
    # providers are frequently the same package.
    return list(dict.fromkeys(packages))


def required_env_vars(spec: AgentSpec) -> dict[str, str]:
    """Env var → why it is needed. Drives .env.example and `langctl doctor`."""
    # Some providers need no key at all — a local runtime, or ambient cloud
    # credentials — so this can legitimately be empty.
    required: dict[str, str] = {}
    if spec.model.api_key_env:
        required[spec.model.api_key_env] = f"chat model ({spec.model.identifier})"
    if spec.model.model_from_env:
        # No safe default exists — see ModelSpec.model_from_env.
        required["MODEL_NAME"] = f"model served by {spec.model.provider}"

    if spec.memory.short_term.backend == "postgres" or (
        spec.memory.long_term.enabled and spec.memory.long_term.backend == "postgres"
    ):
        required["POSTGRES_URI"] = "postgres memory backend"

    if spec.memory.long_term.enabled and spec.memory.long_term.semantic_search:
        key = spec.memory.long_term.embeddings.api_key_env
        if key:
            required[key] = f"embeddings ({spec.memory.long_term.embeddings.identifier})"

    return required
