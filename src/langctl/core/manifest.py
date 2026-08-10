"""Project discovery and on-disk state.

Two files, with a firm split:

``agent.yaml``            user-owned, committed, human-edited. The spec.
``.langctl/state.json``  tool-owned, gitignored, machine-written. Deploy results.

Secrets go in neither — see :mod:`langctl.core.secrets`.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ProjectNotFound
from .spec import AgentSpec

SPEC_FILENAME = "agent.yaml"
STATE_DIR = ".langctl"
STATE_FILENAME = "state.json"


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from *start* looking for agent.yaml.

    Monorepos and `cd src/...` both depend on this, so no command should ever
    assume the process cwd is the project root.
    """
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / SPEC_FILENAME).is_file():
            return candidate
    raise ProjectNotFound(str(cur))


@dataclass
class Project:
    root: Path
    spec: AgentSpec

    @classmethod
    def load(cls, start: Path | None = None) -> Project:
        root = find_project_root(start)
        return cls(root=root, spec=AgentSpec.load(root / SPEC_FILENAME))

    # ---- well-known paths ----------------------------------------------

    @property
    def spec_path(self) -> Path:
        return self.root / SPEC_FILENAME

    @property
    def langgraph_config_path(self) -> Path:
        return self.root / "langgraph.json"

    @property
    def state_path(self) -> Path:
        return self.root / STATE_DIR / STATE_FILENAME

    @property
    def frontend_dir(self) -> Path:
        return self.root / "web"

    @property
    def env_file(self) -> Path:
        return self.root / ".env"

    # ---- state ----------------------------------------------------------

    def read_state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # A corrupt state file must never block a deploy: worst case we
            # re-discover the deployment by name.
            return {}

    def write_state(self, data: dict[str, Any]) -> None:
        """Atomically replace state.json.

        Atomic because a deploy interrupted mid-write would otherwise leave a
        truncated file, and `--resume` reads this to know what already exists.
        """
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**data, "updated_at": datetime.now(UTC).isoformat()}
        fd, tmp = tempfile.mkstemp(dir=self.state_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.state_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def update_state(self, **changes: Any) -> dict[str, Any]:
        state = self.read_state()
        state.update(changes)
        self.write_state(state)
        return state
