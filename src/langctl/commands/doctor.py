"""`langctl doctor` — check the environment before it fails mid-command."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..core.errors import MissingDependency
from ..core.health import describe_port_holder, is_port_free
from ..core.langgraph_cli import find_langgraph
from ..core.manifest import find_project_root
from ..core.spec import AgentSpec

console = Console()

OK, WARN, FAIL = "ok", "warn", "fail"

#: The langgraph CLI version we generate configs and flags against.
MIN_LANGGRAPH_CLI = (0, 4)


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""


def _version_of(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or result.stderr).strip().splitlines()[0]


def _tool(name: str, command: list[str], install: str, required: bool) -> Check:
    if shutil.which(name) is None:
        return Check(name, FAIL if required else WARN, "not found", install)
    return Check(name, OK, _version_of(command) or "installed")


def _langgraph_cli(project_root: Path | None = None) -> Check:
    # Must resolve the same way `dev` does — the project's venv first — or doctor
    # reports "not found" for a project that runs perfectly well.
    try:
        executable = find_langgraph(project_root) if project_root else None
    except MissingDependency:
        executable = None
    if executable is None:
        executable = shutil.which("langgraph")

    if executable is None:
        return Check(
            "langgraph-cli",
            FAIL,
            "not found",
            "Add it to the project: `uv add --dev 'langgraph-cli[inmem]'`, "
            "or install globally: `uv tool install 'langgraph-cli[inmem]'`.",
        )
    raw = _version_of([executable, "--version"]) or ""
    parts = raw.replace(",", " ").split()
    version = next((p for p in parts if p[:1].isdigit()), "?")
    try:
        numeric = tuple(int(x) for x in version.split(".")[:2])
    except ValueError:
        return Check("langgraph-cli", WARN, f"unrecognised version {raw!r}")
    if numeric < MIN_LANGGRAPH_CLI:
        return Check(
            "langgraph-cli",
            WARN,
            f"{version} is older than {'.'.join(map(str, MIN_LANGGRAPH_CLI))}",
            "uv tool upgrade langgraph-cli",
        )
    return Check("langgraph-cli", OK, version)


def _docker() -> Check:
    if shutil.which("docker") is None:
        return Check("docker", WARN, "not found", "Only needed for --docker and image builds.")
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=20)
    except subprocess.SubprocessError:
        return Check("docker", WARN, "not responding")
    if result.returncode != 0:
        return Check("docker", WARN, "installed but the daemon is not running", "Start Docker.")
    return Check("docker", OK, _version_of(["docker", "--version"]) or "running")


def _port(port: int, role: str) -> Check:
    if is_port_free(port):
        return Check(f"port {port}", OK, f"free ({role})")
    holder = describe_port_holder(port) or "unknown process"
    return Check(
        f"port {port}",
        WARN,
        f"in use by {holder}",
        "`langctl dev` will pick the next free port, or pass --strict-port to fail instead.",
    )


def _config_check(root: Path) -> Check:
    """Validate langgraph.json using the real CLI, which is the authority."""
    if not (root / "langgraph.json").is_file():
        return Check("langgraph.json", FAIL, "missing", "Run `langctl sync`.")
    try:
        langgraph = find_langgraph(root)
    except MissingDependency:
        return Check("langgraph.json", WARN, "present (cannot validate: no langgraph CLI)")

    result = subprocess.run([langgraph, "validate"], cwd=root, capture_output=True, text=True)
    if result.returncode == 0:
        return Check("langgraph.json", OK, "valid")
    return Check(
        "langgraph.json",
        FAIL,
        (result.stderr or result.stdout).strip().splitlines()[-1][:120],
        "Run `langctl sync`, then `langgraph validate`.",
    )


def _project_checks() -> list[Check]:
    try:
        root = find_project_root()
    except Exception:
        return [Check("project", WARN, "not inside an langctl project")]

    checks = [Check("project", OK, str(root))]
    try:
        spec = AgentSpec.load(root / "agent.yaml")
    except Exception as exc:
        checks.append(Check("agent.yaml", FAIL, str(exc).splitlines()[0], "Fix agent.yaml."))
        return checks

    checks.append(Check("agent.yaml", OK, f"{spec.name} ({spec.runtime}, mode={spec.mode})"))

    checks.append(_config_check(root))

    key = spec.model.api_key_env
    env_file = root / ".env"
    in_env_file = env_file.is_file() and any(
        line.strip().startswith(f"{key}=") and line.strip() != f"{key}="
        for line in env_file.read_text(encoding="utf-8").splitlines()
    )
    if os.getenv(key) or in_env_file:
        checks.append(Check(key, OK, "set"))
    else:
        checks.append(Check(key, FAIL, "not set", f"Add {key}=... to {env_file}"))

    web = root / "web"
    if spec.frontend.enabled and web.is_dir():
        checks.append(
            Check("frontend deps", OK, "installed")
            if (web / "node_modules").is_dir()
            else Check("frontend deps", FAIL, "node_modules missing", "cd web && npm install")
        )

    checks.append(_port(spec.backend.port, "agent"))
    if spec.frontend.enabled:
        checks.append(_port(spec.frontend.port, "web"))
    return checks


def doctor() -> None:
    """Check that this machine can build, run, and deploy agents."""
    try:
        project_root: Path | None = find_project_root()
    except Exception:
        project_root = None

    checks: list[Check] = [
        Check("python", OK, sys.version.split()[0]),
        _tool("uv", ["uv", "--version"], "curl -LsSf https://astral.sh/uv/install.sh | sh", False),
        _tool("node", ["node", "-v"], "https://nodejs.org (v20+)", False),
        _tool("npm", ["npm", "-v"], "ships with node", False),
        _langgraph_cli(project_root),
        _docker(),
        _tool("git", ["git", "--version"], "https://git-scm.com", False),
    ]
    checks += _project_checks()

    table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2))
    table.add_column("")
    table.add_column("check")
    table.add_column("detail", overflow="fold")

    glyph = {OK: "[green]✓[/green]", WARN: "[yellow]![/yellow]", FAIL: "[red]✗[/red]"}
    for check in checks:
        table.add_row(glyph[check.status], check.name, check.detail)
    console.print(table)

    problems = [c for c in checks if c.status != OK and c.fix]
    if problems:
        console.print("\n[bold]suggested fixes[/bold]")
        for check in problems:
            console.print(f"  [dim]{check.name}:[/dim] {check.fix}")

    if any(c.status == FAIL for c in checks):
        raise SystemExit(1)
