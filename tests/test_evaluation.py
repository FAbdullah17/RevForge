"""Evaluation tests: verdict rules, knowledge persistence, guards."""
from fastapi.testclient import TestClient

from backend.agents import evaluation
from backend.app import app

client = TestClient(app)

T = lambda sent, pos: {"sent": sent, "positive": pos}  # noqa: E731


def test_validated_on_clear_lift():
    v = evaluation.evaluate_pair(T(50, 4), T(50, 2))  # 8% vs 4% -> 2.0x
    assert v["verdict"] == "Validated" and v["lift"] == 2.0
    assert v["confidence"] == "med" and v["n_total"] == 100


def test_rejected_when_underperforming():
    v = evaluation.evaluate_pair(T(100, 3), T(100, 4))  # 3% vs 4%
    assert v["verdict"] == "Rejected" and v["lift"] < 1.0


def test_inconclusive_in_noise_band():
    v = evaluation.evaluate_pair(T(100, 6), T(100, 5))  # 1.2x boundary... 6/5=1.2
    assert v["lift"] == 1.2 and v["verdict"] == "Validated"
    v2 = evaluation.evaluate_pair(T(100, 11), T(100, 10))  # 1.1x
    assert v2["verdict"] == "Inconclusive"


def test_inconclusive_on_small_sample():
    v = evaluation.evaluate_pair(T(10, 2), T(10, 0))
    assert v["verdict"] == "Inconclusive" and "too small" in v["reason"]


def test_zero_control_handled():
    v = evaluation.evaluate_pair(T(50, 3), T(50, 0))
    assert v["verdict"] == "Validated" and v["lift"] == 0.0
    v2 = evaluation.evaluate_pair(T(50, 0), T(50, 0))
    assert v2["verdict"] == "Inconclusive"


def test_deterministic():
    a = evaluation.evaluate_pair(T(50, 4), T(50, 2))
    assert evaluation.evaluate_pair(T(50, 4), T(50, 2)) == a


def _observed():
    client.post("/api/seed")
    client.post("/api/discover", json={"source": "seed", "top_k": 3})
    client.post("/api/hypotheses/H17/approve")
    exp_id = client.post("/api/hypotheses/H17/test", json={}).json()["experiment"]["id"]
    client.post(f"/api/experiments/{exp_id}/launch")
    client.post(f"/api/experiments/{exp_id}/sync-outcomes")
    return exp_id


def test_full_loop_validates_and_stores_knowledge():
    exp_id = _observed()
    r = client.post(f"/api/experiments/{exp_id}/evaluate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"]["verdict"] == "Validated"
    assert body["verdict"]["lift"] == 2.0
    assert body["experiment"]["status"] == "evaluated"
    assert body["experiment"]["ended_at"]
    rows = {x["group"]: x for x in body["results"]}
    assert all(x["verdict"] == "Validated" and x["lift"] == 2.0 for x in rows.values())
    hyp = client.get("/api/hypotheses/H17").json()["hypothesis"]
    assert hyp["status"] == "Validated"
    kn = client.get("/api/knowledge").json()["knowledge"]
    assert len(kn) == 1
    assert kn[0]["hypothesis_id"] == "H17" and kn[0]["verdict"] == "Validated"
    assert kn[0]["pattern"]["tech"] == "Salesforce"


def test_rejected_path_via_live_rows():
    exp_id = _observed()
    exp = client.get(f"/api/experiments/{exp_id}").json()["experiment"]
    cid = exp["graph8_campaign_id"]
    client.post("/webhooks/graph8", json={"campaign_id": cid, "group": "treatment",
               "sent": 100, "replies": 6, "positive": 3, "meetings": 1})
    client.post("/webhooks/graph8", json={"campaign_id": cid, "group": "control",
               "sent": 100, "replies": 8, "positive": 4, "meetings": 1})
    body = client.post(f"/api/experiments/{exp_id}/evaluate").json()
    assert body["verdict"]["verdict"] == "Rejected"
    assert client.get("/api/hypotheses/H17").json()["hypothesis"]["status"] == "Rejected"
    kn = client.get("/api/knowledge").json()["knowledge"]
    assert kn[0]["verdict"] == "Rejected"  # failures remembered too


def test_evaluate_guards_and_idempotency():
    assert client.post("/api/experiments/NOPE/evaluate").status_code == 404
    client.post("/api/seed")
    client.post("/api/discover", json={"source": "seed", "top_k": 3})
    client.post("/api/hypotheses/H17/approve")
    draft = client.post("/api/hypotheses/H17/test", json={}).json()["experiment"]["id"]
    assert client.post(f"/api/experiments/{draft}/evaluate").status_code == 400
    client.post(f"/api/experiments/{draft}/launch")
    client.post(f"/api/experiments/{draft}/sync-outcomes")
    first = client.post(f"/api/experiments/{draft}/evaluate").json()["verdict"]
    second = client.post(f"/api/experiments/{draft}/evaluate").json()["verdict"]
    assert first == second and first["verdict"] == "Validated"
    kn = client.get("/api/knowledge").json()["knowledge"]
    assert len([k for k in kn if k["hypothesis_id"] == "H17"]) == 1
