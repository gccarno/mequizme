"""Server for the Playwright tests: a throwaway database, a draft-free copy of content/ and the
offline fake tutor, so runs are repeatable and never edit the real pack files."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pristine import pristine_copy  # noqa: E402

import uvicorn  # noqa: E402


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    root = Path(tempfile.mkdtemp(prefix="mequizme-e2e-"))
    os.environ["MEQUIZME_CONTENT"] = str(pristine_copy(root / "content"))
    os.environ["MEQUIZME_DB"] = str(root / "e2e.db")
    os.environ["MEQUIZME_LLM"] = "fake"
    os.environ["MEQUIZME_CHECK_LINKS"] = "0"
    uvicorn.run("app.main:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
