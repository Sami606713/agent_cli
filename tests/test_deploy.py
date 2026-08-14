"""Both halves deploy together, or not at all.

The value of this command is one property: the frontend and the agent land in
one operation, wired, with no address for anyone to copy. These tests pin that
property and the handful of details that quietly break it — most of which were
found by breaking them first.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from langctl.core.deploy.stack import STACK_FILES, emit, missing_files
from langctl.core.deploy.targets import (
    ENV_FILE,
    RSYNC_EXCLUDES,
    Remote,
    compose_down,
    compose_logs,
    compose_up,
    missing_secrets,
    over_ssh,
    parse_remote,
    read_env_file,
    rsync_project,
)
from langctl.core.errors import LangctlError
from langctl.core.generate.scaffold import scaffold
from langctl.core.project.spec import AgentSpec

DOCKER = "/usr/bin/docker"


@pytest.fixture
def project(tmp_path) -> tuple[AgentSpec, Path]:
    spec = AgentSpec(name="demo-agent")
    scaffold(spec, tmp_path)
    return spec, tmp_path


def compose_of(root: Path) -> dict:
    return yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))


class TestOneStack:
    def test_every_file_is_written(self, project):
        spec, root = project
        emit(spec, root)
        assert missing_files(root) == []
        for rel in STACK_FILES:
            assert (root / rel).is_file(), rel

    @pytest.mark.parametrize("licensed", [False, True])
    def test_both_stacks_carry_the_same_four_services(self, project, licensed):
        spec, root = project
        emit(spec, root, licensed=licensed)
        assert set(compose_of(root)["services"]) == {"web", "agent", "postgres", "redis"}

    def test_the_unlicensed_agent_is_given_the_database(self, project):
        """No licence, but the graph's own store still gets real Postgres."""
        spec, root = project
        emit(spec, root)
        env = compose_of(root)["services"]["agent"]["environment"]
        assert env["POSTGRES_URI"].startswith("postgres://postgres:")
        assert "@postgres:5432/" in env["POSTGRES_URI"]

    def test_the_licensed_agent_gets_the_server_variables_instead(self, project):
        spec, root = project
        emit(spec, root, licensed=True)
        env = compose_of(root)["services"]["agent"]["environment"]
        assert "DATABASE_URI" in env and "REDIS_URI" in env

    def test_the_frontend_is_never_told_an_address(self, project):
        """The whole point: a service name, not a URL anyone has to maintain."""
        spec, root = project
        emit(spec, root)
        web = compose_of(root)["services"]["web"]
        assert web["environment"]["LANGGRAPH_API_URL"] == "http://agent:8000"

    @pytest.mark.parametrize("licensed", [False, True])
    def test_only_the_frontend_is_published(self, project, licensed):
        spec, root = project
        emit(spec, root, licensed=licensed)
        services = compose_of(root)["services"]
        assert services["web"]["ports"] == ["3000:3000"]
        for name, service in services.items():
            if name == "web":
                continue
            assert "ports" not in service, f"{name} must not be reachable from outside"

    def test_the_agent_is_reachable_only_internally(self, project):
        spec, root = project
        emit(spec, root)
        assert compose_of(root)["services"]["agent"]["expose"] == ["8000"]

    def test_the_frontend_waits_for_a_healthy_agent(self, project):
        spec, root = project
        emit(spec, root)
        depends = compose_of(root)["services"]["web"]["depends_on"]
        assert depends["agent"]["condition"] == "service_healthy"

    def test_the_agent_waits_for_its_databases(self, project):
        spec, root = project
        emit(spec, root, licensed=True)
        depends = compose_of(root)["services"]["agent"]["depends_on"]
        assert depends["postgres"]["condition"] == "service_healthy"
        assert depends["redis"]["condition"] == "service_healthy"

    def test_the_host_builds_the_agent_image(self, project):
        # Not a prebuilt image: a remote host must be able to build its own,
        # with no registry in the loop.
        spec, root = project
        emit(spec, root)
        build = compose_of(root)["services"]["agent"]["build"]
        assert build["dockerfile"] == "Dockerfile.agent"


class TestSecretsStaySecret:
    def test_the_api_key_is_never_public(self, project):
        spec, root = project
        emit(spec, root)
        web = compose_of(root)["services"]["web"]
        assert "LANGSMITH_API_KEY" in web["environment"]
        rendered = (root / "docker-compose.yml").read_text(encoding="utf-8")
        assert "NEXT_PUBLIC_LANGSMITH" not in rendered
        assert "NEXT_PUBLIC_API_KEY" not in rendered

    def test_public_values_are_build_args_not_runtime_env(self, project):
        """Next.js inlines NEXT_PUBLIC_* during `next build`.

        Supplying them only at run time leaves the browser with undefined
        values and drops the user on agent-chat-ui's setup form.
        """
        spec, root = project
        emit(spec, root)
        web = compose_of(root)["services"]["web"]
        assert web["build"]["args"]["NEXT_PUBLIC_API_URL"] == "/api"
        assert web["build"]["args"]["NEXT_PUBLIC_ASSISTANT_ID"] == "agent"
        assert not any(k.startswith("NEXT_PUBLIC_") for k in web["environment"])

    def test_secrets_are_never_uploaded(self):
        argv = rsync_project(Path("/tmp/p"), Remote("me@host", "~/p"))
        assert ENV_FILE in RSYNC_EXCLUDES
        assert "--exclude" in argv and ENV_FILE in argv

    def test_the_env_file_is_not_baked_into_the_image(self, project):
        spec, root = project
        emit(spec, root)
        assert ENV_FILE in (root / ".dockerignore").read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "value,missing",
        [("", True), ("change-me", True), ("   ", True), ("real-secret", False)],
    )
    def test_placeholders_count_as_unset(self, value, missing):
        env = {"POSTGRES_PASSWORD": value, "LANGSMITH_API_KEY": "k"}
        found = missing_secrets(env, None, licensed=True)
        assert ("POSTGRES_PASSWORD" in found) is missing

    def test_the_model_key_is_required_when_the_provider_needs_one(self):
        env = {"POSTGRES_PASSWORD": "p", "LANGSMITH_API_KEY": "k"}
        assert missing_secrets(env, "ANTHROPIC_API_KEY") == ["ANTHROPIC_API_KEY"]
        assert missing_secrets(env, None) == []

    def test_langsmith_is_not_required_by_the_default_stack(self):
        """Tracing is opt-in, and the in-memory server has no licence check."""
        env = {"OPENAI_API_KEY": "sk-real", "POSTGRES_PASSWORD": "pw"}
        assert missing_secrets(env, "OPENAI_API_KEY") == []

    def test_the_licensed_stack_demands_a_licence_of_some_kind(self):
        env = {"POSTGRES_PASSWORD": "p", "OPENAI_API_KEY": "sk-real"}
        gaps = missing_secrets(env, "OPENAI_API_KEY", licensed=True)
        assert any("LANGGRAPH_CLOUD_LICENSE_KEY" in g for g in gaps)
        # Either form satisfies it.
        assert missing_secrets(
            {**env, "LANGSMITH_API_KEY": "lsv2_real"}, "OPENAI_API_KEY", licensed=True
        ) == []

    def test_env_file_parsing_ignores_comments_and_blanks(self, tmp_path):
        path = tmp_path / ENV_FILE
        path.write_text('# a comment\n\nA=1\nB="quoted"\nnot-a-pair\n', encoding="utf-8")
        assert read_env_file(path) == {"A": "1", "B": "quoted"}


class TestComposeInvocation:
    def test_the_deploy_env_file_is_passed_explicitly(self):
        """Compose substitutes ${...} from `.env`, never from a service's
        env_file — and the project already has a `.env` for development."""
        assert compose_up(DOCKER)[:4] == [DOCKER, "compose", "--env-file", ENV_FILE]

    def test_up_waits_for_health(self):
        # Without --wait a broken deploy exits 0 and hands you a dead page.
        assert "--wait" in compose_up(DOCKER)

    def test_down_keeps_the_database_by_default(self):
        assert "--volumes" not in compose_down(DOCKER)
        assert "--volumes" in compose_down(DOCKER, volumes=True)

    def test_logs_can_follow_one_service(self):
        assert compose_logs(DOCKER, "agent", follow=True)[-3:] == ["logs", "-f", "agent"]


class TestRemote:
    def test_the_remote_uses_its_own_docker(self):
        """The local path is resolved for Windows; the host's PATH is right there."""
        argv = over_ssh(Remote("me@host", "~/app"), compose_up("C:\\Docker\\docker.exe"))
        assert argv[0] == "ssh" and argv[1] == "me@host"
        assert "docker compose" in argv[2]
        assert "C:\\Docker" not in argv[2]

    def test_commands_run_in_the_project_directory(self):
        argv = over_ssh(Remote("me@host", "~/app"), ["docker", "ps"])
        assert argv[2].startswith("cd ~/app && ")

    def test_the_home_path_still_expands(self):
        # Quoting ~ would create a directory literally named "~".
        assert "cd ~/app" in over_ssh(Remote("h", "~/app"), ["ls"])[2]

    def test_the_default_path_is_named_for_the_project(self):
        assert parse_remote("me@host", None, "demo-agent").path == "~/demo-agent"

    @pytest.mark.parametrize("bad", ["me@host; rm -rf /", "host && echo", "$(whoami)", "a b"])
    def test_shell_metacharacters_are_refused(self, bad):
        with pytest.raises(LangctlError):
            parse_remote(bad, None, "x")

    def test_build_output_never_travels(self):
        argv = rsync_project(Path("/tmp/p"), Remote("h", "~/p"))
        for heavy in ("node_modules", ".next", ".venv", ".git"):
            assert heavy in argv


class TestTls:
    def test_caddy_is_absent_without_a_domain(self, project):
        spec, root = project
        emit(spec, root)
        assert "caddy" not in compose_of(root)["services"]
        assert not (root / "Caddyfile").exists()

    def test_a_domain_adds_caddy_and_unpublishes_the_frontend(self, project):
        spec, root = project
        emit(spec, root, domain="agent.example.com")
        services = compose_of(root)["services"]
        assert services["caddy"]["ports"] == ["80:80", "443:443"]
        assert "ports" not in services["web"]
        assert (root / "Caddyfile").is_file()

    def test_the_token_stream_is_never_compressed(self, project):
        # Buffering SSE to compress it is what makes an agent appear to hang
        # and then answer all at once.
        spec, root = project
        emit(spec, root, domain="agent.example.com")
        caddyfile = (root / "Caddyfile").read_text(encoding="utf-8")
        assert "text/event-stream" in caddyfile
        assert "flush_interval -1" in caddyfile


class TestUserEditsSurvive:
    def test_a_tuned_compose_file_is_kept(self, project):
        spec, root = project
        emit(spec, root)
        (root / "docker-compose.yml").write_text("# mine\n", encoding="utf-8")
        result = emit(spec, root)
        assert (root / "docker-compose.yml").read_text(encoding="utf-8") == "# mine\n"
        assert any(p.name == "docker-compose.yml" for p in result.skipped)

    def test_force_regenerates(self, project):
        spec, root = project
        emit(spec, root)
        (root / "docker-compose.yml").write_text("# mine\n", encoding="utf-8")
        emit(spec, root, overwrite=True)
        assert "services:" in (root / "docker-compose.yml").read_text(encoding="utf-8")


class TestPorts:
    def test_the_published_port_is_configurable(self, project):
        spec, root = project
        emit(spec, root, web_host_port=8080)
        assert compose_of(root)["services"]["web"]["ports"] == ["8080:3000"]

    def test_the_container_port_never_changes(self, project):
        # The image sets PORT=3000; only the host side of the mapping moves.
        spec, root = project
        emit(spec, root, web_host_port=8080)
        assert compose_of(root)["services"]["web"]["environment"]["PORT"] == "3000"
