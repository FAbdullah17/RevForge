"""Launch, mock sync, live webhook, and guard tests."""
import pytest

from backend import outcomes, store
from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def test_mock_fixtures_direction_and_shape():
    t = outcomes.mock_outcomes(50, "treatment")
    c = outcomes.mock_outcomes(50, "control")
    assert t["sent"] == 50 and c["sent"] == 50
    assert t["positive"] > c["positive"]  # embedded edge survives to execution
    for counts in (t, c):
        assert counts["replies"] <= 50
        assert counts["meetings"] <= counts["positive"]


def test_build_result_validation():
    good = outcomes.build_result("E1", "treatment",
                                 {"sent": 50, "replies": 9, "positive": 4, "meetings": 2},
                                 "seeded")
    assert good["rate"] == 0.08 and good["n_small"] is False
    with pytest.raises(ValueError, match="sent must be > 0"):
        outcomes.build_result("E1", "treatment", {"sent": 0}, "seeded")
    with pytest.raises(ValueError, match="cannot exceed sent"):
        outcomes.build_result("E1", "treatment",
                              {"sent": 10, "replies": 3, "positive": 11, "meetings": 0},
                              "seeded")
    with pytest.raises(ValueError, match="unknown source"):
        outcomes.build_result("E1", "treatment",
                              {"sent": 10, "replies": 1, "positive": 1, "meetings": 0},
                              "bogus")


def _launched(exp_n=50):
    client.post("/api/seed")
    client.post("/api/discover", json={"source": "seed", "top_k": 3})
    client.post("/api/hypotheses/H17/approve")
    r = client.post("/api/hypotheses/H17/test",
                    json={"treatment_n": exp_n, "control_n": exp_n})
    exp_id = r.json()["experiment"]["id"]
    launched = client.post(f"/api/experiments/{exp_id}/launch").json()["experiment"]
    return launched


def test_launch_creates_ids_and_moves_to_launched():
    exp = _launched()
    assert exp["status"] == "launched"
    assert exp["graph8_campaign_id"].startswith("cmp-E17-1")
    assert exp["treatment"]["list_id"].startswith("list-E17-1-treatment")
    assert exp["control"]["list_id"].startswith("list-E17-1-control")
    assert exp["launched_at"]


def test_launch_guards():
    _launched()
    exp_id = client.get("/api/experiments").json()["experiments"][-1]["id"]
    assert client.post(f"/api/experiments/{exp_id}/launch").status_code == 400
    assert client.post("/api/experiments/NOPE/launch").status_code == 404


def test_sync_writes_seeded_rows_and_observes():
    exp = _launched()
    r = client.post(f"/api/experiments/{exp['id']}/sync-outcomes")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["experiment"]["status"] == "observed"
    rows = {x["group"]: x for x in body["results"]}
    assert set(rows) == {"treatment", "control"}
    assert all(x["source"] == "seeded" for x in rows.values())
    assert rows["treatment"]["rate"] > rows["control"]["rate"]
    # idempotent re-sync
    again = client.post(f"/api/experiments/{exp['id']}/sync-outcomes").json()["results"]
    assert len(again) == 2


def test_sync_requires_launch():
    client.post("/api/seed")
    client.post("/api/discover", json={"source": "seed", "top_k": 3})
    client.post("/api/hypotheses/H17/approve")
    exp_id = client.post("/api/hypotheses/H17/test", json={}).json()["experiment"]["id"]
    assert client.post(f"/api/experiments/{exp_id}/sync-outcomes").status_code == 400


def test_webhook_live_path_and_validation():
    exp = _launched()
    evt = {"campaign_id": exp["graph8_campaign_id"], "group": "treatment",
           "sent": 50, "replies": 10, "positive": 5, "meetings": 2}
    r = client.post("/webhooks/graph8", json=evt)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["source"] == "live"
    # second group -> observed
    evt2 = dict(evt, group="control", sent=50, replies=6, positive=3, meetings=1)
    r2 = client.post("/webhooks/graph8", json=evt2)
    assert r2.json()["experiment"]["status"] == "observed"
    # unknown campaign + bad counts
    bad = dict(evt, campaign_id="cmp-nope")
    assert client.post("/webhooks/graph8", json=bad).status_code == 404
    bad_counts = dict(evt, positive=99)
    assert client.post("/webhooks/graph8", json=bad_counts).status_code == 400


def test_results_endpoint():
    exp = _launched()
    assert client.get(f"/api/experiments/{exp['id']}/results").json()["results"] == []
    client.post(f"/api/experiments/{exp['id']}/sync-outcomes")
    rows = client.get(f"/api/experiments/{exp['id']}/results").json()["results"]
    assert len(rows) == 2
    assert client.get("/api/experiments/NOPE/results").status_code == 404
    # seed reset clears results too
    client.post("/api/seed")
    assert store.results_for(exp["id"]) == []
