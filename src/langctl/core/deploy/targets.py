"""Where a stack runs, and the argv that puts it there.

Two targets, one artefact. `local` brings the compose stack up on this machine;
`ssh` copies the project to a host you own and brings the identical stack up
there. Neither splits the app across providers: the frontend and the agent go
up together or not at all.

Everything here builds argv rather than running it, so the wiring is testable
without Docker, a network, or a host.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..errors import LangctlError

#: user@host, a hostname, or an ssh_config alias — all three are things people
#: legitimately pass. Rejecting shell metacharacters is the actual job here,
#: since this value ends up inside a remote command string.
_SSH_TARGET = re.compile(r"^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9._-]+$")

#: Compose substitutes ${...} from the shell or from `.env` in the project
#: directory — never from a service's `env_file`. The project already has a
#: `.env` for development, so deployment secrets are passed explicitly.
ENV_FILE = ".env.deploy"

#: Checked before anything is built. Discovering a missing key after a
#: ten-minute image build is a bad way to find out.
REQUIRED_SECRETS = ("POSTGRES_PASSWORD", "LANGSMITH_API_KEY")

#: Values shipped in the example file that are not real secrets.
PLACEHOLDERS = frozenset({"", "change-me"})

#: Without this the Agent Server still starts, using the LangSmith API key, but
#: production use of a self-hosted server that way is outside LangChain's
#: licence terms. langctl warns rather than blocks: whether a given deployment
#: is "production" is not ours to decide, and staging on your own box is
#: legitimate.
LICENCE_KEY = "LANGGRAPH_CLOUD_LICENSE_KEY"

#: Never uploaded, never baked into an image.
RSYNC_EXCLUDES = (
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".next",
    "__pycache__",
    ".langgraph_api",
    "data",
    ".env",
    ENV_FILE,
    "*.sqlite",
)


@dataclass(frozen=True)
class Remote:
    """An ssh destination and where the project lives on it."""

    destination: str
    path: str

    @property
    def host(self) -> str:
        """The address part, for building the URL to print at the end."""
        return self.destination.rpartition("@")[2]


def parse_remote(destination: str, path: str | None, project_name: str) -> Remote:
    if not _SSH_TARGET.fullmatch(destination):
        raise LangctlError(
            f"Not a usable ssh destination: {destination!r}",
            fix="Pass user@host, a hostname, or a ~/.ssh/config alias.",
        )
    return Remote(destination, path or f"~/{project_name}")


# ---- langgraph -----------------------------------------------------------


def write_agent_dockerfile(langgraph: str, out: Path) -> list[str]:
    """`langgraph dockerfile` argv.

    The agent's Dockerfile is generated rather than templated because
    langgraph.json is the only thing that knows the base image, the Python
    version and the dependency set. A hand-maintained copy would drift on the
    first upgrade. It is written to a real file so it can be read and edited.
    """
    return [langgraph, "dockerfile", str(out)]


# ---- compose -------------------------------------------------------------


def compose(docker: str, *args: str) -> list[str]:
    """`docker compose --env-file .env.deploy ...`.

    *docker* is a resolved path rather than a bare name: on Windows docker is a
    .cmd shim that CreateProcess cannot launch by name.
    """
    return [docker, "compose", "--env-file", ENV_FILE, *args]


def compose_build(docker: str) -> list[str]:
    return compose(docker, "build")


def compose_up(docker: str) -> list[str]:
    # --wait blocks until every healthcheck passes, which turns a failed start
    # into a non-zero exit here rather than a browser tab that never loads.
    return compose(docker, "up", "-d", "--build", "--wait")


def compose_down(docker: str, volumes: bool = False) -> list[str]:
    return compose(docker, "down", *(["--volumes"] if volumes else []))


def compose_logs(docker: str, service: str | None = None, follow: bool = False) -> list[str]:
    args = ["logs"]
    if follow:
        args.append("-f")
    if service:
        args.append(service)
    return compose(docker, *args)


def compose_ps(docker: str) -> list[str]:
    return compose(docker, "ps", "--format", "json")


# ---- remote --------------------------------------------------------------


def over_ssh(remote: Remote, argv: list[str]) -> list[str]:
    """Run *argv* inside the project directory on the remote host."""
    # The remote is a POSIX host, where a bare `docker` on PATH is right — even
    # though locally we had to resolve it to an absolute path for Windows.
    #
    # The basename is taken by hand rather than with pathlib: a Windows path
    # like C:\Docker\docker.exe is a single opaque name to PosixPath, so a
    # Windows user would otherwise ship their local path to a Linux host.
    if argv and _basename(argv[0]) in ("docker", "docker.exe"):
        argv = ["docker", *argv[1:]]
    quoted = " ".join(shell_quote(a) for a in argv)
    return ["ssh", remote.destination, f"cd {shell_quote(remote.path)} && {quoted}"]


def rsync_project(local_root: Path, remote: Remote) -> list[str]:
    """Copy the project up, minus everything that must not travel.

    `.env.deploy` is excluded deliberately: secrets are placed on the host once,
    by you, and are not re-uploaded on every deploy. Build outputs and
    virtualenvs are excluded because they are host-specific and large.
    """
    argv = ["rsync", "-az", "--delete"]
    for pattern in RSYNC_EXCLUDES:
        argv += ["--exclude", pattern]
    # Trailing slashes: copy the *contents* of the project into the target.
    return argv + [f"{local_root}/", f"{remote.destination}:{remote.path}/"]


def remote_mkdir(remote: Remote) -> list[str]:
    return ["ssh", remote.destination, f"mkdir -p {shell_quote(remote.path)}"]


def remote_has_env_file(remote: Remote) -> list[str]:
    """Exits 0 when .env.deploy already exists on the host."""
    return ["ssh", remote.destination, f"test -f {shell_quote(remote.path + '/' + ENV_FILE)}"]


# ---- secrets -------------------------------------------------------------


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file well enough to tell whether a value is set."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def missing_secrets(env: dict[str, str], model_key_env: str | None) -> list[str]:
    """Required values that are absent, empty, or still the placeholder."""
    required = [*REQUIRED_SECRETS]
    if model_key_env:
        required.append(model_key_env)
    return [key for key in required if env.get(key, "").strip() in PLACEHOLDERS]


def shell_quote(arg: str) -> str:
    # ~ is left unquoted on purpose: the remote path defaults to ~/<project>
    # and must expand on the host.
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./~-]+", arg):
        return arg
    return "'" + arg.replace("'", "'\\''") + "'"


def _basename(path: str) -> str:
    """Last segment of a path using either separator.

    Neither PurePosixPath nor PureWindowsPath alone is right here: the value
    comes from whichever platform langctl is running on, and is consumed by a
    POSIX host.
    """
    return path.replace("\\", "/").rsplit("/", 1)[-1]
