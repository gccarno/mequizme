"""Other websites can't drive the local API, and link checks never touch the local network."""

import pytest

from app.llm import links


def test_cross_site_writes_are_refused(client):
    r = client.post("/api/attempts", json={"mode": "practice", "exam": "databricks-ml-associate"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/items/x/reject", headers={"Origin": "null"})
    assert r.status_code == 403
    # Reads and same-site writes still work.
    assert client.get("/api/packs", headers={"Origin": "https://evil.example"}).status_code == 200
    r = client.post("/api/attempts", json={"mode": "practice", "exam": "databricks-ml-associate"},
                    headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 201


def test_dns_rebinding_is_refused(client):
    assert client.get("/api/packs", headers={"Host": "evil.example"}).status_code == 421
    assert client.get("/api/packs", headers={"Host": "127.0.0.1:8000"}).status_code == 200


@pytest.mark.parametrize("url", [
    "http://docs.databricks.com/x",          # not https
    "https://127.0.0.1/admin",
    "https://localhost:8000/api/packs",
    "https://169.254.169.254/latest/meta-data",
    "https://10.0.0.5/",
    "https://[::1]/",
    "https://user@docs.databricks.com/",
])
def test_link_checker_refuses_local_and_odd_urls(url, monkeypatch):
    monkeypatch.setenv("MEQUIZME_CHECK_LINKS", "1")
    assert links.is_public_https(url) is False
    assert links.link_ok(url) is False
