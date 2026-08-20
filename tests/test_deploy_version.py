"""Tagging deploys by commit, and rolling back to one.

`docker-compose.yml` is only ever rendered once — `deploy` never overwrites a
stack file that already exists — so versioning cannot live inside it. These
tests pin the actual mechanism: tag derivation from git, the `docker tag`
argv, and the history recorded in `.langctl/state.json`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from langctl.core.deploy.version import (
    current_tag,
    deploy_history,
    deploy_tag,
    git_sha,
    image_exists,
    is_dirty,
    record_deploy,
    restore_tag,
    set_current,
    tag_image,
)
from langctl.core.errors import LangctlError
from langctl.core.generate.scaffold import scaffold
from langctl.core.project.manifest import Project
from langctl.core.project.spec import AgentSpec
from langctl.main import cli

runner = CliRunner()
DOCKER = "/usr/bin/docker"


def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return tmp_path


def commit(root: Path, message: str = "init") -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=root, check=True)


class TestDeployTag:
    def test_outside_git_falls_back_to_a_timestamp(self, tmp_path):
        assert git_sha(tmp_path) is None
        tag = deploy_tag(tmp_path)
        assert tag.startswith("untracked-")

    def test_a_clean_repo_tags_by_commit_alone(self, tmp_path):
        root = git_repo(tmp_path)
        (root / "f.txt").write_text("x", encoding="utf-8")
        commit(root)
        assert is_dirty(root) is False
        assert deploy_tag(root) == git_sha(root)

    def test_uncommitted_changes_are_marked(self, tmp_path):
        """A version list must never imply a commit reproduces what shipped."""
        root = git_repo(tmp_path)
        (root / "f.txt").write_text("x", encoding="utf-8")
        commit(root)
        (root / "f.txt").write_text("changed", encoding="utf-8")
        assert is_dirty(root) is True
        assert deploy_tag(root) == f"{git_sha(root)}-dirty"

    def test_the_tag_changes_with_the_commit(self, tmp_path):
        root = git_repo(tmp_path)
        (root / "f.txt").write_text("x", encoding="utf-8")
        commit(root, "one")
        first = deploy_tag(root)
        (root / "f.txt").write_text("y", encoding="utf-8")
        commit(root, "two")
        assert deploy_tag(root) != first


class TestArgvBuilders:
    def test_tag_snapshots_latest(self):
        assert tag_image(DOCKER, "demo-agent", "abc123") == [
            DOCKER,
            "tag",
            "demo-agent:latest",
            "demo-agent:abc123",
        ]

    def test_restore_is_the_exact_reverse(self):
        image, tag = "demo-agent", "abc123"
        forward = tag_image(DOCKER, image, tag)
        backward = restore_tag(DOCKER, image, tag)
        assert forward[2:] == list(reversed(backward[2:]))

    def test_image_exists_inspects_the_tagged_image(self):
        assert image_exists(DOCKER, "demo-agent", "abc123")[-1] == "demo-agent:abc123"

    def test_no_builder_spawns_a_bare_docker(self):
        # Windows resolves .cmd shims by path, not name — every argv here must
        # start with the resolved path the caller passed in, never "docker".
        for argv in (
            tag_image(DOCKER, "x", "t"),
            restore_tag(DOCKER, "x", "t"),
            image_exists(DOCKER, "x", "t"),
        ):
            assert argv[0] == DOCKER


class TestHistory:
    @pytest.fixture
    def project(self, tmp_path) -> Project:
        spec = AgentSpec(name="demo-agent")
        scaffold(spec, tmp_path)
        return Project(root=tmp_path, spec=spec)

    def test_a_fresh_project_has_no_history(self, project):
        assert deploy_history(project) == []
        assert current_tag(project) is None

    def test_recording_a_deploy_makes_it_current(self, project):
        record_deploy(project, "abc123", ["demo-agent-agent", "demo-agent-web"])
        history = deploy_history(project)
        assert len(history) == 1
        assert history[0].tag == "abc123"
        assert history[0].images == ("demo-agent-agent", "demo-agent-web")
        assert current_tag(project) == "abc123"

    def test_dirty_is_read_from_the_tag_itself(self, project):
        record_deploy(project, "abc123-dirty", ["demo-agent-agent"])
        assert deploy_history(project)[0].dirty is True
        record_deploy(project, "def456", ["demo-agent-agent"])
        assert deploy_history(project)[1].dirty is False

    def test_history_accumulates_across_deploys(self, project):
        record_deploy(project, "one", ["demo-agent-agent"])
        record_deploy(project, "two", ["demo-agent-agent"])
        record_deploy(project, "three", ["demo-agent-agent"])
        tags = [r.tag for r in deploy_history(project)]
        assert tags == ["one", "two", "three"]
        assert current_tag(project) == "three"

    def test_a_reloaded_project_sees_the_same_history(self, project):
        record_deploy(project, "abc123", ["demo-agent-agent"])
        reloaded = Project.load(project.root)
        assert [r.tag for r in deploy_history(reloaded)] == ["abc123"]

    def test_set_current_does_not_touch_history(self, project):
        # This is what `rollback` does — it built nothing new, so no new row.
        record_deploy(project, "one", ["demo-agent-agent"])
        record_deploy(project, "two", ["demo-agent-agent"])
        set_current(project, "one")
        assert current_tag(project) == "one"
        assert [r.tag for r in deploy_history(project)] == ["one", "two"]


class TestVersionsCommand:
    def test_says_so_plainly_with_nothing_recorded(self, tmp_path, monkeypatch):
        scaffold(AgentSpec(name="demo-agent"), tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["versions"])
        assert result.exit_code == 0
        assert "No recorded deploys" in result.output

    def test_lists_a_recorded_deploy(self, tmp_path, monkeypatch):
        spec = AgentSpec(name="demo-agent")
        scaffold(spec, tmp_path)
        project = Project(root=tmp_path, spec=spec)
        record_deploy(project, "abc123", ["demo-agent-agent"])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["versions"])
        assert result.exit_code == 0
        assert "abc123" in result.output

    def test_outside_a_project_explains_itself(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["versions"])
        assert result.exit_code != 0

    def test_the_timestamp_is_readable_not_a_raw_isoformat(self, tmp_path, monkeypatch):
        # `record.at` is `datetime.now(UTC).isoformat()` — long, with
        # microseconds and a +00:00 offset. Caught live: it truncated inside
        # the table column and was barely legible.
        spec = AgentSpec(name="demo-agent")
        scaffold(spec, tmp_path)
        project = Project(root=tmp_path, spec=spec)
        record_deploy(project, "abc123", ["demo-agent-agent"])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["versions"])
        assert result.exit_code == 0
        raw_timestamp = deploy_history(project)[0].at
        assert raw_timestamp not in result.output
        assert "UTC" in result.output


class TestRollbackCommand:
    def test_an_unknown_tag_names_what_is_available(self, tmp_path, monkeypatch):
        # CliRunner invokes the Typer app directly, bypassing the console-script
        # wrapper that renders LangctlError as a panel — so the error is
        # asserted on the raised exception itself, the same way test_cli.py's
        # other error-path tests only check exit_code, kept precise here by
        # reading the exception's own message and fix.
        spec = AgentSpec(name="demo-agent")
        scaffold(spec, tmp_path)
        project = Project(root=tmp_path, spec=spec)
        record_deploy(project, "abc123", ["demo-agent-agent"])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["rollback", "nonexistent"])
        assert result.exit_code != 0
        assert isinstance(result.exception, LangctlError)
        assert "abc123" in result.exception.fix

    def test_a_missing_image_refuses_and_suggests_a_redeploy(self, tmp_path, monkeypatch):
        """Without a running Docker daemon `docker image inspect` fails for any
        tag — the same failure a pruned image produces — so this exercises the
        real refusal path end to end rather than mocking `docker`."""
        spec = AgentSpec(name="demo-agent")
        scaffold(spec, tmp_path)
        project = Project(root=tmp_path, spec=spec)
        record_deploy(project, "abc123", ["demo-agent-agent"])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["rollback", "abc123"])
        assert result.exit_code != 0
        assert isinstance(result.exception, LangctlError)
        assert "no longer on" in result.exception.message
        assert "langctl deploy" in result.exception.fix

    def test_each_missing_image_is_paired_with_the_right_tag(self, tmp_path, monkeypatch):
        """Caught live: the message joined every image name first and appended
        `:tag` once at the end, reading as one image literally named
        "demo-agent-agent, demo-agent-web:abc123" instead of two images each
        missing that tag."""
        spec = AgentSpec(name="demo-agent")
        scaffold(spec, tmp_path)
        project = Project(root=tmp_path, spec=spec)
        record_deploy(project, "abc123", ["demo-agent-agent", "demo-agent-web"])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["rollback", "abc123"])
        assert isinstance(result.exception, LangctlError)
        assert "demo-agent-agent:abc123" in result.exception.message
        assert "demo-agent-web:abc123" in result.exception.message

    def test_outside_a_project_explains_itself(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["rollback", "abc123"])
        assert result.exit_code != 0
