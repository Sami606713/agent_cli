"""Tagging deploy images by commit, so a deploy can be rolled back to.

`docker-compose.yml` always builds and runs `:latest` — regenerating it on
every deploy to reference a fresh tag is not an option, because `deploy` never
rewrites a stack file that already exists (that is what protects a tuned
compose file from being clobbered on the next run). So versioning happens
outside the compose file entirely: every image a deploy builds is tagged
twice — `:latest`, which is what the stack runs, and `:<tag>`, a snapshot the
next build never touches. `rollback` retags an old snapshot back onto
`:latest` and restarts, with no rebuild and no compose file to regenerate.

History lives in `.langctl/state.json` via the plain read/write helpers
`Project` already exposes — this module only decides what a tag is and builds
the `docker tag` argv, in the same style as `targets.py`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..project.manifest import Project
from ..runtime.executables import find as find_executable
from ..runtime.process import TEXT_IO


def _git(root: Path, *args: str) -> str | None:
    # Resolved to a path rather than the bare name: on Windows `git` is
    # sometimes a shim `CreateProcess` cannot launch from the name alone.
    git = find_executable("git")
    if git is None:
        return None
    try:
        result = subprocess.run([git, *args], cwd=root, capture_output=True, timeout=5, **TEXT_IO)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def git_sha(root: Path) -> str | None:
    """Short commit hash for *root*, or None outside a git repo."""
    return _git(root, "rev-parse", "--short", "HEAD") or None


def is_dirty(root: Path) -> bool:
    """True when the working tree has uncommitted changes."""
    return bool(_git(root, "status", "--porcelain"))


def deploy_tag(root: Path) -> str:
    """A tag identifying this deploy.

    The commit hash when *root* is a git repo, marked `-dirty` when the
    working tree does not match it — a version list must never imply that
    checking out a commit reproduces what was actually shipped. A timestamp
    outside git, since nothing else identifies the code that was built.
    """
    sha = git_sha(root)
    if sha is None:
        return f"untracked-{datetime.now(UTC):%Y%m%d%H%M%S}"
    return f"{sha}-dirty" if is_dirty(root) else sha


def tag_image(docker: str, image: str, tag: str) -> list[str]:
    """`docker tag <image>:latest <image>:<tag>` — snapshot a just-built image."""
    return [docker, "tag", f"{image}:latest", f"{image}:{tag}"]


def restore_tag(docker: str, image: str, tag: str) -> list[str]:
    """`docker tag <image>:<tag> <image>:latest` — the rollback move."""
    return [docker, "tag", f"{image}:{tag}", f"{image}:latest"]


def image_exists(docker: str, image: str, tag: str) -> list[str]:
    """`docker image inspect <image>:<tag>` argv; exit 0 means it is still on disk."""
    return [docker, "image", "inspect", f"{image}:{tag}"]


@dataclass(frozen=True)
class DeployRecord:
    """One row of deploy history — a data shape, not a service."""

    tag: str
    at: str
    images: tuple[str, ...]

    @property
    def dirty(self) -> bool:
        return self.tag.endswith("-dirty")


def deploy_history(project: Project) -> list[DeployRecord]:
    """Every recorded deploy, oldest first. Empty for a project never deployed
    through this code path — including anything deployed before this feature."""
    raw = project.read_state().get("deploys", [])
    return [
        DeployRecord(tag=entry["tag"], at=entry["at"], images=tuple(entry["images"]))
        for entry in raw
        if "tag" in entry and "at" in entry and "images" in entry
    ]


def current_tag(project: Project) -> str | None:
    return project.read_state().get("current")


def record_deploy(project: Project, tag: str, images: list[str]) -> None:
    """Append a deploy to history and mark it current."""
    history = deploy_history(project)
    history.append(DeployRecord(tag=tag, at=datetime.now(UTC).isoformat(), images=tuple(images)))
    project.update_state(
        deploys=[{"tag": r.tag, "at": r.at, "images": list(r.images)} for r in history],
        current=tag,
    )


def set_current(project: Project, tag: str) -> None:
    """Record that *tag* is what the stack now runs, without adding history —
    what `rollback` does, since it did not build anything new."""
    project.update_state(current=tag)
