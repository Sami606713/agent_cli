"""Error text is data, not markup.

Rich reads `[...]` as a style tag. Every value langctl interpolates into an
error — shell commands, paths, upstream stderr — can contain brackets, and the
one that mattered was the hint telling you to install `langgraph-cli[inmem]`:
it rendered as `langgraph-cli`, so a user followed it, installed the bare
package, and `langgraph dev` failed with "Required package 'langgraph-api' is
not installed".
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from langctl.core.errors import LangctlError, MissingDependency
from langctl.core.runtime.langgraph_cli import INSTALL_HINT


def render(error: LangctlError) -> str:
    buffer = io.StringIO()
    # width: keep the panel from wrapping mid-token in the assertions below.
    error.render(Console(file=buffer, width=200, no_color=True))
    return buffer.getvalue()


class TestExtrasSurvive:
    def test_the_inmem_extra_is_printed(self):
        out = render(MissingDependency("langgraph", INSTALL_HINT))
        assert "langgraph-cli[inmem]" in out

    def test_the_hint_langctl_ships_actually_contains_it(self):
        # Guards the message itself, not just the renderer.
        assert "[inmem]" in INSTALL_HINT


class TestBracketsAreNeverStyles:
    @pytest.mark.parametrize(
        "text",
        [
            "package[extra]",
            "list[str] is not a dict[str, int]",
            "[bold red]not a style[/bold red]",
            "matched at line [42]",
        ],
    )
    def test_message_is_verbatim(self, text):
        assert text in render(LangctlError(text))

    @pytest.mark.parametrize("field", ["fix", "detail"])
    def test_every_field_is_escaped(self, field):
        error = LangctlError("boom", **{field: "run `pip install x[y]`"})
        assert "x[y]" in render(error)

    def test_upstream_stderr_cannot_break_the_panel(self):
        # A child's traceback is pasted in verbatim; an unclosed tag in it must
        # not raise while we are already reporting a failure.
        error = LangctlError("child failed", detail="Traceback [most recent call last]:\n  [/")
        assert "most recent call last" in render(error)
