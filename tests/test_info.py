"""`langctl info` — a formatted read of agent.yaml, nothing more.

Every value shown here is asserted against what was actually configured, so a
change to a field name silently breaking the summary fails a test instead of
shipping a blank row.
"""

from __future__ import annotations

from typer.testing import CliRunner

from langctl.core.generate.scaffold import scaffold
from langctl.core.project.spec import AgentSpec
from langctl.main import cli

runner = CliRunner()


def scaffolded(tmp_path, **overrides) -> AgentSpec:
    spec = AgentSpec(name="demo-agent", **overrides)
    scaffold(spec, tmp_path)
    return spec


class TestInfo:
    def test_shows_the_project_name_and_root(self, tmp_path, monkeypatch):
        scaffolded(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["info"])
        assert result.exit_code == 0
        assert "demo-agent" in result.output

    def test_shows_the_model(self, tmp_path, monkeypatch):
        scaffolded(tmp_path, model={"provider": "anthropic", "name": "claude-opus-5"})
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["info"])
        assert "anthropic" in result.output
        assert "claude-opus-5" in result.output

    def test_shows_memory_backend(self, tmp_path, monkeypatch):
        spec = scaffolded(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["info"])
        assert spec.memory.long_term.backend in result.output

    def test_shows_disabled_memory_plainly(self, tmp_path, monkeypatch):
        scaffolded(tmp_path, memory={"long_term": {"enabled": False}})
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["info"])
        assert "disabled" in result.output

    def test_shows_no_frontend_plainly(self, tmp_path, monkeypatch):
        scaffolded(tmp_path, frontend={"enabled": False, "kind": "none"})
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["info"])
        assert "none" in result.output

    def test_shows_an_unset_deploy_target_honestly(self, tmp_path, monkeypatch):
        # A new project has never been asked; info must not invent an answer.
        scaffolded(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["info"])
        assert "not chosen yet" in result.output

    def test_shows_a_recorded_deploy_target_by_its_label(self, tmp_path, monkeypatch):
        scaffolded(tmp_path, deploy={"target": "vps"})
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["info"])
        assert "VPS" in result.output

    def test_never_crashes_on_an_agent_yaml_it_can_still_load(self, tmp_path, monkeypatch):
        # Every field it reads must tolerate every valid spec shape, since info
        # is meant to be the safe, read-only thing to run when confused.
        scaffolded(
            tmp_path,
            model={"provider": "custom-cloud", "name": "m1", "package": "langchain-custom"},
            middleware={"custom": ["rate_limit"]},
        )
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["info"])
        assert result.exit_code == 0
        assert "rate_limit" in result.output
