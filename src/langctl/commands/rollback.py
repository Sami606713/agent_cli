"""`langctl rollback` — go back to a previously deployed version.

No rebuild: `deploy` already tagged that version's images when it shipped
them (see `core/deploy/version.py`), so rolling back is retagging them onto
`:latest` and restarting — the same images that ran before, not a fresh build
from the current working tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from ..core.deploy.targets import Remote, compose_restart, over_ssh, parse_remote
from ..core.deploy.version import (
    DeployRecord,
    deploy_history,
    image_exists,
    restore_tag,
    set_current,
)
from ..core.errors import LangctlError
from ..core.project.manifest import Project
from ..core.runtime.executables import require



def _run(argv: list[str], cwd: Path, what: str) -> None:
    result = subprocess.run(argv, cwd=cwd)
    if result.returncode != 0:
        raise LangctlError(f"{what} failed (exit {result.returncode})", fix="See the output above.")


def _quiet(argv: list[str]) -> bool:
    return (
        subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    )


def _find(history: list[DeployRecord], tag: str) -> DeployRecord:
    for record in history:
        if record.tag == tag:
            return record
    known = ", ".join(r.tag for r in history) or "(none recorded)"
    raise LangctlError(
        f"No recorded deploy tagged {tag!r}",
        fix=f"Run `langctl versions` to see what's available: {known}",
    )


def rollback(
    tag: str = typer.Argument(..., help="A tag from `langctl versions`."),
    host: str = typer.Option(
        None, "--host", help="ssh destination the stack runs on. Omit for this machine."
    ),
    remote_path: str = typer.Option(
        None, "--path", help="Directory on the remote host. Default: ~/<project>."
    ),
) -> None:
    """Retag a previous deploy's images onto `:latest` and restart. No rebuild."""
    project = Project.load()
    root, spec = project.root, project.spec

    history = deploy_history(project)
    record = _find(history, tag)

    remote: Remote | None = parse_remote(host, remote_path, spec.name) if host else None
    docker = require("docker")

    missing = [
        image
        for image in record.images
        if not _quiet(
            over_ssh(remote, image_exists(docker, image, tag))
            if remote
            else image_exists(docker, image, tag)
        )
    ]
    if missing:
        names = ", ".join(f"{image}:{tag}" for image in missing)
        plural = "s" if len(missing) > 1 else ""
        raise LangctlError(
            f"The image{plural} {names} {'are' if len(missing) > 1 else 'is'} "
            f"no longer on {'that host' if remote else 'this machine'}",
            fix=(
                "Docker prunes untagged and unused images over time. "
                "Redeploy from that commit instead of rolling back to it: "
                f"git checkout {tag.removesuffix('-dirty')} && langctl deploy"
            ),
        )

    console.print(f"[bold]rollback[/bold] [dim]→ {tag}[/dim]")
    for image in record.images:
        argv = restore_tag(docker, image, tag)
        _run(over_ssh(remote, argv) if remote else argv, root, f"docker tag ({image})")
        console.print(f"  [green]✓[/green] {image}:{tag} → {image}:latest")

    argv = compose_restart(docker)
    _run(over_ssh(remote, argv) if remote else argv, root, "docker compose up")
    set_current(project, tag)

    console.print(
        Panel(
            f"now running [bold]{tag}[/bold]\n[dim]no images were rebuilt[/dim]",
            title="[bold]rolled back[/bold]",
            border_style="green",
            title_align="left",
        )
    )
