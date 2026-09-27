"""Execution tests: filter mapping, mock universe, cohort determinism."""
import pytest

from backend import graph8
from backend.agents import execution


def test_universe_counts():
    uni = graph8.get_universe()
    assert len(uni) == 320
    full = [c for c in uni if (
        150 <= c["employees"] <= 500 and c["new_vp_sales"]
        and c["sdr_openings"] >= 3 and c["tech"] == "Salesforce" and c["intent"] == "high")]
    assert len(full) == 86  # demo-stable market for the H17 stack


def test_search_is_deterministic():
    filt = {"employees_min": 150, "employees_max": 500, "tech": "Salesforce", "intent": "high"}
    first = [c["id"] for c in graph8.search_companies(filt)]
    second = [c["id"] for c in graph8.search_companies(filt)]
    assert first == second and len(first) > 0


def test_filter_mapping():
    filt = execution.hypothesis_to_filter({
        "employees": "150-500", "new_vp_sales": True,
        "sdr_openings_gte": 3, "tech": "Salesforce", "intent": "high",
    })
    assert filt == {"employees_min": 150, "employees_max": 500,
                    "new_vp_sales": True, "sdr_min": 3,
                    "tech": "Salesforce", "intent": "high"}
    with pytest.raises(ValueError):
        execution.hypothesis_to_filter({"industry": "SaaS"})


def test_h17_cohort_shape_and_counts():
    hyp = {"id": "H17", "pattern": {
        "employees": "150-500", "new_vp_sales": True,
        "sdr_openings_gte": 3, "tech": "Salesforce", "intent": "high"}}
    cohort = execution.build_cohort(hyp, treatment_n=50, control_n=50)
    t, c = cohort["treatment"], cohort["control"]
    assert t["companies_searched"] == 86
    assert t["buyers_found"] > t["companies_searched"]  # multi-buyer companies
    assert t["enriched"] == t["buyers_found"]  # mock enriches everything
    assert t["n"] == 50 and c["n"] == 50
    assert set(t["contact_ids"]).isdisjoint(c["contact_ids"])
    assert set(t["company_ids"]).isdisjoint(set(c["company_ids"]))
    assert set(cohort["live_signals"]) == {"intent", "new_vp_sales", "sdr_openings_gte"}


def test_cohort_deterministic():
    hyp = {"id": "H17", "pattern": {"tech": "Salesforce", "intent": "high"}}
    assert execution.build_cohort(hyp) == execution.build_cohort(hyp)


def test_cohort_errors_are_explicit():
    hyp = {"id": "H17", "pattern": {"tech": "Salesforce"}}
    with pytest.raises(ValueError, match="treatment_n"):
        execution.build_cohort(hyp, treatment_n=0)
    with pytest.raises(ValueError, match="only"):
        execution.build_cohort(hyp, treatment_n=200, control_n=200)
