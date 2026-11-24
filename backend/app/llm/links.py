"""Drop AI-suggested links that don't exist. Models sometimes invent plausible doc URLs.

The URLs come from model output, so treat them as untrusted: public https hosts only, never an
address on this machine or the local network, and every redirect is checked the same way.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlsplit

TIMEOUT_SEC = 8
MAX_REDIRECTS = 5
_cache: dict[str, bool] = {}


def is_public_https(url: str) -> bool:
    """https, default port, and every address the host resolves to is public."""
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.port not in (None, 443) or parts.username:
            return False
        infos = socket.getaddrinfo(parts.hostname, 443, proto=socket.IPPROTO_TCP)
    except (ValueError, OSError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            return False
    return bool(infos)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # follow redirects by hand, checking each target


_opener = urllib.request.build_opener(_NoRedirect)


def _status(url: str, method: str) -> int | None:
    """Final HTTP status after safe redirects; None when unreachable or the target isn't allowed."""
    for _ in range(MAX_REDIRECTS + 1):
        if not is_public_https(url):
            return None
        req = urllib.request.Request(url, method=method, headers={"User-Agent": "mequizme-linkcheck/1"})
        try:
            with _opener.open(req, timeout=TIMEOUT_SEC) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            return e.code
    return None


def link_ok(url: str) -> bool:
    """False when the page is clearly missing (404/410), the host doesn't resolve, or the link points
    somewhere we won't fetch. Sites that block bots (403, 429) or time out get the benefit of the doubt."""
    if os.environ.get("MEQUIZME_CHECK_LINKS", "1") == "0":
        return urlsplit(url).scheme == "https"  # offline: no lookups at all
    if not is_public_https(url):
        return False
    if url in _cache:
        return _cache[url]
    try:
        code = _status(url, "HEAD")
        if code == 405:
            code = _status(url, "GET")
        ok = code is not None and code not in (404, 410)
    except (TimeoutError, socket.timeout):
        ok = True
    except (urllib.error.URLError, OSError, ValueError) as e:
        ok = "timed out" in str(e)
    _cache[url] = ok
    return ok


def keep_live(resources: list[dict]) -> list[dict]:
    return [r for r in resources if link_ok(r["url"])]
