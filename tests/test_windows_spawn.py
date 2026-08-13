"""Every spawned program must be a resolved path, never a bare name.

Reported from Windows:

    FileNotFoundError: [WinError 2] The system cannot find the file specified
      at subprocess.run([pm, "install"], ...)

npm, pnpm and npx install as `.cmd` shims on Windows. `CreateProcess` cannot
launch those from a bare name even though the shell can and `shutil.which`
finds them — the fix is to spawn what `which` returned, because it already
resolved the PATHEXT extension.

These tests are static: they read the source rather than spawning anything, so
they hold on Linux CI while protecting Windows users.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from langctl.core import executables

SRC = pathlib.Path(executables.__file__).parent.parent

#: Programs that are shims on Windows, or that we resolve for consistency.
SPAWNED = {"npm", "pnpm", "npx", "uv", "git", "docker", "node", "langgraph"}


def spawn_calls() -> list[tuple[pathlib.Path, ast.Call]]:
    """Every subprocess.run / subprocess.Popen call in the package."""
    found = []
    for path in SRC.rglob("*.py"):
        if "templates" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"run", "Popen"}:
                continue
            base = node.func.value
            if isinstance(base, ast.Name) and base.id == "subprocess":
                found.append((path, node))
    return found


class TestNoBareExecutables:
    def test_at_least_one_spawn_site_is_checked(self):
        # Guards against the walker silently matching nothing.
        assert len(spawn_calls()) >= 3

    @pytest.mark.parametrize("path,call", spawn_calls(), ids=lambda x: getattr(x, "name", ""))
    def test_argv_does_not_start_with_a_bare_program_name(self, path, call):
        if not call.args:
            return
        argv = call.args[0]
        if not isinstance(argv, ast.List) or not argv.elts:
            return  # built elsewhere; covered by the command-builder tests
        first = argv.elts[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            assert first.value not in SPAWNED, (
                f"{path.name}: spawns bare {first.value!r}; use "
                "executables.find()/require() so Windows .cmd shims resolve"
            )


class TestResolver:
    def test_find_returns_a_path_not_a_name(self):
        found = executables.find("python3") or executables.find("python")
        assert found and ("/" in found or "\\" in found)

    def test_find_returns_none_when_absent(self):
        assert executables.find("definitely-not-a-real-program-xyz") is None

    def test_require_names_the_install_hint(self):
        from langctl.core.errors import MissingDependency

        with pytest.raises(MissingDependency) as excinfo:
            executables.require("definitely-not-a-real-program-xyz")
        assert excinfo.value.fix

    def test_command_builds_argv_with_a_resolved_path(self):
        argv = executables.command("python3", "--version")
        if argv is not None:
            assert argv[0] != "python3"
            assert argv[1] == "--version"

    def test_command_is_none_when_missing(self):
        assert executables.command("definitely-not-a-real-program-xyz") is None

    def test_every_spawned_program_has_an_install_hint(self):
        # A missing tool should always say how to get it.
        for name in ("npm", "pnpm", "npx", "uv", "git", "docker"):
            assert name in executables.INSTALL_HINTS


class TestFrontendCommand:
    def test_uses_a_resolved_path(self, tmp_path):
        from langctl.commands.dev import _frontend_command
        from langctl.core.manifest import Project
        from langctl.core.spec import AgentSpec

        project = Project(root=tmp_path, spec=AgentSpec(name="demo-agent"))
        argv = _frontend_command(project, 3000)
        assert argv[0] not in {"npm", "pnpm"}, "must be the resolved path"
        assert "3000" in argv
