"""`uv run mequizme`: serve the API and the built frontend on one port."""

import argparse
import os
from pathlib import Path

import uvicorn

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    """KEY=value lines from backend/.env (written by scripts/render_env.py). Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def main() -> None:
    ap = argparse.ArgumentParser(prog="mequizme")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="restart on code changes (development)")
    args = ap.parse_args()
    load_env_file()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
