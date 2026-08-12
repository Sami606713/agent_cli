"""Interactive memory configuration.

Kept out of `new.py` so the same questions can be reused by `langctl add memory`
and by any future `langctl configure`, rather than being duplicated.

Progressive disclosure is deliberate. Long-term memory costs nothing and needs
no services, so it is simply on. Semantic search costs money and pulls in a
vendor, so it is asked about — and only if you say yes do you get asked how the
vectors are produced. A beginner sees one extra question; someone who wants
vector search sees three.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.prompt import Confirm, Prompt

from .spec import EMBEDDING_DIMS, EMBEDDING_PROVIDER_FOR_CHAT

console = Console()

EMBEDDING_MODES = ["local", "provider", "custom"]

MEMORY_BACKENDS = ["sqlite", "postgres"]

BACKEND_SUMMARY = {
    "sqlite": "a local file — nothing to run, but single-writer and single-machine",
    "postgres": "a server you provide via POSTGRES_URI — needed for more than one replica",
}

#: Sensible default model per embeddings provider, so the wizard never has to
#: ask for a model name whose dimensions we would then have to guess.
DEFAULT_EMBEDDING_MODEL: dict[str, str] = {
    "openai": "text-embedding-3-small",
    "cohere": "embed-english-v3.0",
    "mistralai": "mistral-embed",
    "google_vertexai": "text-embedding-004",
    "ollama": "nomic-embed-text",
}

DEFAULT_LOCAL_MODEL = "nomic-ai/nomic-embed-text-v1.5"

MODE_SUMMARY = {
    "local": "runs on your machine — no API key, no per-item cost, but downloads torch (GB)",
    "provider": "hosted API — fastest to set up, needs a key, costs per item stored",
    "custom": "you implement the embedding function yourself",
}


def ask_memory(chat_provider: str, *, accept_defaults: bool = False) -> dict[str, Any]:
    """Build the `memory` block of agent.yaml.

    Args:
        chat_provider: The chosen chat model provider. Used to pick a sensible
            embeddings provider, and to warn when the two must differ.
        accept_defaults: Skip every question (the `--yes` path).

    Returns:
        A dict suitable for ``AgentSpec(memory=...)``.
    """
    memory: dict[str, Any] = {"long_term": {"enabled": True, "backend": "sqlite"}}

    if accept_defaults:
        return memory

    console.print(
        "\n[bold]Long-term memory[/bold] is on: the agent remembers facts across "
        "conversations, stored in a local SQLite file. No services to run."
    )

    if not Confirm.ask("  Keep long-term memory enabled?", default=True):
        return {"long_term": {"enabled": False}}

    console.print("\n[bold]Where should memories be stored?[/bold]")
    for name in MEMORY_BACKENDS:
        console.print(f"  [cyan]{name:9s}[/cyan] {BACKEND_SUMMARY[name]}")
    backend = Prompt.ask("  Backend", choices=MEMORY_BACKENDS, default="sqlite")
    memory["long_term"]["backend"] = backend
    if backend == "postgres":
        console.print(
            "  [dim]Set POSTGRES_URI in .env. The schema is created on first "
            "start — no migration step of your own.[/dim]"
        )

    console.print(
        "\n[bold]Semantic search[/bold] lets the agent recall memories by meaning "
        "rather than exact key.\n"
        "  [dim]Without it, memory still works — lookups filter instead of "
        "ranking by similarity.[/dim]"
    )
    if not Confirm.ask("  Enable semantic search?", default=False):
        return memory

    memory["long_term"]["semantic_search"] = True

    console.print("\n[bold]How should embeddings be produced?[/bold]")
    for mode in EMBEDDING_MODES:
        console.print(f"  [cyan]{mode:9s}[/cyan] {MODE_SUMMARY[mode]}")
    mode = Prompt.ask("  Embeddings", choices=EMBEDDING_MODES, default="local")

    embeddings: dict[str, Any] = {"mode": mode}

    if mode == "local":
        embeddings["model"] = Prompt.ask("  Model", default=DEFAULT_LOCAL_MODEL)
    elif mode == "provider":
        suggested = EMBEDDING_PROVIDER_FOR_CHAT.get(chat_provider, "openai")
        if chat_provider == "anthropic":
            # Not a style note: there is no Anthropic embeddings API, so this
            # is a second vendor and a second key the user did not ask for.
            console.print(
                "  [yellow]![/yellow] Anthropic has no embeddings API, so this "
                "adds a second provider and API key."
            )
        provider = Prompt.ask(
            "  Embeddings provider",
            choices=sorted(DEFAULT_EMBEDDING_MODEL),
            default=suggested,
        )
        embeddings["provider"] = provider
        embeddings["model"] = Prompt.ask(
            "  Model", default=DEFAULT_EMBEDDING_MODEL[provider]
        )
    else:
        # Custom: we cannot know the vector width, and guessing it is
        # unrecoverable — a wrong value means re-embedding everything later.
        embeddings["model"] = Prompt.ask("  Name for your embedding function", default="custom")
        embeddings["dims"] = int(Prompt.ask("  Vector dimensions", default="768"))

    identifier = (
        embeddings["model"]
        if mode == "local"
        else f"{embeddings.get('provider', 'openai')}:{embeddings['model']}"
    )
    known = EMBEDDING_DIMS.get(identifier)
    if known:
        console.print(f"  [dim]{identifier} → {known} dimensions[/dim]")
    elif "dims" not in embeddings:
        embeddings["dims"] = int(
            Prompt.ask(
                f"  Dimensions for {identifier} (not in the known table)", default="768"
            )
        )

    memory["long_term"]["embeddings"] = embeddings
    return memory


def memory_from_flags(
    chat_provider: str,
    *,
    memory_enabled: bool,
    semantic_search: bool,
    embeddings_mode: str | None,
    embedding_model: str | None,
    backend: str = "sqlite",
) -> dict[str, Any]:
    """Non-interactive equivalent of :func:`ask_memory`, for flags and CI."""
    if not memory_enabled:
        return {"long_term": {"enabled": False}}

    long_term: dict[str, Any] = {"enabled": True, "backend": backend}
    if not semantic_search:
        return {"long_term": long_term}

    long_term["semantic_search"] = True
    mode = embeddings_mode or "local"
    embeddings: dict[str, Any] = {"mode": mode}

    if mode == "local":
        embeddings["model"] = embedding_model or DEFAULT_LOCAL_MODEL
    elif mode == "provider":
        provider = EMBEDDING_PROVIDER_FOR_CHAT.get(chat_provider, "openai")
        embeddings["provider"] = provider
        embeddings["model"] = embedding_model or DEFAULT_EMBEDDING_MODEL[provider]
    else:
        embeddings["model"] = embedding_model or "custom"

    long_term["embeddings"] = embeddings
    return {"long_term": long_term}
