import json
import re

import pytest
from pydantic import ValidationError

from langctl.core.errors import SpecError
from langctl.core.project.spec import AgentSpec


def spec(**kw) -> AgentSpec:
    return AgentSpec(name=kw.pop("name", "my-agent"), **kw)


class TestNaming:
    @pytest.mark.parametrize("name", ["a-b", "agent1", "x" * 63])
    def test_accepts_dns_safe_names(self, name):
        assert AgentSpec(name=name).name == name

    @pytest.mark.parametrize("name", ["-lead", "trail-", "Upper", "under_score", "a", "x" * 64])
    def test_rejects_unsafe_names(self, name):
        with pytest.raises(ValidationError):
            AgentSpec(name=name)

    def test_package_name_is_importable(self):
        assert spec(name="support-agent").package_name == "support_agent"


class TestModeCoherence:
    """The wizard must never be able to emit a project that cannot run."""

    def test_python_cannot_be_embedded(self):
        with pytest.raises(ValidationError, match="embedded"):
            AgentSpec(name="x-y", runtime="python", mode="embedded")

    def test_node_embedded_is_valid(self):
        s = AgentSpec(name="x-y", runtime="node", mode="embedded")
        assert s.uses_agent_server is False

    def test_proxy_mode_uses_agent_server(self):
        assert spec().uses_agent_server is True


class TestPorts:
    """Both ports are the user's to choose: 3000 and 2024 are already taken on
    plenty of machines, and the answer must not be "edit the source"."""

    def test_defaults(self):
        s = spec()
        assert (s.ports.frontend, s.ports.agent) == (3000, 2024)

    def test_configured_ports_are_kept(self):
        s = spec(ports={"frontend": 3001, "agent": 2025})
        assert (s.ports.frontend, s.ports.agent) == (3001, 2025)

    def test_one_port_can_move_alone(self):
        assert spec(ports={"agent": 2025}).ports.frontend == 3000

    def test_agent_url_follows_the_configured_port(self):
        assert spec(ports={"agent": 2025}).local_backend_url() == "http://127.0.0.1:2025"

    def test_collision_rejected(self):
        with pytest.raises(ValidationError, match="must differ"):
            AgentSpec(name="x-y", ports={"frontend": 3000, "agent": 3000})

    def test_collision_allowed_without_a_frontend(self):
        # Nothing binds the frontend port, so there is nothing to collide with.
        s = AgentSpec(
            name="x-y",
            frontend={"enabled": False, "kind": "none"},
            ports={"frontend": 2024, "agent": 2024},
        )
        assert s.ports.agent == 2024

    @pytest.mark.parametrize("port", [0, -1, 65536, 99999])
    def test_out_of_range_rejected(self, port):
        with pytest.raises(ValidationError):
            AgentSpec(name="x-y", ports={"agent": port})

    def test_ports_reach_the_templates(self):
        from langctl.core.generate.scaffold import render_context

        ctx = render_context(spec(ports={"frontend": 3001, "agent": 2025}))
        assert ctx["frontend_port"] == 3001
        assert ctx["backend_port"] == 2025


class TestLegacyPortLayout:
    """Projects scaffolded before `ports` existed keep loading and keep their
    ports — the values lived under frontend/backend then."""

    def test_legacy_sections_are_migrated(self):
        s = AgentSpec.from_yaml(
            "name: legacy-agent\nfrontend:\n  port: 3001\nbackend:\n  port: 2025\n"
        )
        assert (s.ports.frontend, s.ports.agent) == (3001, 2025)

    def test_legacy_collision_still_rejected(self):
        with pytest.raises(SpecError, match="must differ"):
            AgentSpec.from_yaml(
                "name: legacy-agent\nfrontend:\n  port: 3000\nbackend:\n  port: 3000\n"
            )

    def test_explicit_ports_win_per_key(self):
        s = AgentSpec.from_yaml(
            "name: legacy-agent\nports:\n  agent: 2026\n"
            "frontend:\n  port: 3001\nbackend:\n  port: 2025\n"
        )
        assert (s.ports.frontend, s.ports.agent) == (3001, 2026)

    def test_saved_file_uses_the_new_layout(self):
        text = AgentSpec.from_yaml("name: legacy-agent\nbackend:\n  port: 2025\n").to_yaml()
        assert "ports:\n  frontend: 3000\n  agent: 2025" in text
        # The old top-level section is gone; `backend` under memory is a
        # different key and stays.
        assert not re.search(r"^backend:", text, re.M)


class TestLanggraphConfig:
    def test_python_config_shape(self):
        cfg = spec(name="support-agent").to_langgraph_config()
        assert cfg["dependencies"] == ["."]
        assert cfg["graphs"] == {"agent": "./src/support_agent/agent.py:graph"}
        assert cfg["python_version"] == "3.11"
        assert "node_version" not in cfg

    def test_node_config_shape(self):
        cfg = AgentSpec(name="x-y", runtime="node").to_langgraph_config()
        # Schema declares node_version as a *string* enum ["20"]; an int fails validation.
        assert cfg["node_version"] == "20"
        assert isinstance(cfg["node_version"], str)
        assert "python_version" not in cfg
        assert "dependencies" not in cfg

    def test_store_path_is_emitted_for_persistent_memory(self):
        """Verified against a real restart: without `store.path` the dev server
        keeps long-term memory in process and loses it on exit."""
        cfg = spec(name="support-agent").to_langgraph_config()
        assert cfg["store"] == {
            "path": "./src/support_agent/memory/store.py:generate_store"
        }

    def test_no_store_key_when_long_term_memory_is_off(self):
        cfg = spec(memory={"long_term": {"enabled": False}}).to_langgraph_config()
        assert "store" not in cfg

    def test_no_store_key_for_the_in_memory_backend(self):
        # Nothing to persist, so do not override the server's managed store.
        cfg = spec(memory={"long_term": {"backend": "memory"}}).to_langgraph_config()
        assert "store" not in cfg

    def test_generative_ui_only_for_node(self):
        py = spec(frontend={"generative_ui": True}).to_langgraph_config()
        assert "ui" not in py  # Python agents cannot bundle TSX components
        node = AgentSpec(
            name="x-y", runtime="node", frontend={"generative_ui": True}
        ).to_langgraph_config()
        assert node["ui"] == {"agent": "./src/agent/ui.tsx"}

    def test_cors_allows_studio(self):
        # The browser uses a same-origin proxy, but Studio talks to the server directly.
        cors = spec().to_langgraph_config()["http"]["cors"]
        assert "https://smith.langchain.com" in cors["allow_origins"]

    def test_emitted_keys_are_all_owned(self):
        for s in (spec(), AgentSpec(name="x-y", runtime="node")):
            assert set(s.to_langgraph_config()) <= AgentSpec.owned_keys()


class TestRoundTrip:
    def test_yaml_round_trip_preserves_everything(self):
        original = spec(
            name="round-trip",
            runtime="python",
            memory={"checkpointer": "redis", "store": "memory", "semantic_search": True},
            ports={"frontend": 4000},
            frontend={"proxy_prefix": "/api/x/"},
        )
        assert AgentSpec.from_yaml(original.to_yaml()) == original

    def test_proxy_prefix_normalised(self):
        assert spec(frontend={"proxy_prefix": "/api/x/"}).frontend.proxy_prefix == "/api/x"

    def test_proxy_prefix_must_be_absolute(self):
        with pytest.raises(ValidationError):
            AgentSpec(name="x-y", frontend={"proxy_prefix": "api/x"})

    def test_bad_yaml_gives_actionable_error(self):
        with pytest.raises(SpecError) as e:
            AgentSpec.from_yaml("name: [unclosed")
        assert e.value.fix

    def test_non_mapping_yaml_rejected(self):
        with pytest.raises(SpecError, match="mapping"):
            AgentSpec.from_yaml("- a\n- b\n")


def test_config_is_json_serialisable():
    json.dumps(spec().to_langgraph_config())
