import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from pristine import pristine_copy

# FastAPI's TestClient sends Host: testserver. Allowed in tests only, never in the real app.
os.environ["MEQUIZME_ALLOWED_HOSTS"] = "testserver"


@pytest.fixture(scope="session")
def content(tmp_path_factory):
    return pristine_copy(tmp_path_factory.mktemp("content"))


@pytest.fixture
def client(tmp_path, content):
    app = create_app(content_dir=content, db_path=tmp_path / "t.db", static_dir=tmp_path / "none", llm=None)
    with TestClient(app) as c:
        yield c
