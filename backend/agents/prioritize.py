"""Hypothesis prioritization: which discovery is worth testing first?

Scores every Candidate on eight normalized (0..1) dimensions and combines
them with documented weights into a single ``priority`` in 0..1.

Dimensions:
    evidence_strength   support size — is there enough data to trust it?
    effect_size         lift over baseline — how big is the observed edge?
    novelty             is this genuinely new vs the known ICP/strategy?
    market_size         cohort size relative to the addressable base.
    signal_availability can we observe this pattern live via graph8 signals?
    data_quality        completeness of the supporting rows.
    testability         can we build treatment + control cohorts?
    business_value      expected revenue impact if validated.

Deterministic: same hypothesis dict in, same scores out. Pure functions,
no I/O — persistence lives in ``pipeline.prioritize``.
"""
from __future__ import annotations

from typing import Any

from ..config import KNOWN_ICPS

#: Weights sum to 1.0. Novelty leads: at equal lift, the more specific
#: stack outranks its own broad subsets (the spec's core bet is that the
#: *combination* is the insight). Evidence weight stays modest because
#: MIN_SUPPORT already gates noise and data_quality covers size again.
WEIGHTS: dict[str, float] = {
    "evidence_strength": 0.15,
    "effect_size": 0.25,
    "novelty": 0.25,
    "market_size": 0.10,
    "signal_availability": 0.05,
    "data_quality": 0.05,
    "testability": 0.10,
    "business_value": 0.05,
}

#: Pattern keys observable as live buyer signals. Availability measures
#: whether a pattern can be confirmed as true *right now*, not just
#: whether accounts ever matched it historically.
OBSERVABLE_KEYS = {
    "intent",
    "sdr_openings_gte",
    "sdr_openings",
    "tech",
    "new_vp_sales",
    "employees",
    "hiring",
    "job_change",
}

_TESTABILITY_MAP = {"High": 1.0, "Medium": 0.6, "Low": 0.3}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def evidence_strength(support: int) -> float:
    """0..1 confidence from cohort size. Saturates at 30 accounts."""
    return _clamp(support / 30.0)


def effect_size(lift: float) -> float:
    """0..1 from observed lift. lift=1.0 -> 0, lift>=2.0 -> 1."""
    return _clamp(lift - 1.0)


def market_size(support: int, total: int) -> float:
    """0..1 cohort share of the base. Saturates at ~1/3 of base."""
    if total <= 0:
        return 0.0
    return _clamp((support / total) * 3.0)


def signal_availability(pattern: dict[str, Any]) -> float:
    """Fraction of pattern keys observable live. Empty pattern -> 0."""
    if not pattern:
        return 0.0
    hits = sum(1 for k in pattern if k in OBSERVABLE_KEYS)
    return _clamp(hits / len(pattern))


def data_quality(support: int, wins: int) -> float:
    """0..1 completeness proxy. Full marks at support>=20 with both outcomes."""
    if support <= 0:
        return 0.0
    size = _clamp(support / 20.0)
    balance = 1.0 if 0 < wins < support else 0.5  # one-sided cohorts teach less
    return _clamp(size * balance)


def testability_score(label: str) -> float:
    """Map the generation-stage High/Medium/Low label to 0..1."""
    return _TESTABILITY_MAP.get(label, 0.3)


def business_value(lift: float, rate: float) -> float:
    """0..1 expected impact: big lift on a high absolute rate matters most."""
    return _clamp((lift - 1.0) * 2.0 * (0.5 + rate))


def novelty_check(pattern: dict[str, Any]) -> dict[str, Any]:
    """Compare a pattern against known ICPs/strategies.

    Tokenizes ``KNOWN_ICPS`` and the pattern's keys+values, then measures
    overlap. Low overlap -> genuinely new pattern.

    Returns:
        Dict with ``label`` (High/Medium/Low), ``overlap`` ratio, ``reason``
        naming the overlapping vs novel dimensions. Deterministic.
    """
    known_tokens: set[str] = set()
    for icp in KNOWN_ICPS:
        for tok in icp.lower().replace("/", " ").replace("-", " ").split():
            known_tokens.add(tok)

    pat_tokens: set[str] = set()
    for k, v in pattern.items():
        pat_tokens.add(str(k).lower())
        for tok in str(v).lower().replace("/", " ").replace("-", " ").split():
            pat_tokens.add(tok)
    # Generic glue words carry no signal about the business pattern.
    pat_tokens -= {"true", "false", "gte", "high", "medium", "low"}

    if not pat_tokens:
        return {"label": "Low", "overlap": 1.0, "score": 0.0,
                "reason": "empty pattern matches everything"}

    overlap_dims = sorted(t for t in pat_tokens if t in known_tokens)
    novel_dims = sorted(t for t in pat_tokens if t not in known_tokens)
    overlap = len(overlap_dims) / len(pat_tokens)
    # Continuous novelty: less ICP overlap -> more novel. Thin (<=2-dim)
    # patterns cap at Medium: a bare pair like "new VP + hiring" resembles
    # generic sales wisdom, not a discovered stack, however unmatched.
    score = round(1.0 - overlap, 4)
    if overlap < 0.40 and len(pattern) >= 3:
        label = "High"
    elif overlap < 0.70 and len(pattern) >= 2:
        label = "Medium"
        score = min(score, 0.6)
    else:
        label = "Low" if overlap >= 0.70 else "Medium"
        score = min(score, 0.6 if label == "Medium" else 0.3)
    reason = (
        f"overlaps known ICP on {overlap_dims or 'nothing'}; "
        f"novel dimensions: {novel_dims or 'none'}"
    )
    return {"label": label, "overlap": round(overlap, 3), "score": score,
            "reason": reason}


def novelty_score(label: str, overlap: float | None = None) -> float:
    """Map novelty to 0..1. Continuous when overlap is known, else label buckets."""
    if overlap is not None:
        return _clamp(round(1.0 - overlap, 4))
    return _TESTABILITY_MAP.get(label, 0.3)


def score_hypothesis(hyp: dict[str, Any], total_accounts: int) -> dict[str, Any]:
    """Score one hypothesis dict. Returns dimension breakdown + priority.

    Does not mutate the input. ``priority`` is the weighted sum rounded
    to 4 decimals; ``breakdown`` holds each 0..1 dimension.
    """
    ev = hyp.get("evidence", {})
    support = int(ev.get("support", 0))
    wins = int(ev.get("wins", 0))
    lift = float(ev.get("lift", 1.0))
    rate = float(ev.get("rate", 0.0))
    pattern = hyp.get("pattern", {})

    nov = novelty_check(pattern)
    breakdown = {
        "evidence_strength": round(evidence_strength(support), 4),
        "effect_size": round(effect_size(lift), 4),
        "novelty": nov["score"],
        "market_size": round(market_size(support, total_accounts), 4),
        "signal_availability": round(signal_availability(pattern), 4),
        "data_quality": round(data_quality(support, wins), 4),
        "testability": round(testability_score(hyp.get("testability", "Low")), 4),
        "business_value": round(business_value(lift, rate), 4),
    }
    priority = round(sum(breakdown[k] * WEIGHTS[k] for k in WEIGHTS), 4)
    return {
        "priority": priority,
        "breakdown": breakdown,
        "novelty_detail": nov,
    }
