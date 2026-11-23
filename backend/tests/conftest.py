from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

CONTENT = Path(__file__).resolve().parents[2] / "content"


@pytest.fixture
def client(tmp_path):
    app = create_app(content_dir=CONTENT, db_path=tmp_path / "t.db", static_dir=tmp_path / "none")
    with TestClient(app) as c:
        yield c
