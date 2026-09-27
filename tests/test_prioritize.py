"""Prioritization unit tests: dimensions, novelty, determinism, H17 on top."""
from backend import data_loader, store
from backend.agents import discovery, hypothesis, prioritize
from backend import pipeline


def _seeded_hypotheses():
    store.reset_all()
    df = data_loader.load_accounts_df()
    return hypothesis.build_hypotheses(discovery.find_patterns(df)), df


def test_weights_sum_to_one():
    assert abs(sum(prioritize.WEIGHTS.values()) - 1.0) < 1e-9


def test_novelty_high_for_full_stack():
    full = {"employees": "150-500", "new_vp_sales": True, "sdr_openings_gte": 3,
            "tech": "Salesforce", "intent": "high"}
    res = prioritize.novelty_check(full)
    assert res["label"] == "High"
    assert "reason" in res and res["reason"]


def test_novelty_low_for_bare_icp_overlap():
    # Pattern restating the known ICP should not count as discovery.
    bare = {"region": "US", "industry": "SaaS", "employees": "100-500"}
    res = prioritize.novelty_check(bare)
    assert res["label"] in ("Low", "Medium")
    assert res["overlap"] > prioritize.novelty_check(
        {"new_vp_sales": True, "sdr_openings_gte": 3, "tech": "Salesforce",
         "intent": "high", "employees": "150-500"})["overlap"]


def test_score_dimensions_bounded_and_deterministic():
    rows, df = _seeded_hypotheses()
    total = len(df)
    for r in rows:
        s1 = prioritize.score_hypothesis(r, total)
        s2 = prioritize.score_hypothesis(r, total)
        assert s1 == s2
        assert 0.0 <= s1["priority"] <= 1.0
        assert set(s1["breakdown"]) == set(prioritize.WEIGHTS)
        assert all(0.0 <= v <= 1.0 for v in s1["breakdown"].values())


def test_h17_ranked_first_after_prioritize():
    store.reset_all()
    pipeline.discover(source="seed", top_k=3)
    ranked = pipeline.prioritize_all()
    assert ranked[0]["id"] == "H17"
    assert ranked[0]["priority_breakdown"]  # breakdown persisted
    assert ranked[0]["novelty_reason"]  # reason persisted
    assert all(0.0 <= r["priority"] <= 1.0 for r in ranked)


def test_dimension_helpers_edge_cases():
    assert prioritize.market_size(10, 0) == 0.0
    assert prioritize.signal_availability({}) == 0.0
    assert prioritize.data_quality(0, 0) == 0.0
    assert prioritize.evidence_strength(100) == 1.0
    assert prioritize.effect_size(3.0) == 1.0
