"""API tests: health, stats, seed, accounts."""
from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_seed_then_stats():
    r = client.post("/api/seed")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["reset"]["accounts"] == 142

    s = client.get("/api/stats").json()
    assert s["stats"]["n"] == 142
    assert s["stats"]["won"] == 87


def test_accounts_limit():
    client.post("/api/seed")
    r = client.get("/api/accounts?limit=5")
    assert r.status_code == 200
    assert r.json()["n"] == 142
    assert len(r.json()["accounts"]) == 5


def test_index_serves():
    r = client.get("/")
    assert r.status_code == 200
    assert "RevForge" in r.text
