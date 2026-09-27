"""Discovery engine tests: ranking, bars, determinism, leakage guard."""
import pandas as pd

from backend import data_loader, store
from backend.agents import discovery
from backend.agents.hypothesis import build_hypotheses


def _df():
    store.reset_all()
    return data_loader.load_accounts_df()


def test_finds_seeded_h17_first():
    df = _df()
    cands = discovery.find_patterns(df, top_k=3)
    assert len(cands) == 3
    top = cands[0]
    assert top.pattern.get("tech") == "Salesforce"
    assert top.pattern.get("intent") == "high"
    assert top.pattern.get("new_vp_sales") is True
    assert top.n == 2000
    assert top.wins == 1640
    assert top.lift > 1.2


def test_ranked_and_deterministic():
    df = _df()
    first = [c.key for c in discovery.find_patterns(df)]
    second = [c.key for c in discovery.find_patterns(df)]
    assert first == second
    scores = [c.score for c in discovery.find_patterns(df)]
    assert scores == sorted(scores, reverse=True)


def test_support_and_lift_bars():
    df = _df()
    for c in discovery.find_patterns(df):
        assert c.n >= discovery.MIN_SUPPORT
        assert c.lift >= discovery.MIN_LIFT


def test_empty_frame_never_raises():
    assert discovery.find_patterns(pd.DataFrame()) == []
    assert discovery.find_patterns(pd.DataFrame([{"outcome": "won"}])) == []


def test_no_label_leakage():
    # Discovery must work identically with the hidden label removed.
    df = _df()
    assert "is_h17_pattern" in df.columns
    blind = df.drop(columns=["is_h17_pattern"])
    assert [c.key for c in discovery.find_patterns(blind)] == [
        c.key for c in discovery.find_patterns(df)
    ]


def test_hypotheses_well_formed():
    from backend.models import Hypothesis

    df = _df()
    rows = build_hypotheses(discovery.find_patterns(df))
    assert [r["id"] for r in rows] == ["H17", "H21", "H29"]
    for r in rows:
        Hypothesis(**r)  # raises on schema drift
        assert r["status"] == "Candidate"
