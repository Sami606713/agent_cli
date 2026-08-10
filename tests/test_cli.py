"""CLI surface tests.

`--version` regressed because Click never invokes a group's callback when no
subcommand is given, making the flag unreachable. These lock the entry points.
"""

from typer.testing import CliRunner

from agentctl import __version__
from agentctl.main import cli

runner = CliRunner()


def test_version_flag_works_without_a_subcommand():
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_bare_invocation_shows_help_and_succeeds():
    result = runner.invoke(cli, [])
    assert result.exit_code == 0
    for command in ("new", "dev", "sync", "doctor"):
        assert command in result.output


def test_help_lists_every_command():
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for command in ("new", "dev", "sync", "doctor"):
        assert command in result.output


def test_dev_outside_a_project_explains_itself(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli, ["dev"])
    assert result.exit_code != 0
