"""Hypotheses API tests: detail, re-score, approve checkpoint, errors."""
from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def _fresh():
    client.post("/api/seed?fixed=true")
    return client.post("/api/discover", json={"source": "seed", "top_k": 3}).json()["hypotheses"]


def test_detail_returns_checklist_and_breakdown():
    _fresh()
    r = client.get("/api/hypotheses/H17")
    assert r.status_code == 200, r.text
    h = r.json()["hypothesis"]
    assert h["id"] == "H17"
    assert h["pattern"]["tech"] == "Salesforce"
    assert h["priority_breakdown"]
    assert h["novelty_reason"]
    assert h["status"] == "Candidate"


def test_detail_404():
    _fresh()
    assert client.get("/api/hypotheses/NOPE").status_code == 404


def test_approve_moves_candidate_to_prioritized():
    _fresh()
    r = client.post("/api/hypotheses/H17/approve")
    assert r.status_code == 200, r.text
    assert r.json()["hypothesis"]["status"] == "Prioritized"
    # persisted + visible in list
    listed = {h["id"]: h for h in client.get("/api/hypotheses").json()["hypotheses"]}
    assert listed["H17"]["status"] == "Prioritized"


def test_approve_rejects_double_approve():
    _fresh()
    client.post("/api/hypotheses/H17/approve")
    r = client.post("/api/hypotheses/H17/approve")
    assert r.status_code == 400


def test_approve_404():
    _fresh()
    assert client.post("/api/hypotheses/NOPE/approve").status_code == 404


def test_prioritize_endpoints():
    _fresh()
    r = client.post("/api/hypotheses/H21/prioritize")
    assert r.status_code == 200, r.text
    assert 0.0 <= r.json()["hypothesis"]["priority"] <= 1.0
    r = client.post("/api/hypotheses/prioritize")
    assert r.status_code == 200, r.text
    hyps = r.json()["hypotheses"]
    assert hyps[0]["id"] == "H17"  # H17 survives re-scoring on top
    assert r.json()["hypotheses"] == client.get("/api/hypotheses").json()["hypotheses"]
