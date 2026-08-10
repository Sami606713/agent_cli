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

from .errors import SpecError

Runtime = Literal["python", "node"]
Mode = Literal["proxy", "embedded"]
FrontendKind = Literal["nextjs_proxy", "vite_proxy", "nextjs_embedded", "none"]

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
    provider: Literal["anthropic", "openai", "google", "bedrock", "ollama"] = "anthropic"
    name: str = "claude-opus-5"

    @property
    def identifier(self) -> str:
        """The ``provider:model`` string ``create_agent`` accepts."""
        return f"{self.provider}:{self.name}"

    @property
    def api_key_env(self) -> str:
        return {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GOOGLE_API_KEY",
            "bedrock": "AWS_ACCESS_KEY_ID",
            "ollama": "OLLAMA_HOST",
        }[self.provider]


class MemorySpec(BaseModel):
    checkpointer: Literal["memory", "postgres", "sqlite", "redis"] = "postgres"
    store: Literal["none", "memory", "postgres"] = "postgres"
    semantic_search: bool = False


class FrontendSpec(BaseModel):
    enabled: bool = True
    kind: FrontendKind = "nextjs_proxy"
    port: int = 3000
    proxy_prefix: str = "/api/agent"
    generative_ui: bool = False

    @field_validator("proxy_prefix")
    @classmethod
    def _prefix_shape(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("proxy_prefix must start with '/'")
        return v.rstrip("/")


class BackendSpec(BaseModel):
    port: int = 2024


class ObservabilitySpec(BaseModel):
    langsmith: bool = True
    project: str | None = None


class DeployTarget(BaseModel):
    provider: str | None = None
    deployment_type: Literal["serverless", "dedicated", "dev", "prod"] = "serverless"


class DeploySpec(BaseModel):
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
    frontend: FrontendSpec = Field(default_factory=FrontendSpec)
    backend: BackendSpec = Field(default_factory=BackendSpec)
    observability: ObservabilitySpec = Field(default_factory=ObservabilitySpec)
    deploy: DeploySpec = Field(default_factory=DeploySpec)
    environments: list[str] = Field(default_factory=lambda: ["dev", "prod"])

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
        if self.mode == "embedded" and self.frontend.kind != "nextjs_embedded":
            raise ValueError("mode 'embedded' requires frontend.kind 'nextjs_embedded'")
        if self.mode == "proxy" and self.frontend.kind == "nextjs_embedded":
            raise ValueError("frontend.kind 'nextjs_embedded' requires mode 'embedded'")
        if self.frontend.enabled and self.frontend.kind == "none":
            raise ValueError("frontend.enabled is true but frontend.kind is 'none'")
        if self.frontend.enabled and self.frontend.port == self.backend.port:
            raise ValueError(
                f"frontend.port and backend.port are both {self.frontend.port}; "
                "they must differ"
            )
        return self

    # ---- derived values -------------------------------------------------

    @property
    def package_name(self) -> str:
        """Importable Python package name derived from the project name."""
        return self.name.replace("-", "_")

    @property
    def graph_id(self) -> str:
        return "agent"

    @property
    def uses_agent_server(self) -> bool:
        """True when a separate Agent Server process exists (mode 'proxy')."""
        return self.mode == "proxy"

    def local_backend_url(self, port: int | None = None) -> str:
        return f"http://127.0.0.1:{port or self.backend.port}"

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

        if self.memory.store != "none" and self.memory.semantic_search:
            cfg["store"] = {
                "index": {
                    "embed": "openai:text-embedding-3-small",
                    "dims": 1536,
                    "fields": ["$"],
                }
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
