"""The chat UI is vendored from langchain-ai/agent-chat-ui.

The application source is copied unmodified — these tests exist to pin the two
things langctl is responsible for: that the vendored tree arrives intact, and
that the setup screen is never reached because both env values are pre-filled.
The screen is not deleted; deleting it would fork the upstream source and make
every future re-sync a merge.
"""

from __future__ import annotations

import json

import pytest

from langctl.core.generate.render import render_layers
from langctl.core.generate.scaffold import frontend_templates, render_context, scaffold
from langctl.core.project.spec import LEGACY_FRONTEND_KINDS, AgentSpec


def build(tmp_path, **frontend) -> AgentSpec:
    spec = AgentSpec(name="demo-agent", frontend=frontend or None) if frontend else AgentSpec(
        name="demo-agent"
    )
    scaffold(spec, tmp_path)
    return spec


class TestVendoredTree:
    def test_the_application_is_present(self, tmp_path):
        build(tmp_path)
        for rel in (
            "web/package.json",
            "web/src/app/page.tsx",
            "web/src/app/layout.tsx",
            "web/src/providers/Stream.tsx",
            "web/src/providers/Thread.tsx",
            "web/src/components/thread/index.tsx",
            "web/src/app/api/[..._path]/route.ts",
            "web/tsconfig.json",
            "web/tailwind.config.js",
        ):
            assert (tmp_path / rel).is_file(), f"missing {rel}"

    def test_agent_inbox_survives(self, tmp_path):
        # The human-in-the-loop review UI is the most substantial part of the
        # upstream app; a partial copy would silently drop it.
        build(tmp_path)
        inbox = tmp_path / "web/src/components/thread/agent-inbox"
        assert inbox.is_dir()
        assert len(list(inbox.rglob("*.tsx"))) >= 5

    def test_upstream_licence_is_kept(self, tmp_path):
        build(tmp_path)
        licence = (tmp_path / "web/LICENSE").read_text()
        assert "MIT" in licence

    def test_provenance_is_recorded(self, tmp_path):
        # A vendored copy without its source commit cannot be re-synced.
        build(tmp_path)
        note = (tmp_path / "web/VENDORED.md").read_text()
        assert "agent-chat-ui" in note
        assert "Commit:" in note

    def test_source_is_unmodified(self, tmp_path):
        """Only package.json is templated; the app code is byte-identical."""
        build(tmp_path)
        stream = (tmp_path / "web/src/providers/Stream.tsx").read_text()
        assert "{{" not in stream and "{%" not in stream
        # The setup screen is still in the source — bypassed, not removed.
        assert "Welcome to Agent Chat" in stream


class TestSetupScreenIsBypassed:
    """It renders only when an env value is missing:

        if (!finalApiUrl || !finalAssistantId) { ...form... }
    """

    def test_both_values_are_pre_filled(self, tmp_path):
        build(tmp_path)
        env = (tmp_path / "web/.env.example").read_text()
        assert "NEXT_PUBLIC_API_URL=/api" in env
        assert "NEXT_PUBLIC_ASSISTANT_ID=agent" in env

    def test_passthrough_target_points_at_the_agent(self, tmp_path):
        build(tmp_path, kind="agent_chat_ui", port=3000)
        env = (tmp_path / "web/.env.example").read_text()
        assert "LANGGRAPH_API_URL=http://127.0.0.1:2024" in env

    def test_backend_port_is_honoured(self, tmp_path):
        spec = AgentSpec(name="demo-agent", ports={"agent": 2500})
        scaffold(spec, tmp_path)
        assert "LANGGRAPH_API_URL=http://127.0.0.1:2500" in (
            tmp_path / "web/.env.example"
        ).read_text()

    def test_the_api_key_is_never_public(self, tmp_path):
        build(tmp_path)
        env = (tmp_path / "web/.env.example").read_text()
        assert "LANGSMITH_API_KEY=" in env
        assert "NEXT_PUBLIC_LANGSMITH" not in env


class TestPackageJson:
    def test_named_for_the_project(self, tmp_path):
        build(tmp_path)
        assert json.loads((tmp_path / "web/package.json").read_text())["name"] == "demo-agent-web"

    def test_dev_and_start_bind_the_configured_port(self, tmp_path):
        spec = AgentSpec(name="demo-agent", frontend={"port": 4321})
        scaffold(spec, tmp_path)
        scripts = json.loads((tmp_path / "web/package.json").read_text())["scripts"]
        assert "--port 4321" in scripts["dev"]
        assert "--port 4321" in scripts["start"]

    def test_upstream_dependencies_are_intact(self, tmp_path):
        build(tmp_path)
        deps = json.loads((tmp_path / "web/package.json").read_text())["dependencies"]
        assert "langgraph-nextjs-api-passthrough" in deps
        assert "@langchain/langgraph-sdk" in deps


class TestTemplateLayers:
    def test_a_single_self_contained_layer(self):
        # agent-chat-ui brings its own passthrough, layout and build config, so
        # there is no shared layer to stack beneath it.
        assert frontend_templates(AgentSpec(name="demo-agent")) == ["frontend/agent_chat_ui"]

    def test_disabled_frontend_renders_nothing(self):
        spec = AgentSpec(name="demo-agent", frontend={"enabled": False, "kind": "none"})
        assert frontend_templates(spec) == []
        
    def test_no_frontend_directory_when_disabled(self, tmp_path):
        build(tmp_path, enabled=False, kind="none")
        assert not (tmp_path / "web").exists()

    def test_user_edits_are_never_clobbered(self, tmp_path):
        spec = AgentSpec(name="demo-agent")
        web = tmp_path / "web"
        (web / "src" / "app").mkdir(parents=True)
        (web / "src" / "app" / "page.tsx").write_text("// mine\n")

        result = render_layers(
            frontend_templates(spec), web, render_context(spec), overwrite=False
        )
        assert (web / "src" / "app" / "page.tsx").read_text() == "// mine\n"
        assert any(p.name == "page.tsx" for p in result.skipped)


class TestLegacyKinds:
    @pytest.mark.parametrize("legacy", sorted(LEGACY_FRONTEND_KINDS))
    def test_every_previous_kind_still_loads(self, legacy):
        # Projects scaffolded by 0.1–0.8 must keep opening; their existing web/
        # directory is left alone either way.
        spec = AgentSpec.from_yaml(f"name: x-y\nfrontend:\n  kind: {legacy}\n")
        assert spec.frontend.kind == "agent_chat_ui"

    def test_default_is_agent_chat_ui(self):
        assert AgentSpec(name="x-y").frontend.kind == "agent_chat_ui"


class TestTheApiUrlIsAbsoluteBeforeItReachesTheSdk:
    """`new URL("/api/threads")` throws: no base, so it is not a valid URL.

    The SDK builds every request that way, so pointing the UI at the
    same-origin proxy path meant the page loaded, the health check passed —
    `fetch()` resolves relative paths by itself — and sending a message died
    with "Failed to construct 'URL': Invalid URL".

    Present in SDK 1.9.27, 1.9.28 and 1.9.29, so it is the contract rather than
    a regression.
    """

    def test_the_patch_is_present(self, tmp_path):
        build(tmp_path)
        stream = (tmp_path / "web/src/providers/Stream.tsx").read_text(encoding="utf-8")
        assert "resolveApiUrl" in stream, "the vendored patch was lost in a re-sync"

    def test_the_url_is_resolved_before_use(self, tmp_path):
        build(tmp_path)
        stream = (tmp_path / "web/src/providers/Stream.tsx").read_text(encoding="utf-8")
        assert "const finalApiUrl = resolveApiUrl(apiUrl || envApiUrl);" in stream

    def test_it_resolves_against_the_page_origin(self, tmp_path):
        # Not baked in at build time: one image has to serve localhost, an IP,
        # a tunnel and a domain without rebuilding.
        build(tmp_path)
        stream = (tmp_path / "web/src/providers/Stream.tsx").read_text(encoding="utf-8")
        assert "window.location.origin" in stream

    def test_server_rendering_is_guarded(self, tmp_path):
        # Next server-renders client components once, where window is undefined.
        build(tmp_path)
        stream = (tmp_path / "web/src/providers/Stream.tsx").read_text(encoding="utf-8")
        assert 'typeof window === "undefined"' in stream

    def test_the_patch_is_documented(self, tmp_path):
        build(tmp_path)
        note = (tmp_path / "web/VENDORED.md").read_text(encoding="utf-8")
        assert "resolveApiUrl" in note and "next.config.mjs" in note


class TestTheAppIsNamedAfterTheProject:
    """A user who builds `research-assistant` should see Research Assistant.

    Upstream ships "Agent Chat" and LangChain's mark, which is right for
    upstream and wrong for someone's own product.
    """

    def named(self, tmp_path, name="research-assistant"):
        spec = AgentSpec(name=name)
        scaffold(spec, tmp_path)
        return tmp_path / "web"

    def test_the_browser_tab_shows_the_project(self, tmp_path):
        web = self.named(tmp_path)
        layout = (web / "src/app/layout.tsx").read_text(encoding="utf-8")
        assert 'title: "Research Assistant"' in layout
        assert "LangChain" not in layout

    def test_the_headings_show_the_project(self, tmp_path):
        web = self.named(tmp_path)
        thread = (web / "src/components/thread/index.tsx").read_text(encoding="utf-8")
        assert "Agent Chat" not in thread
        assert thread.count("{APP_NAME}") == 2

    def test_the_name_comes_from_one_place(self, tmp_path):
        web = self.named(tmp_path)
        icon = (web / "src/components/icons/langgraph.tsx").read_text(encoding="utf-8")
        assert 'export const APP_NAME = "Research Assistant";' in icon

    def test_the_mark_uses_the_initials(self, tmp_path):
        web = self.named(tmp_path)
        icon = (web / "src/components/icons/langgraph.tsx").read_text(encoding="utf-8")
        assert ">\n        RA\n      </text>" in icon
        assert 'aria-label="Research Assistant"' in icon

    def test_the_colour_is_derived_and_stable(self, tmp_path):
        # Deterministic, so the icon does not change between builds.
        web = self.named(tmp_path)
        icon = (web / "src/components/icons/langgraph.tsx").read_text(encoding="utf-8")
        expected = AgentSpec(name="research-assistant").brand_hue
        assert f"hsl({expected} 62% 48%)" in icon

    def test_the_tab_icon_replaces_the_vendored_favicon(self, tmp_path):
        # Next serves app/icon.svg; shipping both leaves the browser choosing.
        web = self.named(tmp_path)
        assert (web / "src/app/icon.svg").is_file()
        assert not (web / "src/app/favicon.ico").exists()
        svg = (web / "src/app/icon.svg").read_text(encoding="utf-8")
        assert ">RA</text>" in svg

    def test_the_import_site_still_resolves(self, tmp_path):
        # The component keeps upstream's name so no other file needs editing.
        web = self.named(tmp_path)
        thread = (web / "src/components/thread/index.tsx").read_text(encoding="utf-8")
        assert 'import { APP_NAME, LangGraphLogoSVG } from "../icons/langgraph";' in thread

    def test_jinja_never_reaches_the_jsx_props(self, tmp_path):
        """index.tsx has JSX `{{ ... }}` style props; templating it ate them."""
        web = self.named(tmp_path)
        thread = (web / "src/components/thread/index.tsx").read_text(encoding="utf-8")
        assert 'style={{ width: "100%", height: "100%" }}' in thread
        assert "(Undefined, Undefined)" not in thread

    @pytest.mark.parametrize(
        "name,display,initials",
        [
            ("research-assistant", "Research Assistant", "RA"),
            ("scout", "Scout", "SC"),
            ("support-bot-pro", "Support Bot Pro", "SB"),
        ],
    )
    def test_names_of_every_shape(self, tmp_path, name, display, initials):
        spec = AgentSpec(name=name)
        assert spec.display_name == display
        assert spec.initials == initials
