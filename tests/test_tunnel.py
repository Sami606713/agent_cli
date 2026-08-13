"""Tunnel provider selection and URL scraping.

Both providers announce their URL in human-readable output rather than on a
machine-readable channel, so the scraper is the fragile part and gets the tests.
"""

from __future__ import annotations

import pytest

from langctl.core.runtime.tunnel import CLOUDFLARED, NGROK, extract_url, resolve


class TestUrlExtraction:
    @pytest.mark.parametrize(
        "line,expected",
        [
            (
                "|  https://busy-panda-1234.trycloudflare.com   |",
                "https://busy-panda-1234.trycloudflare.com",
            ),
            (
                't=2026-08-12 lvl=info msg="started tunnel" url=https://7fdb-1-2-3.ngrok-free.app',
                "https://7fdb-1-2-3.ngrok-free.app",
            ),
            ("Forwarding https://abcd.ngrok.io -> http://localhost:3000", "https://abcd.ngrok.io"),
        ],
    )
    def test_finds_the_url(self, line, expected):
        assert extract_url(line) == expected

    def test_trailing_punctuation_is_trimmed(self):
        assert extract_url("visit https://x-1.trycloudflare.com.") == "https://x-1.trycloudflare.com"

    @pytest.mark.parametrize(
        "line",
        ["starting tunnel", "", "http://localhost:3000 is not public", "level=info msg=connected"],
    )
    def test_ignores_lines_without_a_public_url(self, line):
        assert extract_url(line) is None


class TestProviderSelection:
    def test_named_provider_is_honoured(self, monkeypatch):
        monkeypatch.setattr("langctl.core.runtime.tunnel.available", lambda: [CLOUDFLARED, NGROK])
        assert resolve("ngrok") is NGROK

    def test_cloudflared_wins_by_default(self, monkeypatch):
        # It needs no account, which is the whole reason to prefer it.
        monkeypatch.setattr("langctl.core.runtime.tunnel.available", lambda: [CLOUDFLARED, NGROK])
        assert resolve() is CLOUDFLARED

    def test_missing_provider_resolves_to_none(self, monkeypatch):
        monkeypatch.setattr("langctl.core.runtime.tunnel.available", lambda: [])
        assert resolve() is None
        assert resolve("ngrok") is None


class TestCommands:
    def test_cloudflared_uses_a_quick_tunnel(self):
        assert CLOUDFLARED.command(3000) == [
            "cloudflared", "tunnel", "--url", "http://localhost:3000"
        ]

    def test_ngrok_logs_parseably(self):
        # The default TUI repaints and cannot be scraped for the URL.
        cmd = NGROK.command(3000)
        assert "--log=stdout" in cmd and "--log-format=logfmt" in cmd
