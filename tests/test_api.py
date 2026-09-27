"""API tests: health, stats, seed, accounts."""
from fastapi.testclient import TestClient

from backend.app import app
from backend.seed import MAX_N, MIN_N

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_seed_then_stats():
    r = client.post("/api/seed?fixed=true")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["reset"]["accounts"] == 10000

    s = client.get("/api/stats").json()
    assert s["stats"]["n"] == 10000
    assert s["stats"]["won"] == 6127


def test_accounts_limit():
    client.post("/api/seed?fixed=true")
    r = client.get("/api/accounts?limit=5")
    assert r.status_code == 200
    assert r.json()["n"] == 10000
    assert len(r.json()["accounts"]) == 5


def test_index_serves():
    r = client.get("/")
    assert r.status_code == 200
    assert "RevForge" in r.text


def test_seed_generates_fresh_random_datasets():
    seen = set()
    for _ in range(4):
        body = client.post("/api/seed").json()
        assert body["ok"] is True
        n = body["dataset"]["n"]
        assert MIN_N <= n <= MAX_N
        s = client.get("/api/stats").json()["stats"]
        assert s["n"] == n and s["won"] == body["dataset"]["won"]
        seen.add(n)
    assert len(seen) > 1  # basically impossible to collide 4x by chance... unless fixed
    # restore deterministic state for suites that assume the template
    client.post("/api/seed?fixed=true")
