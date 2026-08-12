"""Memory questions at creation time, and keeping deps in step afterwards."""

from __future__ import annotations

import pytest

from langctl.core.deps import required_env_vars
from langctl.core.memory_wizard import memory_from_flags
from langctl.core.pyproject import (
    current_dependencies,
    dependency_drift,
    render_dependencies,
    sync_dependencies,
)
from langctl.core.scaffold import scaffold
from langctl.core.spec import AgentSpec


class TestFlags:
    def test_default_is_memory_on_search_off(self):
        cfg = memory_from_flags("anthropic", memory_enabled=True, semantic_search=False,
                                embeddings_mode=None, embedding_model=None)
        assert cfg["long_term"]["enabled"] is True
        assert "semantic_search" not in cfg["long_term"]

    def test_no_memory_disables_it(self):
        cfg = memory_from_flags("anthropic", memory_enabled=False, semantic_search=False,
                                embeddings_mode=None, embedding_model=None)
        assert cfg["long_term"]["enabled"] is False

    def test_local_mode_needs_no_key(self):
        cfg = memory_from_flags("anthropic", memory_enabled=True, semantic_search=True,
                                embeddings_mode="local", embedding_model=None)
        spec = AgentSpec(name="demo-agent", memory=cfg)
        assert spec.memory.long_term.embeddings.api_key_env is None
        assert spec.memory.long_term.embeddings.dims == 768

    def test_provider_mode_follows_the_chat_provider(self):
        cfg = memory_from_flags("openai", memory_enabled=True, semantic_search=True,
                                embeddings_mode="provider", embedding_model=None)
        assert cfg["long_term"]["embeddings"]["provider"] == "openai"

    def test_anthropic_falls_back_to_a_second_vendor(self):
        # Anthropic ships no embeddings API, so semantic search necessarily
        # means another provider and another key.
        cfg = memory_from_flags("anthropic", memory_enabled=True, semantic_search=True,
                                embeddings_mode="provider", embedding_model=None)
        assert cfg["long_term"]["embeddings"]["provider"] == "openai"

    @pytest.mark.parametrize("chat", ["openai", "google", "ollama", "anthropic"])
    def test_every_chat_provider_yields_a_valid_spec(self, chat):
        cfg = memory_from_flags(chat, memory_enabled=True, semantic_search=True,
                                embeddings_mode="provider", embedding_model=None)
        spec = AgentSpec(name="demo-agent", memory=cfg)
        assert spec.memory.long_term.embeddings.dims


class TestBackendChoice:
    def test_sqlite_is_the_default(self):
        cfg = memory_from_flags("anthropic", memory_enabled=True, semantic_search=False,
                                embeddings_mode=None, embedding_model=None)
        assert cfg["long_term"]["backend"] == "sqlite"

    def test_postgres_can_be_selected(self):
        cfg = memory_from_flags("anthropic", memory_enabled=True, semantic_search=False,
                                embeddings_mode=None, embedding_model=None,
                                backend="postgres")
        spec = AgentSpec(name="demo-agent", memory=cfg)
        assert spec.memory.long_term.backend == "postgres"
        assert "POSTGRES_URI" in required_env_vars(spec)


class TestPyprojectSync:
    """Config alone is not enough: a feature whose package is missing passes
    `langgraph validate` and then kills the server on import."""

    def build(self, tmp_path, **memory):
        spec = AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"},
                         memory=memory or {})
        scaffold(spec, tmp_path)
        return spec, tmp_path / "pyproject.toml"

    def test_generated_file_is_parseable(self, tmp_path):
        _, path = self.build(tmp_path)
        assert "langchain>=1.0" in (current_dependencies(path.read_text()) or [])

    def test_enabling_search_later_is_detected_as_drift(self, tmp_path):
        _, path = self.build(tmp_path)
        upgraded = AgentSpec(
            name="demo-agent", frontend={"enabled": False, "kind": "none"},
            memory={"long_term": {"semantic_search": True,
                                  "embeddings": {"mode": "local",
                                                 "model": "nomic-ai/nomic-embed-text-v1.5"}}},
        )
        missing, _ = dependency_drift(upgraded, path.read_text())
        assert any("sentence-transformers" in p for p in missing)

    def test_sync_adds_the_missing_package(self, tmp_path):
        _, path = self.build(tmp_path)
        upgraded = AgentSpec(
            name="demo-agent", frontend={"enabled": False, "kind": "none"},
            memory={"long_term": {"semantic_search": True,
                                  "embeddings": {"mode": "local",
                                                 "model": "nomic-ai/nomic-embed-text-v1.5"}}},
        )
        assert sync_dependencies(upgraded, path) is True
        assert "sentence-transformers" in path.read_text()

    def test_sync_is_idempotent(self, tmp_path):
        spec, path = self.build(tmp_path)
        assert sync_dependencies(spec, path) is False

    def test_hand_added_packages_survive(self, tmp_path):
        spec, path = self.build(tmp_path)
        text = path.read_text().replace(
            'dependencies = [\n', 'dependencies = [\n    "httpx>=0.27",\n', 1
        )
        path.write_text(text)
        # A package we do not manage must not be reported as removable…
        _, extra = dependency_drift(spec, path.read_text())
        assert not any("httpx" in p for p in extra)

    def test_the_rest_of_the_file_is_untouched(self, tmp_path):
        spec, path = self.build(tmp_path)
        before = path.read_text()
        upgraded = AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"},
                             memory={"long_term": {"backend": "postgres"}})
        sync_dependencies(upgraded, path)
        after = path.read_text()
        for section in ("[build-system]", "[tool.ruff]", "[project.optional-dependencies]"):
            assert section in after
        assert before.split("[build-system]")[1] == after.split("[build-system]")[1]

    def test_render_is_deterministic(self, tmp_path):
        spec, _ = self.build(tmp_path)
        assert render_dependencies(spec) == render_dependencies(spec)
