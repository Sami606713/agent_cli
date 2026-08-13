"""Memory configuration and its fan-out into the generated project.

The behavioural claim these guard was established by running the real server:
with no `store` key, `langgraph dev` keeps long-term memory in process and
loses every item on restart. `store.path` is what makes it durable.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from langctl.core.generate.deps import required_env_vars, runtime_packages
from langctl.core.generate.scaffold import scaffold
from langctl.core.project.spec import AgentSpec


def spec(**memory) -> AgentSpec:
    return AgentSpec(name="demo-agent", memory=memory) if memory else AgentSpec(name="demo-agent")


class TestDefaults:
    def test_long_term_memory_is_on_by_default(self):
        assert spec().memory.long_term.enabled is True
        assert spec().memory.long_term.backend == "sqlite"

    def test_short_term_is_server_managed_by_default(self):
        # Overriding the checkpointer loses adelete_for_runs; overriding the
        # store gains persistence. Hence the asymmetric defaults.
        assert spec().memory.short_term.backend == "server"
        assert spec().memory.short_term.is_managed

    def test_semantic_search_is_off_by_default(self):
        assert spec().memory.long_term.semantic_search is False


class TestLanggraphConfig:
    def test_store_path_emitted_for_durable_backends(self):
        cfg = AgentSpec(name="support-agent").to_langgraph_config()
        assert cfg["store"] == {"path": "./src/support_agent/memory/store.py:generate_store"}

    def test_no_store_path_for_in_memory_backend(self):
        assert "store" not in spec(long_term={"backend": "memory"}).to_langgraph_config()

    def test_no_checkpointer_key_when_server_managed(self):
        assert "checkpointer" not in spec().to_langgraph_config()

    def test_checkpointer_path_emitted_when_project_owns_it(self):
        cfg = spec(short_term={"backend": "sqlite"}).to_langgraph_config()
        assert cfg["checkpointer"]["path"].endswith("checkpointer.py:generate_checkpointer")

    def test_emitted_keys_stay_owned(self):
        cfg = spec(short_term={"backend": "sqlite"}).to_langgraph_config()
        assert set(cfg) <= AgentSpec.owned_keys()


class TestEmbeddings:
    def test_dims_are_derived_from_the_model(self):
        s = spec(long_term={"semantic_search": True,
                            "embeddings": {"model": "text-embedding-3-large"}})
        assert s.memory.long_term.embeddings.dims == 3072

    def test_local_model_dims_are_known(self):
        s = spec(long_term={"embeddings": {"mode": "local",
                                           "model": "nomic-ai/nomic-embed-text-v1.5"}})
        assert s.memory.long_term.embeddings.dims == 768

    def test_unknown_model_requires_explicit_dims(self):
        # Guessing here is unrecoverable: a wrong width cannot be fixed without
        # re-embedding every stored item.
        with pytest.raises(ValidationError, match="dims is required"):
            AgentSpec(name="demo-agent",
                      memory={"long_term": {"embeddings": {"model": "mystery-model"}}})

    def test_explicit_dims_accepted_for_unknown_model(self):
        s = spec(long_term={"embeddings": {"mode": "custom", "model": "mine", "dims": 42}})
        assert s.memory.long_term.embeddings.dims == 42

    def test_local_and_custom_modes_need_no_api_key(self):
        for mode, model in (("local", "nomic-ai/nomic-embed-text-v1.5"),
                            ("custom", "x")):
            s = spec(long_term={"embeddings": {"mode": mode, "model": model, "dims": 8}})
            assert s.memory.long_term.embeddings.api_key_env is None


class TestDependencyFanOut:
    """A feature without its package is a boot failure `langgraph validate`
    reports as valid — proven in plan 09."""

    def test_sqlite_backend_adds_its_package(self):
        assert any("checkpoint-sqlite" in p for p in runtime_packages(spec()))

    def test_local_embeddings_add_sentence_transformers(self):
        s = spec(long_term={"semantic_search": True,
                            "embeddings": {"mode": "local",
                                           "model": "nomic-ai/nomic-embed-text-v1.5"}})
        assert any("sentence-transformers" in p for p in runtime_packages(s))

    def test_provider_embeddings_add_the_provider_package_and_key(self):
        s = spec(long_term={"semantic_search": True})
        assert any("langchain-openai" in p for p in runtime_packages(s))
        assert "OPENAI_API_KEY" in required_env_vars(s)

    def test_postgres_requires_a_uri(self):
        s = spec(long_term={"backend": "postgres"})
        assert "POSTGRES_URI" in required_env_vars(s)

    def test_no_duplicate_packages(self):
        s = AgentSpec(name="demo-agent", model={"provider": "openai"},
                      memory={"long_term": {"semantic_search": True}})
        packages = runtime_packages(s)
        assert len(packages) == len(set(packages))


class TestScaffold:
    def test_memory_package_is_generated(self, tmp_path):
        scaffold(AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"}),
                 tmp_path)
        for rel in ("src/demo_agent/memory/__init__.py",
                    "src/demo_agent/memory/store.py",
                    "src/demo_agent/memory/checkpointer.py",
                    "src/demo_agent/tools/__init__.py",
                    "src/demo_agent/tools/memory.py",
                    "src/demo_agent/prompts/system.py"):
            assert (tmp_path / rel).is_file(), f"missing {rel}"

    def test_memory_tools_registered_only_when_enabled(self, tmp_path):
        off = tmp_path / "off"
        scaffold(AgentSpec(name="demo-agent",
                           frontend={"enabled": False, "kind": "none"},
                           memory={"long_term": {"enabled": False}}), off)
        registry = (off / "src/demo_agent/tools/__init__.py").read_text()
        assert "save_memory" not in registry

    def test_data_directory_is_gitignored(self, tmp_path):
        scaffold(AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"}),
                 tmp_path)
        # These files hold real conversation content.
        assert "data/" in (tmp_path / ".gitignore").read_text()

    def test_generated_deps_match_the_spec(self, tmp_path):
        s = AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"})
        scaffold(s, tmp_path)
        pyproject = (tmp_path / "pyproject.toml").read_text()
        for package in runtime_packages(s):
            assert package in pyproject


class TestLegacyMigration:
    def test_020_layout_still_loads(self):
        s = AgentSpec.from_yaml(
            "name: demo-agent\n"
            "memory:\n  checkpointer: postgres\n  store: postgres\n  semantic_search: true\n"
        )
        assert s.memory.long_term.enabled is True
        assert s.memory.long_term.semantic_search is True

    def test_legacy_projects_stay_server_managed(self):
        # 0.2.0 never emitted checkpointer.path; migrating them onto a custom
        # checkpointer would change runtime behaviour silently.
        s = AgentSpec.from_yaml("name: demo-agent\nmemory:\n  checkpointer: postgres\n")
        assert s.memory.short_term.backend == "server"
        assert "checkpointer" not in s.to_langgraph_config()

    def test_store_none_disables_long_term(self):
        s = AgentSpec.from_yaml("name: demo-agent\nmemory:\n  store: none\n")
        assert s.memory.long_term.enabled is False


class TestPostgresBackend:
    """Verified against a real Postgres 16 container, not just rendered."""

    def build(self, tmp_path):
        spec = AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"},
                         memory={"long_term": {"backend": "postgres"}})
        scaffold(spec, tmp_path)
        return spec

    def test_postgres_package_and_uri_required(self, tmp_path):
        spec = self.build(tmp_path)
        assert any("checkpoint-postgres" in p for p in runtime_packages(spec))
        assert "POSTGRES_URI" in required_env_vars(spec)

    def test_store_path_still_emitted(self, tmp_path):
        spec = self.build(tmp_path)
        # Same wiring as sqlite: the server opens our context manager.
        assert spec.to_langgraph_config()["store"]["path"].endswith("store.py:generate_store")

    def test_generated_store_strips_sqlalchemy_prefix(self, tmp_path):
        # psycopg3 rejects `postgresql+psycopg://`; a URI copied from a
        # SQLAlchemy config would otherwise fail with an opaque parse error.
        self.build(tmp_path)
        source = (tmp_path / "src/demo_agent/memory/store.py").read_text()
        assert "postgresql+asyncpg://" in source
        assert "_clean_uri" in source

    def test_generated_store_has_both_sync_and_async(self, tmp_path):
        self.build(tmp_path)
        source = (tmp_path / "src/demo_agent/memory/store.py").read_text()
        assert "AsyncPostgresStore" in source
        assert "PostgresStore" in source

    def test_sqlite_remains_the_default(self):
        assert AgentSpec(name="demo-agent").memory.long_term.backend == "sqlite"
