"""Every chat UI must satisfy the same contract.

The three UIs differ only in `app/components/`. Everything that makes the
runtime work — the proxy route, the absolute apiUrl, the absence of secrets in
the client — has to hold identically for all of them, or `langctl dev` behaves
differently depending on a cosmetic choice.
"""

from __future__ import annotations

import json
import re

import pytest

from langctl.core.render import render_layers
from langctl.core.scaffold import frontend_templates, render_context, scaffold
from langctl.core.spec import PROXY_FRONTENDS, AgentSpec

UI_KINDS = sorted(PROXY_FRONTENDS)


def build(tmp_path, kind: str, **frontend) -> AgentSpec:
    spec = AgentSpec(name="demo-agent", frontend={"kind": kind, **frontend})
    scaffold(spec, tmp_path)
    return spec


@pytest.mark.parametrize("kind", UI_KINDS)
class TestEveryUi:
    def test_renders_the_shared_runtime_files(self, tmp_path, kind):
        build(tmp_path, kind)
        for rel in (
            "web/app/api/agent/[...path]/route.ts",
            "web/app/layout.tsx",
            "web/app/globals.css",
            "web/app/page.tsx",
            "web/app/components/Chat.tsx",
            "web/package.json",
            "web/tsconfig.json",
            "web/.gitignore",
        ):
            assert (tmp_path / rel).is_file(), f"{kind}: missing {rel}"

    def test_no_unrendered_jinja(self, tmp_path, kind):
        build(tmp_path, kind)
        for path in (tmp_path / "web").rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                assert "{%" not in text, f"{kind}: jinja block left in {path.name}"
                assert "{{ " not in text, f"{kind}: jinja expression left in {path.name}"

    def test_no_jinja_ate_a_jsx_brace(self, tmp_path, kind):
        """JSX `{{ … }}` inside a .j2 template is parsed as a Jinja tuple.

        StrictUndefined does not catch this: a tuple of undefined values
        stringifies to "(Undefined, Undefined)" instead of raising, so the only
        signal is the literal in the output. This bit the assistant-ui template.
        """
        build(tmp_path, kind)
        for path in (tmp_path / "web").rglob("*.tsx"):
            # Comments may legitimately mention the failure mode; only executable
            # code containing it indicates a swallowed brace.
            code = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
            code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
            assert "Undefined" not in code, f"{kind}: jinja swallowed a JSX brace in {path.name}"

    def test_api_url_is_absolute(self, tmp_path, kind):
        # A relative apiUrl throws "Failed to construct 'URL'" in the SDK.
        chat = (tmp_path / "web/app/components/Chat.tsx") if build(tmp_path, kind) else None
        text = chat.read_text()
        assert "window.location.origin" in text
        assert 'typeof window === "undefined"' in text

    def test_no_secret_is_exposed_to_the_browser(self, tmp_path, kind):
        build(tmp_path, kind)
        for path in (tmp_path / "web").rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                assert "NEXT_PUBLIC_LANGSMITH" not in text
                assert "NEXT_PUBLIC_ANTHROPIC" not in text
                assert "NEXT_PUBLIC_OPENAI" not in text

    def test_package_json_is_valid_and_named(self, tmp_path, kind):
        build(tmp_path, kind)
        pkg = json.loads((tmp_path / "web/package.json").read_text())
        assert pkg["name"] == "demo-agent-web"
        assert "@langchain/react" in pkg["dependencies"]

    def test_proxy_route_follows_the_prefix(self, tmp_path, kind):
        build(tmp_path, kind, proxy_prefix="/api/llm")
        assert (tmp_path / "web/app/api/llm/[...path]/route.ts").is_file()
        assert not (tmp_path / "web/app/api/agent").exists()


class TestNoCustomCss:
    """No hand-written CSS in any template — Tailwind utilities or @theme tokens.

    Enforced rather than documented, because a stylesheet grows one rule at a
    time and nobody notices until it is 300 lines.
    """

    SELECTOR = re.compile(r"^[^@\s/][^{]*\{", re.M)

    @pytest.mark.parametrize("kind", UI_KINDS)
    def test_css_contains_no_rule_blocks(self, tmp_path, kind):
        build(tmp_path, kind)
        for css in (tmp_path / "web").rglob("*.css"):
            body = css.read_text()
            # Strip comments and @theme/@layer token blocks, then assert nothing
            # that looks like `selector { … }` remains.
            stripped = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
            stripped = re.sub(r"@theme[^{]*\{.*?\n\}", "", stripped, flags=re.S)
            leftover = self.SELECTOR.findall(stripped)
            assert not leftover, f"{kind}: custom CSS rule(s) in {css.name}: {leftover}"

    @pytest.mark.parametrize("kind", UI_KINDS)
    def test_tailwind_is_imported(self, tmp_path, kind):
        build(tmp_path, kind)
        assert '@import "tailwindcss"' in (tmp_path / "web/app/globals.css").read_text()

    def test_minimal_and_assistant_ui_ship_a_one_line_stylesheet(self, tmp_path):
        for kind in ("nextjs_minimal", "nextjs_assistant_ui"):
            target = tmp_path / kind
            build(target, kind)
            css = (target / "web/app/globals.css").read_text().strip()
            assert css == '@import "tailwindcss";', f"{kind} should need no tokens"


class TestLayering:
    def test_shared_layer_is_listed_first(self):
        layers = frontend_templates(AgentSpec(name="demo-agent"))
        assert layers[0] == "frontend/_shared"
        assert layers[1].startswith("frontend/nextjs_")

    def test_disabled_frontend_has_no_layers(self):
        spec = AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"})
        assert frontend_templates(spec) == []

    def test_proxy_route_is_byte_identical_across_uis(self, tmp_path):
        """Proves the route really is shared, not three copies that drifted."""
        contents = set()
        for kind in UI_KINDS:
            target = tmp_path / kind
            build(target, kind)
            contents.add((target / "web/app/api/agent/[...path]/route.ts").read_text())
        assert len(contents) == 1

    def test_ui_layer_overrides_shared_files(self, tmp_path):
        # nextjs_ai_elements replaces globals.css to add its design tokens.
        build(tmp_path, "nextjs_ai_elements")
        assert "@theme" in (tmp_path / "web/app/globals.css").read_text()

    def test_layers_do_not_clobber_user_files(self, tmp_path):
        """`langctl add` must never destroy an edited file, even on the top layer."""
        spec = AgentSpec(name="demo-agent", frontend={"kind": "nextjs_ai_elements"})
        web = tmp_path / "web"
        web.mkdir(parents=True)
        (web / "app").mkdir()
        (web / "app" / "globals.css").write_text("/* mine */\n")

        result = render_layers(
            frontend_templates(spec), web, render_context(spec), overwrite=False
        )
        assert (web / "app" / "globals.css").read_text() == "/* mine */\n"
        assert any(p.name == "globals.css" for p in result.skipped)


class TestAssistantUi:
    def test_ships_the_converter(self, tmp_path):
        build(tmp_path, "nextjs_assistant_ui")
        assert (tmp_path / "web/app/components/lc-runtime.ts").is_file()

    def test_depends_on_assistant_ui(self, tmp_path):
        build(tmp_path, "nextjs_assistant_ui")
        deps = json.loads((tmp_path / "web/package.json").read_text())["dependencies"]
        assert "@assistant-ui/react" in deps

    def test_does_not_import_the_removed_thread_component(self, tmp_path):
        # `Thread` is not exported by @assistant-ui/react 0.15; the docs example
        # is stale. We compose primitives instead.
        build(tmp_path, "nextjs_assistant_ui")
        chat = (tmp_path / "web/app/components/Chat.tsx").read_text()
        assert "ThreadPrimitive" in chat
        assert not re.search(r"import \{[^}]*\bThread\b[^}]*\} from \"@assistant-ui/react\"", chat)

    def test_does_not_use_the_stale_styled_package(self, tmp_path):
        build(tmp_path, "nextjs_assistant_ui")
        deps = json.loads((tmp_path / "web/package.json").read_text())["dependencies"]
        assert "@assistant-ui/react-ui" not in deps


class TestAiElements:
    def test_ships_shadcn_prerequisites(self, tmp_path):
        """So the registry CLI never runs against an uninitialised project."""
        build(tmp_path, "nextjs_ai_elements")
        assert (tmp_path / "web/components.json").is_file()
        assert (tmp_path / "web/lib/utils.ts").is_file()

    def test_component_aliases_match_the_imports(self, tmp_path):
        build(tmp_path, "nextjs_ai_elements")
        aliases = json.loads((tmp_path / "web/components.json").read_text())["aliases"]
        chat = (tmp_path / "web/app/components/Chat.tsx").read_text()
        assert aliases["components"] == "@/components"
        assert "@/components/ai-elements/" in chat

    def test_tokens_cover_the_classes_the_components_use(self, tmp_path):
        build(tmp_path, "nextjs_ai_elements")
        css = (tmp_path / "web/app/globals.css").read_text()
        for token in ("--color-background", "--color-foreground", "--color-muted-foreground",
                      "--color-border", "--color-primary"):
            assert token in css

    def test_chat_explains_how_to_recover_from_a_failed_fetch(self, tmp_path):
        build(tmp_path, "nextjs_ai_elements")
        chat = (tmp_path / "web/app/components/Chat.tsx").read_text()
        assert "ai-elements@latest add" in chat


class TestLegacyKinds:
    @pytest.mark.parametrize("legacy", ["nextjs_proxy", "vite_proxy"])
    def test_old_names_still_load(self, legacy):
        spec = AgentSpec.from_yaml(f"name: x-y\nfrontend:\n  kind: {legacy}\n")
        assert spec.frontend.kind == "nextjs_minimal"

    def test_default_is_assistant_ui(self):
        assert AgentSpec(name="x-y").frontend.kind == "nextjs_assistant_ui"
