"""Keep other websites out of the local API.

The server listens on 127.0.0.1, but any page open in your browser can still send requests to it
(cross-site request forgery), and a hostile domain can re-point its DNS at 127.0.0.1 to read
responses (DNS rebinding). So every /api request must name a local host, and every request that
changes something must not come from another origin.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _hostname(value: str) -> str:
    try:
        return (urlsplit(f"//{value}").hostname or "").lower()
    except ValueError:
        return ""


class LocalOnly:
    def __init__(self, app: ASGIApp, extra_hosts: set[str] | None = None):
        self.app = app
        self.hosts = LOCAL_HOSTS | (extra_hosts or set())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/api/"):
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            if _hostname(headers.get("host", "")) not in self.hosts:
                await JSONResponse({"detail": "requests must be addressed to this computer"}, 421)(scope, receive, send)
                return
            origin = headers.get("origin")
            if scope["method"] not in SAFE_METHODS and origin and _hostname(origin.split("://", 1)[-1]) not in self.hosts:
                await JSONResponse({"detail": "cross-site request refused"}, 403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
