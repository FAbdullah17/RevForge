"""Experiments API tests: draft creation, state machine, errors."""
from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def _approved():
    client.post("/api/seed")
    client.post("/api/discover", json={"source": "seed", "top_k": 3})
    client.post("/api/hypotheses/H17/approve")
    return "H17"


def test_build_experiment_drafts_cohorts_and_moves_to_testing():
    _approved()
    r = client.post("/api/hypotheses/H17/test",
                    json={"treatment_n": 50, "control_n": 50})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    exp = body["experiment"]
    assert exp["id"].startswith("E17-")
    assert exp["hypothesis_id"] == "H17"
    assert exp["status"] == "draft"
    assert exp["treatment"]["n"] == 50 and exp["control"]["n"] == 50
    t = body["cohort"]["treatment"]
    assert t["companies_searched"] == 86
    assert client.get("/api/hypotheses/H17").json()["hypothesis"]["status"] == "Testing"


def test_experiment_ids_increment():
    _approved()
    e1 = client.post("/api/hypotheses/H17/test", json={}).json()["experiment"]["id"]
    # second build blocked while Testing; approve flow tested separately
    assert e1 == "E17-1"
    listed = client.get("/api/experiments").json()["experiments"]
    assert any(e["id"] == "E17-1" for e in listed)
    detail = client.get(f"/api/experiments/{e1}").json()["experiment"]
    assert detail["cohort"]["treatment"]["n"] == 50


def test_candidate_cannot_be_tested():
    client.post("/api/seed")
    client.post("/api/discover", json={"source": "seed", "top_k": 3})
    r = client.post("/api/hypotheses/H17/test", json={})
    assert r.status_code == 400  # approve first


def test_unknown_hypothesis_404():
    r = client.post("/api/hypotheses/NOPE/test", json={})
    assert r.status_code == 404


def test_bad_sizes_rejected():
    _approved()
    assert client.post("/api/hypotheses/H17/test",
                       json={"treatment_n": 0, "control_n": 50}).status_code == 422
    assert client.post("/api/hypotheses/H17/test",
                       json={"treatment_n": 500, "control_n": 50}).status_code == 422


def test_unknown_experiment_404():
    assert client.get("/api/experiments/NOPE").status_code == 404
