"""Chat model providers, including ones langctl has never heard of.

The provider list is open on purpose: `init_chat_model` supports 25+ providers
and gains more, so a closed Literal would mean a new LangChain integration
could not be used until langctl shipped a release.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from langctl.core.catalog.models import PROVIDERS, WIZARD_PROVIDERS, is_known, normalise
from langctl.core.generate.deps import required_env_vars, runtime_packages
from langctl.core.generate.scaffold import scaffold
from langctl.core.project.spec import AgentSpec, ModelSpec


def project(tmp_path, **model) -> AgentSpec:
    spec = AgentSpec(
        name="demo-agent", frontend={"enabled": False, "kind": "none"}, model=model
    )
    scaffold(spec, tmp_path)
    return spec


class TestRegistry:
    def test_covers_the_common_providers(self):
        for name in ("anthropic", "openai", "google_genai", "ollama", "openrouter",
                     "groq", "bedrock", "mistralai", "deepseek", "together"):
            assert is_known(name), name

    def test_every_wizard_choice_is_registered(self):
        for name in WIZARD_PROVIDERS:
            assert name in PROVIDERS

    def test_every_provider_declares_a_package(self):
        # A provider without a package is a project that imports and then fails.
        for name, provider in PROVIDERS.items():
            assert provider.package, name

    @pytest.mark.parametrize("alias,canonical", [
        ("google", "google_genai"), ("gemini", "google_genai"),
        ("azure", "azure_openai"), ("aws", "bedrock"), ("OpenAI", "openai"),
    ])
    def test_aliases_normalise(self, alias, canonical):
        assert normalise(alias) == canonical


class TestModelSpec:
    def test_default_is_anthropic(self):
        assert ModelSpec().identifier == "anthropic:claude-opus-5"

    def test_choosing_a_provider_updates_the_model(self):
        # Otherwise `--model-provider openai` silently keeps claude-opus-5.
        assert ModelSpec(provider="openai").identifier == "openai:gpt-5.5"

    def test_no_name_is_invented_for_providers_without_a_safe_default(self):
        # "ollama:claude-opus-5" would be nonsense; the name comes from
        # MODEL_NAME, so record nothing rather than something false.
        assert ModelSpec(provider="ollama").name == ""

    def test_an_explicit_model_is_respected(self):
        assert ModelSpec(provider="openai", name="gpt-4o").identifier == "openai:gpt-4o"

    def test_unknown_provider_is_rejected_with_a_suggestion(self):
        with pytest.raises(ValidationError, match="opanai|openai"):
            ModelSpec(provider="opanai")

    def test_unknown_provider_is_allowed_when_it_declares_a_package(self):
        spec = ModelSpec(provider="mycloud", name="m1", package="langchain-mycloud")
        assert spec.package_requirement == "langchain-mycloud"

    def test_empty_provider_is_rejected(self):
        with pytest.raises(ValidationError):
            ModelSpec(provider="   ")

    def test_providers_without_a_key_report_none(self):
        # Ollama runs locally; requiring a key would block a valid setup.
        assert ModelSpec(provider="ollama").api_key_env is None

    def test_key_env_can_be_overridden(self):
        spec = ModelSpec(provider="openai", api_key_env_override="MY_GATEWAY_KEY")
        assert spec.api_key_env == "MY_GATEWAY_KEY"


class TestConstructionPath:
    """A "provider:model" string cannot carry an endpoint or options."""

    def test_plain_provider_needs_no_construction(self):
        assert ModelSpec(provider="openai").needs_construction is False

    def test_base_url_forces_construction(self):
        assert ModelSpec(provider="openai", base_url="http://localhost:1234/v1"
                         ).needs_construction is True

    def test_options_force_construction(self):
        assert ModelSpec(provider="openai", options={"temperature": 0.2}
                         ).needs_construction is True

    def test_generated_agent_passes_a_string_by_default(self, tmp_path):
        project(tmp_path)
        agent = (tmp_path / "src/demo_agent/agent.py").read_text()
        assert "model=settings.model_identifier" in agent
        assert "build_model" not in agent

    def test_generated_agent_builds_the_model_for_a_custom_endpoint(self, tmp_path):
        project(tmp_path, provider="openai", name="local",
                base_url="http://localhost:1234/v1")
        agent = (tmp_path / "src/demo_agent/agent.py").read_text()
        config = (tmp_path / "src/demo_agent/config.py").read_text()
        assert "model=build_model()" in agent
        assert "base_url=settings.model_base_url" in config
        # The endpoint stays overridable per environment.
        assert 'os.getenv("MODEL_BASE_URL"' in config

    def test_options_are_emitted(self, tmp_path):
        project(tmp_path, provider="openai", options={"temperature": 0.2})
        config = (tmp_path / "src/demo_agent/config.py").read_text()
        assert "temperature=0.2" in config


class TestDependencyFanOut:
    @pytest.mark.parametrize("provider,fragment", [
        ("openrouter", "langchain-openrouter"),
        ("groq", "langchain-groq"),
        ("deepseek", "langchain-deepseek"),
        ("ollama", "langchain-ollama"),
    ])
    def test_provider_package_is_added(self, provider, fragment):
        spec = AgentSpec(name="demo-agent", model={"provider": provider})
        assert any(fragment in p for p in runtime_packages(spec))

    def test_unknown_provider_package_is_added(self, tmp_path):
        spec = AgentSpec(
            name="demo-agent",
            model={"provider": "mycloud", "name": "m1", "package": "langchain-mycloud"},
        )
        assert "langchain-mycloud" in runtime_packages(spec)

    def test_keyless_provider_requires_no_api_key(self):
        spec = AgentSpec(name="demo-agent", model={"provider": "ollama"})
        assert spec.model.api_key_env is None
        # …but the model name still has to come from somewhere.
        assert list(required_env_vars(spec)) == ["MODEL_NAME"]

    def test_provider_key_is_required(self):
        spec = AgentSpec(name="demo-agent", model={"provider": "groq"})
        assert "GROQ_API_KEY" in required_env_vars(spec)


class TestGeneratedConfig:
    def test_keyless_provider_skips_validation(self, tmp_path):
        # Demanding a key that does not exist would block a working local setup.
        project(tmp_path, provider="ollama")
        config = (tmp_path / "src/demo_agent/config.py").read_text()
        assert "needs no API key" in config

    def test_keyed_provider_validates_at_import(self, tmp_path):
        project(tmp_path, provider="groq")
        config = (tmp_path / "src/demo_agent/config.py").read_text()
        assert "GROQ_API_KEY" in config

    def test_env_example_lists_the_right_key(self, tmp_path):
        project(tmp_path, provider="openrouter", name="z-ai/glm-5.2")
        assert "OPENROUTER_API_KEY" in (tmp_path / ".env.example").read_text()


class TestModelFromEnv:
    """Some providers have no safe default model.

    A hosted provider does: everyone with an OpenAI key can reach gpt-5.5. A
    local runtime does not — the model is whatever that machine has pulled, so
    a name compiled into the code fails on the first message with an opaque 404
    from a server langctl never saw.
    """

    @pytest.mark.parametrize("provider", ["ollama", "litellm", "huggingface"])
    def test_local_and_gateway_providers_read_the_name_from_env(self, provider):
        assert ModelSpec(provider=provider, name="x").model_from_env is True

    @pytest.mark.parametrize("provider", ["openai", "anthropic", "groq"])
    def test_hosted_providers_keep_a_default(self, provider):
        assert ModelSpec(provider=provider).model_from_env is False

    def test_a_custom_endpoint_is_the_same_situation(self):
        spec = ModelSpec(provider="openai", name="x", base_url="http://localhost:1234/v1")
        assert spec.model_from_env is True

    def test_unknown_providers_read_from_env(self):
        spec = ModelSpec(provider="mycloud", name="m1", package="langchain-mycloud")
        assert spec.model_from_env is True

    def test_no_model_is_guessed_for_ollama(self):
        from langctl.core.catalog.models import get

        assert get("ollama").default_model is None

    def test_model_name_is_a_required_env_var(self):
        spec = AgentSpec(name="demo-agent", model={"provider": "ollama", "name": "qwen3"})
        assert "MODEL_NAME" in required_env_vars(spec)

    def test_generated_config_has_no_baked_default(self, tmp_path):
        project(tmp_path, provider="ollama", name="qwen3")
        config = (tmp_path / "src/demo_agent/config.py").read_text()
        assert 'os.getenv("MODEL_NAME", "")' in config
        assert "qwen3" not in config  # the name lives in .env, not the code

    def test_generated_config_fails_fast_when_unset(self, tmp_path):
        project(tmp_path, provider="ollama", name="qwen3")
        config = (tmp_path / "src/demo_agent/config.py").read_text()
        assert "MODEL_NAME is not set" in config
        assert "ollama list" in config  # says how to find a valid name

    def test_env_example_seeds_the_chosen_name(self, tmp_path):
        project(tmp_path, provider="ollama", name="qwen3")
        env = (tmp_path / ".env.example").read_text()
        assert "MODEL_NAME=qwen3" in env

    def test_hosted_provider_keeps_the_name_in_code(self, tmp_path):
        project(tmp_path, provider="openai")
        config = (tmp_path / "src/demo_agent/config.py").read_text()
        assert 'os.getenv("MODEL_NAME", "gpt-5.5")' in config
