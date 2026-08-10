import json

import pytest
from pydantic import ValidationError

from langctl.core.errors import SpecError
from langctl.core.spec import AgentSpec


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
            AgentSpec(
                name="x-y",
                runtime="python",
                mode="embedded",
                frontend={"kind": "nextjs_embedded"},
            )

    def test_node_embedded_is_valid(self):
        s = AgentSpec(
            name="x-y", runtime="node", mode="embedded", frontend={"kind": "nextjs_embedded"}
        )
        assert s.uses_agent_server is False

    def test_embedded_frontend_requires_embedded_mode(self):
        with pytest.raises(ValidationError):
            AgentSpec(name="x-y", runtime="node", mode="proxy",
                      frontend={"kind": "nextjs_embedded"})

    def test_port_collision_rejected(self):
        with pytest.raises(ValidationError, match="must differ"):
            AgentSpec(name="x-y", backend={"port": 3000}, frontend={"port": 3000})

    def test_proxy_mode_uses_agent_server(self):
        assert spec().uses_agent_server is True


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

    def test_semantic_search_emits_store_index(self):
        cfg = spec(memory={"store": "postgres", "semantic_search": True}).to_langgraph_config()
        assert cfg["store"]["index"]["dims"] == 1536

    def test_no_store_without_semantic_search(self):
        assert "store" not in spec().to_langgraph_config()

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
            frontend={"port": 4000, "proxy_prefix": "/api/x/"},
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
