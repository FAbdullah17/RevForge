"""Discovery API tests: POST persists Candidates, GET ranks, errors are clean."""
from fastapi.testclient import TestClient

from backend import store
from backend.app import app

client = TestClient(app)


def test_discover_persists_three_candidates():
    client.post("/api/seed?fixed=true")
    r = client.post("/api/discover", json={"source": "seed", "top_k": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["stats"]["n"] == 10000
    hyps = body["hypotheses"]
    assert len(hyps) == 3
    assert hyps[0]["id"] == "H17"
    assert all(h["status"] == "Candidate" for h in hyps)
    assert hyps[0]["evidence"]["lift"] > 1.2
    # Persisted, ranked by priority.
    listed = client.get("/api/hypotheses").json()["hypotheses"]
    assert len(listed) == 3
    assert listed[0]["id"] == "H17"


def test_discover_is_idempotent_replace():
    client.post("/api/seed?fixed=true")
    client.post("/api/discover", json={"source": "seed", "top_k": 3})
    client.post("/api/discover", json={"source": "seed", "top_k": 3})
    assert len(client.get("/api/hypotheses").json()["hypotheses"]) == 3


def test_discover_rejects_bad_top_k():
    r = client.post("/api/discover", json={"source": "seed", "top_k": 99})
    assert r.status_code == 400


def test_discover_requires_seed_first():
    # Empty accounts -> clean 400, never 500 or silent [].
    saved = store.list_all("accounts")
    store.replace_all("accounts", [])
    try:
        r = client.post("/api/discover", json={"source": "seed", "top_k": 3})
        assert r.status_code == 400
    finally:
        store.replace_all("accounts", saved)
        client.post("/api/seed?fixed=true")
        client.post("/api/discover", json={"source": "seed", "top_k": 3})
