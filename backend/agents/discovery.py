"""Pattern discovery over historical revenue outcomes.

Consumes a normalized accounts DataFrame (via ``backend.data_loader``) and
returns ranked candidate patterns — conjunctions of interpretable business
attributes that convert above the global baseline.

Design notes
------------
* Pure functions: no I/O, no LLM, no graph8 calls. Deterministic output.
* Leakage guard: the hidden ``is_h17_pattern`` seed label is never read.
  Discovery may only use business columns (employees, tech, intent, ...).
* Small curated spec list (not brute-force mining) keeps results explainable
  and the demo stable. Each spec is a falsifiable business claim.
* Ranking balances effect size, support, and specificity:
  ``score = (lift - 1) * sqrt(n) + SPECIFICITY_WEIGHT * len(pattern)``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

#: Minimum cohort size for a pattern to be considered. Guards against noise.
MIN_SUPPORT = 10

#: Minimum lift over baseline to be interesting.
MIN_LIFT = 1.10

#: Specificity prior: at equal evidence, a richer conjunction is a more
#: interesting, more falsifiable claim (it also feeds novelty scoring).
#: This keeps full stacks ranked above their own broad subsets.
SPECIFICITY_WEIGHT = 0.25

#: Business columns discovery is allowed to read. Anything else is ignored.
ALLOWED_FEATURES = {
    "employees",
    "new_vp_sales",
    "sdr_openings",
    "tech",
    "intent",
    "industry",
    "region",
    "persona_title",
}


def bin_employees(n: int) -> str:
    """Bucket raw headcount into interpretable bands."""
    if n < 150:
        return "<150"
    if n <= 500:
        return "150-500"
    return ">500"


def bin_sdr(n: int) -> str:
    """Bucket SDR openings into hiring-signal bands."""
    return "3+" if n >= 3 else "0-2"


@dataclass(frozen=True)
class PatternSpec:
    """A named, testable conjunction over account attributes."""

    key: str
    title: str
    predicate: Callable[[pd.DataFrame], pd.Series]
    pattern: dict[str, Any] = field(default_factory=dict)


def _specs() -> list[PatternSpec]:
    """Curated candidate patterns, ordered for deterministic evaluation."""
    return [
        PatternSpec(
            key="vp_sdr_intent_stack",
            title="New VP Sales + SDR hiring + high intent",
            predicate=lambda df: (
                df["employees"].between(150, 500)
                & df["new_vp_sales"].eq(True)
                & (df["sdr_openings"] >= 3)
                & (df["tech"] == "Salesforce")
                & (df["intent"] == "high")
            ),
            pattern={
                "employees": "150-500",
                "new_vp_sales": True,
                "sdr_openings_gte": 3,
                "tech": "Salesforce",
                "intent": "high",
            },
        ),
        PatternSpec(
            key="salesforce_midmarket_intent",
            title="Salesforce + mid-market + high intent",
            predicate=lambda df: (
                df["employees"].between(150, 500)
                & (df["tech"] == "Salesforce")
                & (df["intent"] == "high")
            ),
            pattern={"employees": "150-500", "tech": "Salesforce", "intent": "high"},
        ),
        PatternSpec(
            key="leadership_hiring_momentum",
            title="New VP Sales + active SDR hiring",
            predicate=lambda df: (
                df["new_vp_sales"].eq(True) & (df["sdr_openings"] >= 3)
            ),
            pattern={"new_vp_sales": True, "sdr_openings_gte": 3},
        ),
        PatternSpec(
            key="high_intent_salesforce",
            title="High intent + Salesforce",
            predicate=lambda df: (
                (df["tech"] == "Salesforce") & (df["intent"] == "high")
            ),
            pattern={"tech": "Salesforce", "intent": "high"},
        ),
        PatternSpec(
            key="high_intent_only",
            title="High purchase intent",
            predicate=lambda df: (df["intent"] == "high"),
            pattern={"intent": "high"},
        ),
        PatternSpec(
            key="vp_change_only",
            title="Recent VP Sales hire",
            predicate=lambda df: (df["new_vp_sales"].eq(True)),
            pattern={"new_vp_sales": True},
        ),
    ]


@dataclass(frozen=True)
class CandidatePattern:
    """A scored pattern with supporting evidence."""

    key: str
    title: str
    pattern: dict[str, Any]
    n: int
    wins: int
    rate: float
    baseline: float
    lift: float
    score: float


def _baseline_rate(df: pd.DataFrame) -> float:
    """Global win rate. Returns 0.0 for empty frames (no crash)."""
    if df.empty:
        return 0.0
    return float((df["outcome"] == "won").mean())


def evaluate_spec(df: pd.DataFrame, spec: PatternSpec, baseline: float) -> CandidatePattern | None:
    """Score one spec. Returns None when below support/lift bars."""
    mask = spec.predicate(df).fillna(False).astype(bool)
    n = int(mask.sum())
    if n < MIN_SUPPORT or baseline <= 0:
        return None
    wins = int(((df["outcome"] == "won") & mask).sum())
    rate = wins / n
    lift = rate / baseline
    if lift < MIN_LIFT:
        return None
    score = (lift - 1.0) * math.sqrt(n) + SPECIFICITY_WEIGHT * len(spec.pattern)
    return CandidatePattern(
        key=spec.key,
        title=spec.title,
        pattern=dict(spec.pattern),
        n=n,
        wins=wins,
        rate=round(rate, 4),
        baseline=round(baseline, 4),
        lift=round(lift, 3),
        score=round(score, 4),
    )


def find_patterns(df: pd.DataFrame, top_k: int = 3) -> list[CandidatePattern]:
    """Rank candidate patterns.

    Args:
        df: Normalized accounts frame. Must contain ``outcome`` plus the
            business columns used by specs. The ``is_h17_pattern`` column,
            if present, is ignored (leakage guard).
        top_k: Maximum patterns to return.

    Returns:
        Up to ``top_k`` candidates sorted by score (desc), then key (asc)
        for deterministic ties. Empty list when no data or no spec clears
        the support/lift bars — never raises on shape issues.
    """
    if df.empty or "outcome" not in df.columns:
        return []
    missing = ALLOWED_FEATURES - set(df.columns)
    if missing:
        return []
    baseline = _baseline_rate(df)
    if baseline <= 0:
        return []
    ranked: list[CandidatePattern] = []
    for spec in _specs():
        try:
            cand = evaluate_spec(df, spec, baseline)
        except (KeyError, TypeError, ValueError):
            continue
        if cand is not None:
            ranked.append(cand)
    ranked.sort(key=lambda c: (-c.score, c.key))
    return ranked[:top_k]
