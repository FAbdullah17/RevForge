"""Live graph8 transport tests. Network + key required; never run by default.

Run: G8_LIVE=1 .venv/bin/python -m pytest tests/test_graph8_live.py -q
Uses the key from .env. Creates one clearly-named test list (lists have
no delete endpoint) and one campaign that is deleted afterwards.
"""
import os

import pytest

from backend import graph8

pytestmark = pytest.mark.skipif(
    os.getenv("G8_LIVE") != "1", reason="needs G8_LIVE=1 + API key"
)


def test_transport_is_live():
    assert not graph8._use_mock()
    assert graph8.transport() == "live"


def test_live_company_search():
    rows = graph8.search_companies({"employees_min": 150, "employees_max": 500}, limit=5)
    assert 1 <= len(rows) <= 5
    assert all(r["company"] and r["id"] for r in rows)
    assert all(r["tech"] == "unconfirmed" for r in rows)  # honest labeling


def test_live_people_search():
    rows = graph8.search_companies({"employees_min": 150, "employees_max": 500}, limit=3)
    people = graph8.find_people([r["id"] for r in rows])
    assert people
    assert all(p["company_id"] and p["title"] for p in people)


def test_live_create_then_delete_campaign():
    lst = graph8.create_list(["c1", "c2"], name="pytest-probe")
    assert lst["list_id"]
    cmp_ = graph8.create_campaign(lst["list_id"], name="pytest-probe")
    assert cmp_["campaign_id"]
    deleted = graph8._live("DELETE", f"/campaigns/{cmp_['campaign_id']}")
    assert deleted is not None
