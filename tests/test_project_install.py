"""Everything a project needs belongs to the project.

`langgraph dev` imports the agent in-process, so the Agent Server CLI has to
live in the project's own virtualenv. A global install resolves, satisfies
every naive check, and then cannot import the agent — which is exactly how one
user ended up with `uv tool install langgraph-cli` and a broken project.
"""

from __future__ import annotations

import sys

import pytest

from langctl.commands.new import _venv_has_langgraph
from langctl.core.errors import MissingDependency
from langctl.core.runtime.langgraph_cli import find_langgraph

BIN = "Scripts" if sys.platform == "win32" else "bin"
EXE = "langgraph.exe" if sys.platform == "win32" else "langgraph"


def make_venv(root, name=".venv"):
    path = root / name / BIN
    path.mkdir(parents=True)
    binary = path / EXE
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


class TestTheProjectVenvIsTheOnlyAnswer:
    def test_found_when_present(self, tmp_path):
        expected = make_venv(tmp_path)
        assert find_langgraph(tmp_path) == str(expected)

    def test_a_plain_venv_directory_also_counts(self, tmp_path):
        expected = make_venv(tmp_path, "venv")
        assert find_langgraph(tmp_path) == str(expected)

    def test_a_global_install_is_refused(self, tmp_path, monkeypatch):
        """The failure mode this whole module exists for."""
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/langgraph")
        with pytest.raises(MissingDependency) as caught:
            find_langgraph(tmp_path)
        assert "globally" in caught.value.fix
        # It must name the project-local fix, with the extra intact.
        assert "langgraph-cli[inmem]" in caught.value.fix

    def test_nothing_anywhere_asks_for_a_project_install(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _name: None)
        with pytest.raises(MissingDependency) as caught:
            find_langgraph(tmp_path)
        assert "langgraph-cli[inmem]" in caught.value.fix


class TestScaffoldVerifiesItsOwnWork:
    def test_reports_a_complete_environment(self, tmp_path):
        make_venv(tmp_path)
        assert _venv_has_langgraph(tmp_path) is True

    def test_reports_an_empty_one(self, tmp_path):
        (tmp_path / ".venv" / BIN).mkdir(parents=True)
        assert _venv_has_langgraph(tmp_path) is False

    def test_reports_no_venv_at_all(self, tmp_path):
        assert _venv_has_langgraph(tmp_path) is False
