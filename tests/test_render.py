import pytest
from jinja2 import UndefinedError

from langctl.core.render import render_tree, substitute_path
from langctl.core.scaffold import config_drift, merge_langgraph_config, scaffold
from langctl.core.spec import AgentSpec


class TestSubstitutePath:
    def test_whole_segment_is_substituted(self):
        assert substitute_path("__pkg__", {"pkg": "my_agent"}) == "my_agent"

    def test_dunder_filenames_are_not_placeholders(self):
        # Regression: `__init__.py.j2` was being parsed as a placeholder named
        # "init", which broke every scaffold.
        for name in ("__init__.py", "__main__.py", "__init__.py.j2"):
            assert substitute_path(name, {"pkg": "x"}) == name

    def test_dot_prefix_becomes_dotfile(self):
        assert substitute_path("dot.gitignore", {}) == ".gitignore"

    def test_unknown_whole_segment_placeholder_raises(self):
        with pytest.raises(KeyError, match="nope"):
            substitute_path("__nope__", {"pkg": "x"})


class TestRenderTree:
    def test_renders_j2_and_copies_the_rest(self, tmp_path):
        src = tmp_path / "tpl"
        (src / "__pkg__").mkdir(parents=True)
        (src / "__pkg__" / "__init__.py.j2").write_text("# {{ name }}\n")
        (src / "__pkg__" / "static.txt").write_text("{{ not_rendered }}\n")
        (src / "dot.gitignore").write_text("*.pyc\n")

        render_tree(src, tmp_path / "out", {"pkg": "my_agent", "name": "demo"})

        out = tmp_path / "out"
        assert (out / "my_agent" / "__init__.py").read_text() == "# demo\n"
        # Non-.j2 files are copied byte for byte, so TSX braces survive.
        assert (out / "my_agent" / "static.txt").read_text() == "{{ not_rendered }}\n"
        assert (out / ".gitignore").exists()

    def test_undefined_variable_fails_loudly(self, tmp_path):
        src = tmp_path / "tpl"
        src.mkdir()
        (src / "f.txt.j2").write_text("{{ missing }}")
        with pytest.raises(UndefinedError):
            render_tree(src, tmp_path / "out", {})

    def test_existing_files_are_not_clobbered(self, tmp_path):
        src = tmp_path / "tpl"
        src.mkdir()
        (src / "keep.txt.j2").write_text("new")
        out = tmp_path / "out"
        out.mkdir()
        (out / "keep.txt").write_text("mine")

        result = render_tree(src, out, {})
        assert (out / "keep.txt").read_text() == "mine"
        assert result.skipped and not result.written

        result = render_tree(src, out, {}, overwrite=True)
        assert (out / "keep.txt").read_text() == "new"


class TestScaffold:
    def test_python_project_has_the_expected_shape(self, tmp_path):
        spec = AgentSpec(name="demo-agent")
        scaffold(spec, tmp_path)
        for rel in (
            "agent.yaml",
            "langgraph.json",
            "pyproject.toml",
            ".env.example",
            ".gitignore",
            "src/demo_agent/agent.py",
            "src/demo_agent/__init__.py",
            "tests/test_agent.py",
            "web/package.json",
            "web/app/api/agent/[...path]/route.ts",
            "web/app/components/Chat.tsx",
        ):
            assert (tmp_path / rel).is_file(), f"missing {rel}"

    def test_no_frontend_when_disabled(self, tmp_path):
        spec = AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"})
        scaffold(spec, tmp_path)
        assert not (tmp_path / "web").exists()

    def test_no_unrendered_jinja_left_in_output(self, tmp_path):
        """A stray {{ }} in a rendered file means a template bug shipped."""
        scaffold(AgentSpec(name="demo-agent"), tmp_path)
        for path in tmp_path.rglob("*"):
            if not path.is_file() or "node_modules" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            # Chat.tsx legitimately contains JSX braces, but never Jinja tags.
            assert "{%" not in text, f"unrendered jinja block in {path}"
            assert "{{ " not in text, f"unrendered jinja expression in {path}"

    def test_secrets_are_never_public_in_the_frontend(self, tmp_path):
        """Guard the one mistake that leaks the API key to every visitor."""
        scaffold(AgentSpec(name="demo-agent"), tmp_path)
        for path in (tmp_path / "web").rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                assert "NEXT_PUBLIC_LANGSMITH" not in text
                assert "NEXT_PUBLIC_ANTHROPIC" not in text

    def test_proxy_route_defaults_to_the_configured_backend_port(self, tmp_path):
        scaffold(AgentSpec(name="demo-agent", backend={"port": 2500}), tmp_path)
        route = (tmp_path / "web/app/api/agent/[...path]/route.ts").read_text()
        assert "http://127.0.0.1:2500" in route
        assert "AGENT_PROXY_TARGET" in route


class TestConfigMerge:
    def test_hand_written_keys_survive(self):
        spec = AgentSpec(name="demo-agent")
        existing = {
            "auth": {"path": "./src/demo_agent/auth.py:auth"},
            "dockerfile_lines": ["RUN apt-get update"],
            "graphs": {"agent": "./old/path.py:graph"},
        }
        merged = merge_langgraph_config(spec, existing)
        assert merged["auth"] == existing["auth"]
        assert merged["dockerfile_lines"] == existing["dockerfile_lines"]
        # Owned keys are still overwritten.
        assert merged["graphs"] == {"agent": "./src/demo_agent/agent.py:graph"}

    def test_drift_is_reported_for_owned_keys_only(self):
        spec = AgentSpec(name="demo-agent")
        drift = config_drift(spec, {"graphs": {"agent": "./other.py:graph"}, "auth": {"x": 1}})
        assert "graphs" in drift
        assert "auth" not in drift

    def test_no_drift_when_in_sync(self):
        spec = AgentSpec(name="demo-agent")
        assert config_drift(spec, spec.to_langgraph_config()) == {}


class TestBackendImportability:
    """Regression guards for two failures found only by running the real server."""

    def test_agent_module_uses_absolute_imports(self, tmp_path):
        # The Agent Server loads agent.py by path, so relative imports raise
        # "attempted relative import with no known parent package".
        scaffold(AgentSpec(name="demo-agent"), tmp_path)
        source = (tmp_path / "src/demo_agent/agent.py").read_text()
        assert "from demo_agent.config import" in source
        assert "\nfrom ." not in source

    def test_requires_python_excludes_unsupported_versions(self, tmp_path):
        # langgraph.json's python_version enum is 3.11/3.12/3.13; without an
        # upper bound uv resolves 3.14 locally and drifts from the deployment.
        scaffold(AgentSpec(name="demo-agent"), tmp_path)
        assert '">=3.11,<3.14"' in (tmp_path / "pyproject.toml").read_text()


class TestFrontendApiUrl:
    """The SDK builds URLs with `new URL(apiUrl + path)` — no base argument.

    A relative apiUrl therefore throws "Failed to construct 'URL': Invalid URL"
    on the first request. The UI must pass an absolute same-origin URL.
    """

    def test_api_url_is_absolute_at_runtime(self, tmp_path):
        scaffold(AgentSpec(name="demo-agent"), tmp_path)
        chat = (tmp_path / "web/app/components/Chat.tsx").read_text()
        assert "window.location.origin" in chat
        # The bare relative prefix must never be handed to useStream directly.
        assert 'apiUrl: "/api/agent"' not in chat
        assert "apiUrl," in chat

    def test_api_url_is_ssr_safe(self, tmp_path):
        scaffold(AgentSpec(name="demo-agent"), tmp_path)
        chat = (tmp_path / "web/app/components/Chat.tsx").read_text()
        assert 'typeof window === "undefined"' in chat

    def test_proxy_prefix_is_respected(self, tmp_path):
        scaffold(AgentSpec(name="demo-agent", frontend={"proxy_prefix": "/api/llm"}), tmp_path)
        chat = (tmp_path / "web/app/components/Chat.tsx").read_text()
        assert 'PROXY_PREFIX = "/api/llm"' in chat

    def test_route_handler_lives_where_the_client_calls(self, tmp_path):
        """A custom prefix must move the route file too, or every call 404s."""
        scaffold(AgentSpec(name="demo-agent", frontend={"proxy_prefix": "/api/llm"}), tmp_path)
        assert (tmp_path / "web/app/api/llm/[...path]/route.ts").is_file()
        assert not (tmp_path / "web/app/api/agent").exists()
