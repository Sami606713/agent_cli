"""`langctl add` — bringing a feature into an existing project.

The behaviour that matters is what happens to files that are already on disk.
A plain non-destructive render is wrong here: the template has *already*
produced a file for the old spec, so skipping it leaves the project pointing at
stale code — a langgraph.json promising persistence while store.py still returns
an in-memory store. Silent wrongness, not an error.
"""

from __future__ import annotations

import pytest

from langctl.core.render import plan_layers
from langctl.core.scaffold import backend_template, render_context, scaffold
from langctl.core.spec import AgentSpec
from langctl.core.spec_edit import has_comments, merge_section, register_tool
from langctl.core.tool_scaffold import module_name, symbol_name


def project(tmp_path, **memory) -> AgentSpec:
    spec = AgentSpec(
        name="demo-agent",
        frontend={"enabled": False, "kind": "none"},
        memory=memory or {"long_term": {"enabled": False}},
    )
    scaffold(spec, tmp_path)
    return spec


class TestRegeneration:
    """The core rule: regenerate what we generated, keep what the user changed."""

    def apply(self, tmp_path, old: AgentSpec, new: AgentSpec):
        before = plan_layers([backend_template(new)], tmp_path, render_context(old))
        after = plan_layers([backend_template(new)], tmp_path, render_context(new))
        written, skipped = [], []
        for path, content in sorted(after.items()):
            if path.exists():
                current = path.read_text()
                if current == content:
                    continue
                if current != before.get(path):
                    skipped.append(path)
                    continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            written.append(path)
        return written, skipped

    def test_stale_generated_file_is_regenerated(self, tmp_path):
        old = project(tmp_path)
        new = AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"})
        self.apply(tmp_path, old, new)
        # Without this, store.py would still yield InMemoryStore while
        # langgraph.json advertised a durable store.
        assert "SqliteStore" in (tmp_path / "src/demo_agent/memory/store.py").read_text()

    def test_memory_tools_get_registered(self, tmp_path):
        old = project(tmp_path)
        new = AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"})
        self.apply(tmp_path, old, new)
        assert "save_memory" in (tmp_path / "src/demo_agent/tools/__init__.py").read_text()

    def test_user_edited_file_is_preserved_and_reported(self, tmp_path):
        old = project(tmp_path)
        edited = tmp_path / "src/demo_agent/prompts/system.py"
        edited.write_text(edited.read_text() + "\n# my own note\n")

        new = AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"})
        _, skipped = self.apply(tmp_path, old, new)

        assert "# my own note" in edited.read_text()
        assert edited in skipped

    def test_unchanged_files_are_not_rewritten(self, tmp_path):
        spec = project(tmp_path, long_term={"enabled": True})
        written, skipped = self.apply(tmp_path, spec, spec)
        assert not written and not skipped


class TestSpecEdit:
    def test_merge_replaces_one_section_only(self, tmp_path):
        project(tmp_path)
        path = tmp_path / "agent.yaml"
        before = path.read_text()
        assert "name: demo-agent" in before

        changed, _ = merge_section(path, "memory", {"long_term": {"enabled": True}})
        assert changed
        text = path.read_text()
        assert "name: demo-agent" in text          # other sections survive
        assert "enabled: true" in text

    def test_merge_is_idempotent(self, tmp_path):
        project(tmp_path)
        path = tmp_path / "agent.yaml"
        value = {"long_term": {"enabled": True}}
        merge_section(path, "memory", value)
        changed, _ = merge_section(path, "memory", value)
        assert changed is False

    def test_comments_trigger_a_backup(self, tmp_path):
        project(tmp_path)
        path = tmp_path / "agent.yaml"
        path.write_text("# hand-written note\n" + path.read_text())
        assert has_comments(path.read_text())

        _, backup = merge_section(path, "memory", {"long_term": {"enabled": True}})
        # PyYAML cannot preserve comments, so the original must be recoverable.
        assert backup is not None and backup.is_file()
        assert "# hand-written note" in backup.read_text()

    def test_no_backup_when_there_is_nothing_to_lose(self, tmp_path):
        project(tmp_path)
        path = tmp_path / "agent.yaml"
        _, backup = merge_section(path, "memory", {"long_term": {"enabled": True}})
        assert backup is None


class TestToolRegistration:
    @pytest.mark.parametrize(
        "given,expected",
        [("lookup order", "lookup_order"), ("lookupOrder", "lookup_order"),
         ("Lookup-Order", "lookup_order"), ("2fa check", "tool_2fa_check")],
    )
    def test_names_are_normalised(self, given, expected):
        assert module_name(given) == expected
        assert symbol_name(given) == expected

    def test_empty_name_is_rejected(self):
        with pytest.raises(ValueError):
            module_name("!!!")

    def test_registers_import_and_list_entry(self, tmp_path):
        project(tmp_path, long_term={"enabled": True})
        registry = tmp_path / "src/demo_agent/tools/__init__.py"
        assert register_tool(registry, "lookup_order", "lookup_order")
        text = registry.read_text()
        assert "from demo_agent.tools.lookup_order import lookup_order" in text
        assert "    lookup_order," in text

    def test_second_registration_is_a_no_op(self, tmp_path):
        project(tmp_path, long_term={"enabled": True})
        registry = tmp_path / "src/demo_agent/tools/__init__.py"
        register_tool(registry, "lookup_order", "lookup_order")
        assert register_tool(registry, "lookup_order", "lookup_order") is False

    def test_restructured_registry_is_left_alone(self, tmp_path):
        """Guessing where to splice into rewritten code is worse than saying so."""
        project(tmp_path, long_term={"enabled": True})
        registry = tmp_path / "src/demo_agent/tools/__init__.py"
        registry.write_text("TOOLS = build_tools()\n")
        assert register_tool(registry, "lookup_order", "lookup_order") is False
        assert registry.read_text() == "TOOLS = build_tools()\n"
