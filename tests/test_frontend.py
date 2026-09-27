"""Frontend smoke tests: shell serves, views exist, copy stays honest."""
from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def test_index_has_four_views_and_tabs():
    html = client.get("/").text
    for section in ("view-data", "view-discover", "view-hypothesis", "view-test", "view-results"):
        assert f'id="{section}"' in html
    for tab in ("data", "discover", "hypothesis", "test", "results"):
        assert f'data-tab="{tab}"' in html
    assert "stepper" in html and "err" in html


def test_honest_labels_present():
    html = client.get("/").text
    assert "demo data" in html  # provenance stated in plain words, no env vars
    assert "MOCK_" not in html and "mock_graph8" not in html
    js = client.get("/static/app.js").text
    assert "SEEDED" in js  # per-row outcome labels stay honest where details show


def test_static_js_serves_and_mentions_flow():
    r = client.get("/static/app.js")
    assert r.status_code == 200
    for token in ("showTab", "loadKnowledge", "evaluateExperiment", "launchExperiment",
                  "backend unreachable", "same origin"):
        assert token in r.text


def test_every_touched_element_exists():
    """No `null.innerHTML`: each $("id") is in index.html or created in JS."""
    import re
    html = client.get("/").text
    js = client.get("/static/app.js").text
    static_ids = set(re.findall(r'id="([a-z-]+)"', html))
    created_ids = set(re.findall(r'id="([a-z-]+)"', js))
    available = static_ids | created_ids
    touched = set(re.findall(r'\$\("([a-z-]+)"\)', js))
    orphan = sorted(i for i in touched if i not in available)
    if orphan:
        raise AssertionError(f"JS touches missing elements: {orphan}")
