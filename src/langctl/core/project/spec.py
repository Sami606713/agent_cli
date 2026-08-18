"""AgentSpec — the single source of truth for a project.

Persisted as ``agent.yaml``. Everything else (langgraph.json, .env.example, the
frontend proxy target, CI, Dockerfile) is derived from it. Nothing else is
authoritative: if a command needs to know something about the project, it asks
the spec.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from ..errors import SpecError


def _default_middleware() -> dict[str, Any]:
    """Cost and reliability guards every new project starts with.

    Imported lazily: the registry imports nothing from the spec, but keeping the
    call inside a function documents that the registry owns these values.
    """
    from ..catalog.middleware import default_config

    return default_config()


Runtime = Literal["python", "node"]
Mode = Literal["proxy", "embedded"]
FrontendKind = Literal["agent_chat_ui", "none"]

#: Frontend kinds that reach the Agent Server through a same-origin passthrough.
PROXY_FRONTENDS = frozenset({"agent_chat_ui"})

#: Every previous kind maps to the one UI. Projects scaffolded by earlier
#: versions keep loading; their existing web/ directory is left untouched.
LEGACY_FRONTEND_KINDS = {
    "nextjs_proxy": "agent_chat_ui",
    "vite_proxy": "agent_chat_ui",
    "nextjs_minimal": "agent_chat_ui",
    "nextjs_assistant_ui": "agent_chat_ui",
    "nextjs_ai_elements": "agent_chat_ui",
    "nextjs_embedded": "agent_chat_ui",
}

#: Agent Server paths the dev proxy must forward. Verified against the Agent Server
#: surface and langchain-ai/deployment-cookbook's vite-langgraph-proxy.ts.
AGENT_SERVER_PATHS = (
    "threads",
    "runs",
    "assistants",
    "store",
    "sandbox",
    "download",
    "ok",
    "info",
    "docs",
)


class ModelSpec(BaseModel):
    """Which chat model the agent uses.

    `provider` is an open string rather than a fixed set: `init_chat_model`
    supports 27 providers and gains more, and pinning a Literal here would mean
    a new LangChain integration could not be used until langctl shipped.
    Unknown providers are allowed as long as `package` says what supplies them.
    """

    provider: str = "anthropic"
    name: str = "claude-opus-5"
    #: OpenAI-compatible endpoint — LM Studio, vLLM, a LiteLLM proxy, or any
    #: gateway. When set, the model is constructed rather than passed as a
    #: "provider:model" string, because a string carries no endpoint.
    base_url: str | None = None
    #: Override the credential variable, for a gateway with its own key.
    api_key_env_override: str | None = None
    #: Required for a provider langctl does not know; ignored otherwise.
    package: str | None = None
    #: Extra keyword arguments passed to init_chat_model (temperature, etc).
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider")
    @classmethod
    def _normalise_provider(cls, v: str) -> str:
        from ..catalog.models import normalise

        if not v or not v.strip():
            raise ValueError("model.provider must not be empty")
        return normalise(v)

    @model_validator(mode="after")
    def _known_or_declared(self) -> ModelSpec:
        from ..catalog.models import PROVIDERS, get, is_known, suggest

        # Choosing a provider without naming a model should not silently keep
        # the previous provider's default (e.g. openai + claude-opus-5).
        if "name" not in self.model_fields_set:
            known = get(self.provider)
            if known and known.default_model:
                self.name = known.default_model
            elif known is None or known.model_from_env:
                # No safe default exists, so record nothing rather than a name
                # this provider probably does not serve. MODEL_NAME supplies it.
                self.name = ""

        if is_known(self.provider) or self.package:
            return self
        hint = suggest(self.provider)
        raise ValueError(
            f"unknown model provider {self.provider!r}. Either use one of the "
            f"{len(PROVIDERS)} known providers"
            + (f" (did you mean {' or '.join(hint)}?)" if hint else "")
            + ", or set model.package so the dependency can be installed."
        )

    @property
    def identifier(self) -> str:
        """The ``provider:model`` string ``create_agent`` accepts."""
        return f"{self.provider}:{self.name}"

    @property
    def needs_construction(self) -> bool:
        """True when a plain identifier string cannot express this model."""
        return bool(self.base_url or self.options)

    @property
    def api_key_env(self) -> str | None:
        """Credential variable, or None when the provider needs no key."""
        if self.api_key_env_override:
            return self.api_key_env_override
        from ..catalog.models import get

        known = get(self.provider)
        return known.api_key_env if known else None

    @property
    def model_from_env(self) -> bool:
        """True when the model name must be read from MODEL_NAME at runtime.

        Local runtimes, gateways and unknown providers serve whatever that
        machine or proxy has — baking a name in would fail on the first message
        against a server langctl never saw. A custom base_url is the same
        situation for the same reason.
        """
        from ..catalog.models import get

        known = get(self.provider)
        if known is None:
            return True  # unknown provider: we cannot know what it serves
        return known.model_from_env or bool(self.base_url)

    @property
    def package_requirement(self) -> str | None:
        if self.package:
            return self.package
        from ..catalog.models import get

        known = get(self.provider)
        return known.package if known else None


MemoryBackend = Literal["sqlite", "postgres", "memory"]

#: Output dimensions per embedding model. A mismatch is unrecoverable — there is
#: no re-embedding tooling — so dims is derived rather than left to the user.
#: Values come from provider documentation, not from a live call.
EMBEDDING_DIMS: dict[str, int] = {
    "openai:text-embedding-3-small": 1536,
    "openai:text-embedding-3-large": 3072,
    "openai:text-embedding-ada-002": 1536,
    "cohere:embed-english-v3.0": 1024,
    "cohere:embed-multilingual-v3.0": 1024,
    "mistralai:mistral-embed": 1024,
    "google_vertexai:text-embedding-004": 768,
    "ollama:nomic-embed-text": 768,
    "nomic-ai/nomic-embed-text-v1.5": 768,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
}

#: Chat provider → sensible embeddings provider. Anthropic ships no embeddings
#: API at all, so choosing it means taking on a second vendor.
EMBEDDING_PROVIDER_FOR_CHAT: dict[str, str] = {
    "openai": "openai",
    "google": "google_vertexai",
    "bedrock": "bedrock",
    "ollama": "ollama",
    "anthropic": "openai",
}


class EmbeddingsSpec(BaseModel):
    """How vectors are produced when semantic search is on.

    Three modes because the trade-offs genuinely differ: a hosted API (key and
    per-item cost), a local model (no key, but pulls torch), or your own
    function (no assumptions).
    """

    mode: Literal["provider", "local", "custom"] = "provider"
    provider: str = "openai"
    model: str = "text-embedding-3-small"
    dims: int | None = None
    #: JSON fields to embed; "$" means the whole document.
    fields: list[str] = Field(default_factory=lambda: ["$"])

    @property
    def identifier(self) -> str:
        return self.model if self.mode == "local" else f"{self.provider}:{self.model}"

    @property
    def api_key_env(self) -> str | None:
        """Env var this embedding provider needs, if any."""
        if self.mode != "provider":
            return None  # local models and custom functions need no key
        return {
            "openai": "OPENAI_API_KEY",
            "cohere": "COHERE_API_KEY",
            "mistralai": "MISTRAL_API_KEY",
            "google_vertexai": "GOOGLE_APPLICATION_CREDENTIALS",
        }.get(self.provider)

    @model_validator(mode="after")
    def _resolve_dims(self) -> EmbeddingsSpec:
        if self.dims is None:
            resolved = EMBEDDING_DIMS.get(self.identifier)
            if resolved is None:
                raise ValueError(
                    f"dims is required for embedding model {self.identifier!r}: it is not "
                    "in the known-dimensions table. A wrong value cannot be corrected "
                    "later without re-embedding every stored item."
                )
            self.dims = resolved
        return self


class ShortTermMemorySpec(BaseModel):
    """Thread state — the messages inside one conversation.

    Defaults to ``server``: let the Agent Server manage checkpoints. Unlike the
    store, overriding this *loses* capability — the server warns that a custom
    checkpointer without ``adelete_for_runs`` cannot clean up checkpoints from
    cancelled runs, so ``multitask_strategy="rollback"`` leaves stale state.
    Choose sqlite/postgres only when thread history must outlive the process.
    """

    backend: Literal["server", "sqlite", "postgres", "memory"] = "server"
    path: str = "data/checkpoints.sqlite"

    @property
    def is_managed(self) -> bool:
        return self.backend in ("server", "memory")


class LongTermMemorySpec(BaseModel):
    """Facts that outlive any single thread.

    On by default. Verified against a real restart: with no explicit store,
    `langgraph dev` keeps long-term memory in process and loses all of it.
    """

    enabled: bool = True
    backend: MemoryBackend = "sqlite"
    path: str = "data/memory.sqlite"
    semantic_search: bool = False
    embeddings: EmbeddingsSpec = Field(default_factory=EmbeddingsSpec)


class MemorySpec(BaseModel):
    short_term: ShortTermMemorySpec = Field(default_factory=ShortTermMemorySpec)
    long_term: LongTermMemorySpec = Field(default_factory=LongTermMemorySpec)

    @model_validator(mode="before")
    @classmethod
    def _migrate_flat_shape(cls, data: object) -> object:
        """Accept the 0.2.0 layout so existing projects keep loading.

        old: {checkpointer, store, semantic_search}
        new: {short_term: {...}, long_term: {...}}
        """
        if not isinstance(data, dict) or "short_term" in data or "long_term" in data:
            return data
        if not ({"checkpointer", "store", "semantic_search"} & set(data)):
            return data

        legacy_checkpointer = data.get("checkpointer", "sqlite")
        legacy_store = data.get("store", "sqlite")
        return {
            "short_term": {
                # 0.2.0 never emitted checkpointer.path, so those projects were
                # always server-managed. Preserve that rather than silently
                # switching them onto a custom checkpointer.
                "backend": "memory" if legacy_checkpointer == "memory" else "server"
            },
            "long_term": {
                "enabled": legacy_store != "none",
                "backend": "memory" if legacy_store == "memory" else "sqlite",
                "semantic_search": bool(data.get("semantic_search", False)),
            },
        }


class MiddlewareSpec(BaseModel):
    """Which middleware are on, and how each is configured.

    Free-form by design: keys are registry names, values are that middleware's
    settings. Validating them here would duplicate the registry, so the registry
    stays the single source of truth and unknown keys are reported by `sync`.
    """

    model_config = {"extra": "allow"}

    #: Names of custom AgentMiddleware classes in middleware/custom.py.
    custom: list[str] = Field(default_factory=list)

    def enabled_keys(self) -> list[str]:
        """Built-in middleware switched on, in agent.yaml order."""
        keys = []
        for key, value in self.model_dump().items():
            if key == "custom":
                continue
            if isinstance(value, dict) and value.get("enabled"):
                keys.append(key)
        return keys

    def settings(self, key: str) -> dict[str, Any]:
        value = getattr(self, key, None)
        if not isinstance(value, dict):
            return {}
        return {k: v for k, v in value.items() if k != "enabled"}


class FrontendSpec(BaseModel):
    enabled: bool = True
    kind: FrontendKind = "agent_chat_ui"
    proxy_prefix: str = "/api/agent"
    generative_ui: bool = False

    @field_validator("kind", mode="before")
    @classmethod
    def _migrate_kind(cls, v: object) -> object:
        # Accept the pre-rename names rather than failing on a project scaffolded
        # by an earlier version.
        return LEGACY_FRONTEND_KINDS.get(v, v) if isinstance(v, str) else v

    @field_validator("proxy_prefix")
    @classmethod
    def _prefix_shape(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("proxy_prefix must start with '/'")
        return v.rstrip("/")


class PortsSpec(BaseModel):
    """Where this project's two local servers listen.

    Configurable because the defaults collide with whatever else the machine is
    already running — 3000 is every other Next.js app, 2024 is any other Agent
    Server — and the alternative was editing generated source. Keys are named
    for the roles `langctl dev` prints, `frontend` and `agent`, not for the spec
    sections they used to live under.
    """

    frontend: int = Field(default=3000, ge=1, le=65535)
    agent: int = Field(default=2024, ge=1, le=65535)


class ObservabilitySpec(BaseModel):
    langsmith: bool = True
    project: str | None = None


class DeployTarget(BaseModel):
    provider: str | None = None
    deployment_type: Literal["serverless", "dedicated", "dev", "prod"] = "serverless"


class DeploySpec(BaseModel):
    #: Where `langctl deploy` sends this project. None means it has never been
    #: asked; the first deploy picks one and records it here, so the question is
    #: asked once rather than every time.
    target: str | None = None
    backend: DeployTarget = Field(default_factory=DeployTarget)
    frontend: DeployTarget = Field(default_factory=DeployTarget)


class AgentSpec(BaseModel):
    version: Literal[1] = 1
    name: str
    runtime: Runtime = "python"
    template: str = "react_agent"
    mode: Mode = "proxy"
    model: ModelSpec = Field(default_factory=ModelSpec)
    memory: MemorySpec = Field(default_factory=MemorySpec)
    middleware: MiddlewareSpec = Field(
        default_factory=lambda: MiddlewareSpec(**_default_middleware())
    )
    frontend: FrontendSpec = Field(default_factory=FrontendSpec)
    ports: PortsSpec = Field(default_factory=PortsSpec)
    observability: ObservabilitySpec = Field(default_factory=ObservabilitySpec)
    deploy: DeploySpec = Field(default_factory=DeploySpec)
    environments: list[str] = Field(default_factory=lambda: ["dev", "prod"])

    @model_validator(mode="before")
    @classmethod
    def _migrate_ports(cls, data: object) -> object:
        """Accept the layout used before `ports` existed, ports living apart.

        old: {frontend: {port: 3001}, backend: {port: 2025}}
        new: {ports: {frontend: 3001, agent: 2025}}

        A project scaffolded by an earlier version keeps running untouched. An
        explicit `ports` wins per key, so a file carrying both — one hand-edited,
        one left over — resolves the way the user last wrote it rather than by
        section order.
        """
        if not isinstance(data, dict):
            return data

        legacy: dict[str, Any] = {}
        for section, key in (("frontend", "frontend"), ("backend", "agent")):
            value = data.get(section)
            if isinstance(value, dict) and value.get("port") is not None:
                legacy[key] = value["port"]
        if not legacy:
            return data

        ports = data.get("ports")
        ports = dict(ports) if isinstance(ports, dict) else {}
        data = dict(data)
        data["ports"] = {**legacy, **ports}
        return data

    @field_validator("name")
    @classmethod
    def _name_shape(cls, v: str) -> str:
        # Deployment names become DNS labels and container names downstream, so
        # constrain here rather than failing at deploy time.
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,61}[a-z0-9]", v):
            raise ValueError(
                "name must be lowercase alphanumeric with hyphens, 2-63 chars, "
                "and must not start or end with a hyphen"
            )
        return v

    @model_validator(mode="after")
    def _coherent(self) -> AgentSpec:
        # A Python agent cannot live inside Next.js route handlers. Catching this
        # here is what stops the wizard from producing a project that can never run.
        if self.mode == "embedded" and self.runtime != "node":
            raise ValueError(
                "mode 'embedded' requires runtime 'node' — a Python agent cannot run "
                "inside Next.js route handlers. Use mode 'proxy'."
            )
        if self.frontend.enabled and self.frontend.kind == "none":
            raise ValueError("frontend.enabled is true but frontend.kind is 'none'")
        if self.frontend.enabled and self.ports.frontend == self.ports.agent:
            raise ValueError(
                f"ports.frontend and ports.agent are both {self.ports.frontend}; they must differ"
            )
        return self

    # ---- derived values -------------------------------------------------

    @property
    def package_name(self) -> str:
        """Importable Python package name derived from the project name."""
        return self.name.replace("-", "_")

    @property
    def display_name(self) -> str:
        """The project's name as a person would write it.

        ``research-assistant`` becomes ``Research Assistant``. Used for the
        browser tab and the chat UI's heading, so the app a user built is
        named after their project rather than after the framework.
        """
        return " ".join(word.capitalize() for word in self.name.split("-") if word)

    @property
    def initials(self) -> str:
        """One or two letters for the app's mark.

        Two words give their initials (``research-assistant`` → ``RA``); a
        single word gives its first two letters (``scout`` → ``SC``), because
        one letter alone reads as an accident rather than a logo.
        """
        words = [word for word in self.name.split("-") if word]
        if len(words) >= 2:
            return (words[0][0] + words[1][0]).upper()
        return words[0][:2].upper() if words else "AG"

    @property
    def brand_hue(self) -> int:
        """A stable colour for the mark, derived from the name.

        Deterministic so the icon never changes between renders, and spread
        across the wheel so two projects rarely collide. Hue only — saturation
        and lightness are fixed in the template, which keeps every generated
        mark legible on both light and dark backgrounds.
        """
        return sum(ord(char) * (index + 1) for index, char in enumerate(self.name)) % 360

    @property
    def graph_id(self) -> str:
        return "agent"

    @property
    def uses_agent_server(self) -> bool:
        """True when a separate Agent Server process exists (mode 'proxy')."""
        return self.mode == "proxy"

    def local_backend_url(self, port: int | None = None) -> str:
        return f"http://127.0.0.1:{port or self.ports.agent}"

    # ---- langgraph.json -------------------------------------------------

    def to_langgraph_config(self) -> dict[str, Any]:
        """Build the langgraph.json fields we own.

        Only the keys listed in :meth:`owned_keys` are emitted; ``sync`` merges
        this over any existing file so hand-written keys survive.
        """
        cfg: dict[str, Any] = {}
        if self.runtime == "python":
            cfg["dependencies"] = ["."]
            cfg["python_version"] = "3.11"
            cfg["graphs"] = {self.graph_id: f"./src/{self.package_name}/agent.py:graph"}
        else:
            cfg["node_version"] = "20"
            cfg["graphs"] = {self.graph_id: "./src/agent/index.ts:graph"}
        cfg["env"] = ".env"

        # Long-term memory is wired through `store.path`, not `store.index`.
        #
        # Verified against a real restart: with no `store` key, `langgraph dev`
        # holds the store in process and loses every memory when it exits.
        # Pointing `path` at our own context manager is what makes it durable.
        # It also *replaces* the deployed server's managed Postgres store, so we
        # only emit it when the project actually owns its store.
        if self.memory.long_term.enabled and self.memory.long_term.backend != "memory":
            cfg["store"] = {"path": f"./src/{self.package_name}/memory/store.py:generate_store"}

        # Short-term is the opposite trade-off: the server manages threads well,
        # and a custom checkpointer loses adelete_for_runs. Only override when
        # the project explicitly asked for durable local thread history.
        if not self.memory.short_term.is_managed:
            cfg["checkpointer"] = {
                "path": f"./src/{self.package_name}/memory/checkpointer.py:generate_checkpointer"
            }

        if self.frontend.generative_ui and self.runtime == "node":
            cfg["ui"] = {self.graph_id: "./src/agent/ui.tsx"}

        # The browser reaches the Agent Server through a same-origin proxy, so CORS
        # is not needed for our own frontend. It IS needed for Studio, which runs on
        # smith.langchain.com and talks to the server directly.
        cfg["http"] = {
            "cors": {
                "allow_origins": ["https://smith.langchain.com"],
                "allow_credentials": True,
            }
        }
        return cfg

    @staticmethod
    def owned_keys() -> set[str]:
        """Keys `langctl sync` may rewrite. Everything else is the user's."""
        return {
            "dependencies",
            "python_version",
            "node_version",
            "graphs",
            "env",
            "store",
            "checkpointer",
            "ui",
            "http",
        }

    # ---- persistence ----------------------------------------------------

    def to_yaml(self) -> str:
        data = self.model_dump(mode="json", exclude_defaults=False)
        return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)

    @classmethod
    def from_yaml(cls, text: str) -> AgentSpec:
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise SpecError(f"agent.yaml is not valid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise SpecError("agent.yaml must contain a mapping at the top level")
        try:
            return cls.model_validate(data)
        except Exception as exc:
            raise SpecError(f"agent.yaml is invalid:\n{exc}") from exc

    @classmethod
    def load(cls, path: Path) -> AgentSpec:
        return cls.from_yaml(path.read_text(encoding="utf-8"))

    def save(self, path: Path) -> None:
        path.write_text(self.to_yaml(), encoding="utf-8")
