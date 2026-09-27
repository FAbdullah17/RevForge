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


def test_live_enrich_chain_two_contacts():
    from backend.config import G8_OWNER_EMAIL

    lst = graph8.create_list(["x"], name="pytest-enrich")
    list_id = int(lst["list_id"])
    rows = [
        {"first_name": "Michael", "last_name": "Cascio",
         "linkedin_url": "linkedin.com/in/michael-cascio-7839a33",
         "company_id": "iac.com", "title": "Vp Sales"},
        {"first_name": "Mike", "last_name": "Zaret",
         "linkedin_url": "", "company_id": "", "title": "Sales"},
    ]
    asserted = graph8._live_assert_contacts(list_id, rows)
    assert asserted.get("created", 0) >= 1
    unlocked = graph8._live_unlock_list(list_id)
    assert unlocked.get("credits_charged", 0) >= 0
    members = graph8._live_list_members(list_id)
    assert len(members) >= 1 and all("pk" in m for m in members)
    verdicts = graph8._live_verify_pks([m["pk"] for m in members if m["pk"]])
    assert isinstance(verdicts, dict)
    seq_id = graph8._live_create_sequence("pytest-enrich", list_id, G8_OWNER_EMAIL)
    pks = [m["pk"] for m in members if m["pk"]]
    if pks:
        graph8._live_enroll(seq_id, list_id, pks)
        assert set(graph8._live_sequence_contacts(seq_id)) >= set(pks)
    archived = graph8.archive_sequence(seq_id)
    assert archived.get("status") in ("archived", None) or archived
