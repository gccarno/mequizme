"""Write the app's env files from `terraform output` in infra/.

Run from the repo root after `terraform apply`:
    python scripts/render_env.py

Writes (both gitignored):
    frontend/.env.local   VITE_FIREBASE_* and VITE_SENTRY_DSN (baked into the web build)
    backend/.env          SENTRY_DSN, MEQUIZME_FIREBASE_API_KEY, MEQUIZME_FIREBASE_PROJECT
Existing keys not managed here are kept.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tf_outputs(infra: Path) -> dict:
    out = subprocess.run(["terraform", f"-chdir={infra}", "output", "-json"],
                         check=True, capture_output=True, text=True).stdout
    return {k: v["value"] for k, v in json.loads(out).items()}


def merge_env(path: Path, values: dict[str, str]) -> None:
    lines, seen = [], set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0].strip()
            if key in values:
                lines.append(f"{key}={values[key]}")
                seen.add(key)
            else:
                lines.append(line)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({', '.join(values)})")


def main() -> int:
    out = tf_outputs(ROOT / "infra")
    web, dsns = out["firebase_web_config"], out["sentry_dsns"]
    merge_env(ROOT / "frontend" / ".env.local", {
        "VITE_FIREBASE_API_KEY": web["apiKey"],
        "VITE_FIREBASE_AUTH_DOMAIN": web["authDomain"],
        "VITE_FIREBASE_PROJECT_ID": web["projectId"],
        "VITE_FIREBASE_APP_ID": web["appId"],
        "VITE_SENTRY_DSN": dsns["web"],
    })
    merge_env(ROOT / "backend" / ".env", {
        "SENTRY_DSN": dsns["backend"],
        "MEQUIZME_FIREBASE_API_KEY": web["apiKey"],
        "MEQUIZME_FIREBASE_PROJECT": web["projectId"],
    })
    print(f"StudyDeck Sentry DSN (put in local.properties as sentry.dsn): {dsns['android']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
