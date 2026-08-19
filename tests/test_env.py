"""`langctl env` — required variables, and whether `.env` sets them.

Matches Shopify's `app env show` / `app env pull`. The property that matters
most for `pull`: `.env.example` carries no secrets and is always regenerated,
`.env` does — it is only ever created once, never overwritten.
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


class TestEnvShow:
    def test_lists_a_required_variable_as_missing(self, tmp_path, monkeypatch):
        scaffolded(tmp_path, model={"provider": "openai"})
        (tmp_path / ".env").unlink(missing_ok=True)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["env", "show"])
        assert result.exit_code == 0
        assert "OPENAI_API_KEY" in result.output
        assert "missing" in result.output

    def test_a_filled_value_shows_as_set(self, tmp_path, monkeypatch):
        scaffolded(tmp_path, model={"provider": "openai"})
        (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-real\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["env", "show"])
        assert "set" in result.output
        assert "everything required is set" in result.output

    def test_a_present_but_empty_value_is_distinguished_from_missing(self, tmp_path, monkeypatch):
        scaffolded(tmp_path, model={"provider": "openai"})
        (tmp_path / ".env").write_text("OPENAI_API_KEY=\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["env", "show"])
        assert "empty" in result.output

    def test_a_provider_needing_no_key_reports_nothing_required(self, tmp_path, monkeypatch):
        scaffolded(
            tmp_path,
            model={"provider": "ollama", "name": "qwen3"},
            memory={"long_term": {"enabled": False}},
        )
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["env", "show"])
        assert result.exit_code == 0

    def test_outside_a_project_explains_itself(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["env", "show"])
        assert result.exit_code != 0


class TestEnvPull:
    def test_writes_env_example(self, tmp_path, monkeypatch):
        scaffolded(tmp_path)
        (tmp_path / ".env.example").unlink(missing_ok=True)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["env", "pull"])
        assert result.exit_code == 0
        assert (tmp_path / ".env.example").is_file()

    def test_creates_env_when_entirely_missing(self, tmp_path, monkeypatch):
        scaffolded(tmp_path)
        (tmp_path / ".env").unlink(missing_ok=True)
        monkeypatch.chdir(tmp_path)
        runner.invoke(cli, ["env", "pull"])
        assert (tmp_path / ".env").is_file()

    def test_never_overwrites_an_existing_env(self, tmp_path, monkeypatch):
        # The property that matters most: .env holds real secrets.
        scaffolded(tmp_path)
        secret = "OPENAI_API_KEY=sk-do-not-lose-this\n"
        (tmp_path / ".env").write_text(secret, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        runner.invoke(cli, ["env", "pull"])
        assert (tmp_path / ".env").read_text(encoding="utf-8") == secret

    def test_env_example_reflects_the_current_spec_even_if_stale_on_disk(
        self, tmp_path, monkeypatch
    ):
        # If agent.yaml changed since the last scaffold (a hand edit, or
        # `add`), .env.example must catch up — it carries no secrets, so
        # there is nothing to protect by leaving it alone.
        scaffolded(tmp_path, model={"provider": "openai"})
        (tmp_path / ".env.example").write_text("STALE=true\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        runner.invoke(cli, ["env", "pull"])
        content = (tmp_path / ".env.example").read_text(encoding="utf-8")
        assert "OPENAI_API_KEY" in content
        assert "STALE" not in content

    def test_outside_a_project_explains_itself(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["env", "pull"])
        assert result.exit_code != 0


class TestEnvAfterAdoption:
    """The motivating case: `init` writes agent.yaml and nothing else, so an
    adopted project has no .env.example at all until `env pull` makes one."""

    def test_pull_creates_what_init_never_scaffolds(self, tmp_path, monkeypatch):
        from langctl.core.project.adopt import ProjectAdopter

        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "adopted"\ndependencies = ["langchain-openai>=1.0"]\n',
            encoding="utf-8",
        )
        adopter = ProjectAdopter(tmp_path)
        adopter.detect()
        findings = adopter.infer()
        spec = adopter.build_spec(findings, provider=findings.provider or "anthropic", model=None)
        adopter.write(spec)

        assert not (tmp_path / ".env.example").exists()
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["env", "pull"])
        assert result.exit_code == 0
        assert (tmp_path / ".env.example").is_file()
