"""Drop AI-suggested links that don't exist. Models sometimes invent plausible doc URLs."""

from __future__ import annotations

import os
import urllib.error
import urllib.request

TIMEOUT_SEC = 8
_cache: dict[str, bool] = {}


def link_ok(url: str) -> bool:
    """False only when the page is clearly missing (404/410 or the host doesn't resolve).
    Sites that block bots (403, 429) or time out get the benefit of the doubt."""
    if os.environ.get("MEQUIZME_CHECK_LINKS", "1") == "0":
        return True
    if url in _cache:
        return _cache[url]
    ok = True
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": "mequizme-linkcheck/1"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC):
                ok = True
                break
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                ok = False
                break
            if e.code == 405 and method == "HEAD":
                continue  # HEAD not allowed; try GET
            ok = True
            break
        except urllib.error.URLError as e:
            ok = not isinstance(e.reason, OSError) or "timed out" in str(e.reason)
            break
        except (TimeoutError, ValueError):
            ok = True
            break
    _cache[url] = ok
    return ok


def keep_live(resources: list[dict]) -> list[dict]:
    return [r for r in resources if link_ok(r["url"])]
