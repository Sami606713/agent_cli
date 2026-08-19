"""`langctl init` — adopting a project langctl never created.

The property that matters most: adoption writes exactly one file. Every test
that builds a hand-made project asserts the rest of the tree is byte-for-byte
untouched, because a command whose whole selling point is "safe to run on a
project you already have" earns no trust if it moves anything.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from langctl.core.errors import LangctlError
from langctl.core.project.adopt import Findings, ProjectAdopter
from langctl.core.project.spec import AgentSpec, slugify
from langctl.main import cli

runner = CliRunner()


def handmade(
    tmp_path,
    *,
    name: str = "weird-layout-bot",
    graph_target: str = "./app/graph.py:build_graph",
    dependencies: tuple[str, ...] = ("langgraph>=1.0", "langchain-anthropic>=1.0"),
):
    """A project langctl never touched — no agent.yaml, an arbitrary layout."""
    deps = "\n".join(f'    "{d}",' for d in dependencies)
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\ndependencies = [\n{deps}\n]\n', encoding="utf-8"
    )
    (tmp_path / "langgraph.json").write_text(
        json.dumps({"graphs": {"support": graph_target}, "env": ".env"}), encoding="utf-8"
    )
    return tmp_path


class TestProjectAdopter:
    """The class doing the work, tested directly — one method at a time."""

    def test_detect_reads_langgraph_json(self, tmp_path):
        handmade(tmp_path)
        adopter = ProjectAdopter(tmp_path)
        adopter.detect()
        assert adopter.found_langgraph_config
        assert adopter.langgraph_config["graphs"]["support"] == "./app/graph.py:build_graph"

    def test_detect_tolerates_no_langgraph_json_at_all(self, tmp_path):
        adopter = ProjectAdopter(tmp_path)
        adopter.detect()
        assert not adopter.found_langgraph_config

    def test_detect_raises_a_typed_error_for_broken_json(self, tmp_path):
        (tmp_path / "langgraph.json").write_text("{not json", encoding="utf-8")
        adopter = ProjectAdopter(tmp_path)
        with pytest.raises(LangctlError, match="not valid JSON"):
            adopter.detect()

    def test_infer_takes_the_name_from_pyproject(self, tmp_path):
        handmade(tmp_path, name="my-cool-agent")
        adopter = ProjectAdopter(tmp_path)
        adopter.detect()
        findings = adopter.infer()
        assert findings.name == "my-cool-agent"
        assert findings.name_source == "pyproject.toml"

    def test_infer_falls_back_to_the_directory_name(self, tmp_path):
        adopter = ProjectAdopter(tmp_path)
        adopter.detect()
        findings = adopter.infer()
        assert findings.name == slugify(tmp_path.name)
        assert findings.name_source == "directory name"

    def test_infer_slugifies_a_directory_name_agentspec_would_reject(self, tmp_path):
        # Caught live: pytest's own tmp_path names contain underscores, which
        # AgentSpec's name validator rejects outright — `init --yes` crashed
        # with a raw pydantic ValidationError instead of adopting the project.
        odd = tmp_path / "My_Weird Directory!!"
        odd.mkdir()
        adopter = ProjectAdopter(odd)
        adopter.detect()
        findings = adopter.infer()
        AgentSpec(name=findings.name)  # must not raise

    def test_infer_flags_a_conventional_graph_path(self, tmp_path):
        handmade(
            tmp_path,
            name="my-agent",
            graph_target="./src/my_agent/agent.py:graph",
        )
        adopter = ProjectAdopter(tmp_path)
        adopter.detect()
        findings = adopter.infer()
        assert findings.graph_path_is_conventional is True

    def test_infer_flags_an_unconventional_graph_path(self, tmp_path):
        handmade(tmp_path, graph_target="./app/graph.py:build_graph")
        adopter = ProjectAdopter(tmp_path)
        adopter.detect()
        findings = adopter.infer()
        assert findings.graph_path_is_conventional is False
        assert findings.expected_graph_target == "./src/weird_layout_bot/agent.py:graph"

    def test_infer_matches_an_installed_provider_package(self, tmp_path):
        handmade(tmp_path, dependencies=("langgraph>=1.0", "langchain-openai>=1.0"))
        adopter = ProjectAdopter(tmp_path)
        adopter.detect()
        findings = adopter.infer()
        assert findings.provider == "openai"

    def test_infer_finds_no_provider_with_no_matching_package(self, tmp_path):
        handmade(tmp_path, dependencies=("langgraph>=1.0",))
        adopter = ProjectAdopter(tmp_path)
        adopter.detect()
        findings = adopter.infer()
        assert findings.provider is None

    def test_build_spec_disables_long_term_memory(self, tmp_path):
        # AgentSpec defaults memory on; adoption must not inherit that, since
        # nothing here writes the memory/store.py the config would reference.
        findings = Findings(name="x-y", name_source="test")
        spec = ProjectAdopter(tmp_path).build_spec(findings, provider="anthropic", model=None)
        assert spec.memory.long_term.enabled is False

    def test_build_spec_disables_the_frontend(self, tmp_path):
        findings = Findings(name="x-y", name_source="test")
        spec = ProjectAdopter(tmp_path).build_spec(findings, provider="anthropic", model=None)
        assert spec.frontend.enabled is False

    def test_write_refuses_to_overwrite_an_existing_spec(self, tmp_path):
        adopter = ProjectAdopter(tmp_path)
        (tmp_path / "agent.yaml").write_text("name: already-here\n", encoding="utf-8")
        with pytest.raises(LangctlError, match="already exists"):
            adopter.write(AgentSpec(name="x-y"))

    def test_write_produces_a_spec_that_loads_back(self, tmp_path):
        adopter = ProjectAdopter(tmp_path)
        path = adopter.write(AgentSpec(name="round-trip"))
        assert AgentSpec.load(path).name == "round-trip"


class TestInitCommand:
    def test_writes_only_agent_yaml_nothing_else_moves(self, tmp_path, monkeypatch):
        handmade(tmp_path)
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "graph.py").write_text("# untouched", encoding="utf-8")
        before = {
            p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file() and p.name != "agent.yaml"
        }

        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["init", "--yes"])

        assert result.exit_code == 0
        assert (tmp_path / "agent.yaml").is_file()
        for path, content in before.items():
            assert path.read_bytes() == content, f"{path} was modified by init"

    def test_refuses_a_project_that_is_already_adopted(self, tmp_path, monkeypatch):
        (tmp_path / "agent.yaml").write_text("name: x-y\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["init"])
        assert result.exit_code != 0
        assert isinstance(result.exception, LangctlError)
        assert "already" in result.exception.message.lower()

    def test_yes_never_prompts_even_with_an_unconventional_layout(self, tmp_path, monkeypatch):
        handmade(tmp_path, graph_target="./app/graph.py:build_graph")
        (tmp_path / "app").mkdir()
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["init", "--yes"], input="")
        assert result.exit_code == 0
        assert (tmp_path / "agent.yaml").is_file()

    def test_declining_the_layout_warning_writes_nothing(self, tmp_path, monkeypatch):
        handmade(tmp_path, graph_target="./app/graph.py:build_graph")
        (tmp_path / "app").mkdir()
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["init"], input="n\n")
        assert result.exit_code != 0
        assert not (tmp_path / "agent.yaml").exists()

    def test_works_on_a_completely_empty_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["init", "--yes"])
        assert result.exit_code == 0
        spec = AgentSpec.load(tmp_path / "agent.yaml")
        assert spec.name == slugify(tmp_path.name)
        assert spec.model.provider == "anthropic"

    def test_the_adopted_project_works_with_other_commands(self, tmp_path, monkeypatch):
        handmade(tmp_path, dependencies=("langgraph>=1.0", "langchain-openai>=1.0"))
        monkeypatch.chdir(tmp_path)
        runner.invoke(cli, ["init", "--yes"])
        result = runner.invoke(cli, ["info"])
        assert result.exit_code == 0
        assert "openai" in result.output
