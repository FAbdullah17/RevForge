"""Frontend smoke tests: shell serves, views exist, copy stays honest."""
from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def test_index_has_four_views_and_tabs():
    html = client.get("/").text
    for section in ("view-discover", "view-hypothesis", "view-test", "view-results"):
        assert f'id="{section}"' in html
    for tab in ("discover", "hypothesis", "test", "results"):
        assert f'data-tab="{tab}"' in html
    assert "stepper" in html and "err" in html


def test_honest_labels_present():
    html = client.get("/").text
    assert "SEEDED" in html  # seeded-history + mock-outcome labeling
    assert "MOCK_GRAPH8" in html


def test_static_js_serves_and_mentions_flow():
    r = client.get("/static/app.js")
    assert r.status_code == 200
    for token in ("showTab", "loadKnowledge", "evaluateExperiment", "launchExperiment",
                  "backend unreachable", "same origin"):
        assert token in r.text
