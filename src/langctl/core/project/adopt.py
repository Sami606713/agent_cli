"""Adopting an existing LangGraph project into langctl.

`init` is `new` in reverse: instead of generating a project from a spec, it
infers a spec from a project that already exists. It writes exactly one file
— `agent.yaml` — and never touches source code, so running it is always safe
to undo: delete the file and nothing happened.

The one landmine worth stating up front: `langctl sync`/`dev`/`deploy` always
regenerate `langgraph.json`'s `graphs` key to point at
`./src/<package>/agent.py:graph` — that path is *owned*, not merged, because
it is how a scaffolded project's layout is guaranteed. Adopting a project
whose graph lives somewhere else does not move it or rewrite langgraph.json;
it records what `ProjectAdopter.infer()` found so the mismatch is a decision
the caller makes deliberately, not something it discovers on the next `sync`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..catalog.models import PROVIDERS
from ..errors import LangctlError
from .manifest import SPEC_FILENAME
from .spec import AgentSpec, FrontendSpec, ModelSpec, slugify


@dataclass
class Findings:
    """What could be worked out from the project on disk, and how."""

    name: str
    name_source: str
    graph_id: str | None = None
    graph_target: str | None = None
    graph_path_is_conventional: bool = True
    provider: str | None = None
    provider_source: str | None = None

    @property
    def expected_graph_target(self) -> str:
        return f"./src/{self.name.replace('-', '_')}/agent.py:graph"


class ProjectAdopter:
    """Reads an existing project, infers a spec, and writes `agent.yaml`.

    Three steps, one per method, run in order by the caller so it can prompt
    between them: `detect()` reads what is on disk, `infer()` turns that into
    `Findings`, `build_spec()` and `write()` turn findings plus whatever the
    caller decided into the one file this ever creates.
    """

    def __init__(self, root: Path):
        self.root = root
        self.langgraph_config: dict | None = None
        self.pyproject_text: str | None = None

    # ---- detect -----------------------------------------------------------

    def detect(self) -> None:
        """Read whatever configuration already exists. Never writes anything."""
        langgraph_path = self.root / "langgraph.json"
        if langgraph_path.is_file():
            try:
                self.langgraph_config = json.loads(langgraph_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise LangctlError(
                    "langgraph.json exists but is not valid JSON",
                    fix=f"Fix the syntax error, then run `langctl init` again: {exc}",
                ) from exc

        pyproject_path = self.root / "pyproject.toml"
        if pyproject_path.is_file():
            self.pyproject_text = pyproject_path.read_text(encoding="utf-8")

    @property
    def already_a_langctl_project(self) -> bool:
        return (self.root / SPEC_FILENAME).is_file()

    @property
    def found_langgraph_config(self) -> bool:
        return self.langgraph_config is not None

    # ---- infer --------------------------------------------------------------

    def infer(self) -> Findings:
        """Best-guess `Findings`. Never raises for an ordinary "could not tell"
        — that is what the caller's prompts are for; this only raises for
        configuration that is actually broken, which `detect()` already did."""
        name, name_source = self._infer_name()
        findings = Findings(name=name, name_source=name_source)

        graphs = (self.langgraph_config or {}).get("graphs") or {}
        if graphs:
            graph_id, target = next(iter(graphs.items()))
            findings.graph_id = graph_id
            findings.graph_target = target
            findings.graph_path_is_conventional = target == findings.expected_graph_target

        provider = self._infer_provider()
        if provider is not None:
            findings.provider, findings.provider_source = provider

        return findings

    def _infer_name(self) -> tuple[str, str]:
        """A name `AgentSpec` will accept, from whatever source supplied it.

        Neither source is guaranteed to satisfy `NAME_PATTERN` on its own — a
        PyPI project name may contain underscores, and a directory name can be
        anything the filesystem allows — so both are slugified here rather
        than handed to `AgentSpec` raw, which would surface as a bare pydantic
        `ValidationError` instead of an adoption that just works.
        """
        if self.pyproject_text:
            match = re.search(r'(?m)^name\s*=\s*"([^"]+)"', self.pyproject_text)
            if match:
                return slugify(match.group(1)), "pyproject.toml"
        return slugify(self.root.name), "directory name"

    def _infer_provider(self) -> tuple[str, str] | None:
        """Match an installed `langchain-*` package back to a known provider.

        Ambiguous on purpose rather than wrong: several providers share a
        package (`azure_openai` and `openai` both install `langchain-openai`),
        so this is a starting guess for the caller to confirm, not a fact.
        """
        if not self.pyproject_text:
            return None
        from ..generate.pyproject import current_dependencies

        installed = {
            re.split(r"[<>=\[]", dep, maxsplit=1)[0].strip()
            for dep in current_dependencies(self.pyproject_text) or []
        }
        for key, provider in PROVIDERS.items():
            if provider.package and provider.package.split(">")[0].split("[")[0] in installed:
                return key, provider.package
        return None

    # ---- build + write ------------------------------------------------------

    def build_spec(self, findings: Findings, *, provider: str, model: str | None) -> AgentSpec:
        """An `AgentSpec` from `findings` plus whatever the caller decided.

        Long-term memory and the frontend default off: both, once enabled,
        make `langgraph.json` reference generated files (`memory/store.py`,
        `web/`) this class never writes. `langctl add memory` / `add frontend`
        are what create them — this only ever records the model and the name.
        """
        model_spec = (
            ModelSpec(provider=provider, name=model) if model else ModelSpec(provider=provider)
        )
        spec = AgentSpec(
            name=findings.name,
            model=model_spec,
            frontend=FrontendSpec(enabled=False, kind="none"),
        )
        # AgentSpec's long-term memory defaults to enabled; adoption must not
        # inherit that, for the reason in the docstring above.
        memory = spec.memory.model_dump()
        memory["long_term"]["enabled"] = False
        return spec.model_copy(update={"memory": type(spec.memory)(**memory)})

    def write(self, spec: AgentSpec) -> Path:
        path = self.root / SPEC_FILENAME
        if path.exists():
            raise LangctlError(
                f"{SPEC_FILENAME} already exists",
                fix="This project is already a langctl project.",
            )
        spec.save(path)
        return path
