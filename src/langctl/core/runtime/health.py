"""Port probing and readiness polling.

The health gate is what separates this from two terminals: the frontend is not
started until the Agent Server answers ``/ok``. Without it you get a UI that
boots against a dead backend and shows a network error on first message.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from .process import TEXT_IO

#: Agent Server readiness endpoint (verified: `langgraph dev` serves GET /ok).
HEALTH_PATH = "/ok"


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """True if *port* can be bound right now.

    Uses a real bind rather than a connect attempt: connect-based checks report
    "free" for ports held in TIME_WAIT or bound to a different interface.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_free_port(preferred: int, host: str = "127.0.0.1", attempts: int = 20) -> int:
    """Return *preferred* if free, else the next free port above it."""
    for candidate in range(preferred, preferred + attempts):
        if is_port_free(candidate, host):
            return candidate
    raise RuntimeError(f"no free port in range {preferred}-{preferred + attempts}")


def describe_port_holder(port: int) -> str | None:
    """Best-effort description of what holds *port*, for error messages.

    Returns None when we cannot tell (no psutil, no permission, non-Linux).
    Never raises: this only ever decorates an error we are already reporting.
    """
    try:
        import subprocess

        out = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"],
            capture_output=True,
            timeout=2,
            **TEXT_IO,
        ).stdout.strip()
        lines = [ln for ln in out.splitlines()[1:] if ln.strip()]
        return lines[0].strip() if lines else None
    except Exception:
        return None


@dataclass
class WaitResult:
    ok: bool
    elapsed: float
    last_error: str | None = None


def wait_for_http(
    url: str,
    timeout: float = 90.0,
    on_progress: Callable[[float], None] | None = None,
    should_abort: Callable[[], str | None] | None = None,
    initial_interval: float = 0.1,
    max_interval: float = 1.0,
) -> WaitResult:
    """Poll *url* until it returns 2xx/3xx, or give up.

    Args:
        url: Full health URL, e.g. ``http://127.0.0.1:2024/ok``.
        timeout: Hard ceiling in seconds.
        on_progress: Called with elapsed seconds so the caller can show a spinner.
        should_abort: Checked each tick. Returning a string aborts immediately with
            that reason — this is how a crashed backend short-circuits the wait
            instead of making the user sit through the full timeout.
        initial_interval: First sleep, kept small so a fast server is detected fast.
        max_interval: Ceiling for the exponential backoff.

    Returns:
        WaitResult with ``ok`` set and, on failure, the last transport error.
    """
    start = time.monotonic()
    interval = initial_interval
    last_error: str | None = None

    with httpx.Client(timeout=2.0) as client:
        while True:
            if should_abort is not None:
                reason = should_abort()
                if reason:
                    return WaitResult(False, time.monotonic() - start, reason)

            try:
                response = client.get(url)
                if response.status_code < 400:
                    return WaitResult(True, time.monotonic() - start)
                last_error = f"HTTP {response.status_code}"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"

            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                return WaitResult(False, elapsed, last_error)
            if on_progress is not None:
                on_progress(elapsed)

            time.sleep(min(interval, max(0.0, timeout - elapsed)))
            interval = min(interval * 1.6, max_interval)
