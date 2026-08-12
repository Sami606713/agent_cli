"""Public tunnels for a locally running app.

One tunnel is enough. Because the browser reaches the agent through the
frontend's own proxy route, exposing the frontend exposes the whole app — and
the agent, its port, and the API keys never become reachable from outside.

`langgraph dev --tunnel` exists but tunnels the *agent*, which is the wrong
layer here: it would publish the raw API and bypass the frontend entirely.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass

#: cloudflared quick tunnels need no account at all; ngrok needs an authtoken.
#: That is the whole reason cloudflared is preferred when both are present.
PROVIDERS = ("cloudflared", "ngrok")

_URL_PATTERNS = (
    re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com"),
    re.compile(r"https://[a-z0-9-]+\.ngrok-free\.app"),
    re.compile(r"https://[a-z0-9-]+\.ngrok\.io"),
    re.compile(r"url=(https://[^\s]+)"),
)


@dataclass
class TunnelProvider:
    name: str
    binary: str
    install_hint: str

    def command(self, port: int) -> list[str]:
        if self.name == "cloudflared":
            return [self.binary, "tunnel", "--url", f"http://localhost:{port}"]
        # logfmt on stdout is the only reliable way to read the URL back;
        # ngrok's default TUI repaints and cannot be parsed.
        return [
            self.binary,
            "http",
            str(port),
            "--log=stdout",
            "--log-format=logfmt",
        ]


CLOUDFLARED = TunnelProvider(
    "cloudflared",
    "cloudflared",
    "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/",
)
NGROK = TunnelProvider(
    "ngrok",
    "ngrok",
    "https://ngrok.com/download, then `ngrok config add-authtoken <token>`",
)


def available() -> list[TunnelProvider]:
    return [p for p in (CLOUDFLARED, NGROK) if shutil.which(p.binary)]


def resolve(preferred: str | None = None) -> TunnelProvider | None:
    """Pick a tunnel provider, honouring an explicit choice."""
    found = available()
    if preferred:
        return next((p for p in found if p.name == preferred), None)
    return found[0] if found else None


def extract_url(line: str) -> str | None:
    """Find a public URL in a line of tunnel output.

    Both providers announce the URL in prose rather than on a machine-readable
    channel, so scanning output is the supported approach.
    """
    for pattern in _URL_PATTERNS:
        match = pattern.search(line)
        if match:
            url = match.group(1) if match.lastindex else match.group(0)
            return url.rstrip(".,)")
    return None
