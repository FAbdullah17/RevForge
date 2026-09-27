"""Hypothesis generation: candidate pattern -> testable Revenue Hypothesis.

Produces well-formed ``Candidate`` hypotheses with evidence attached.
``priority`` initially carries the discovery score; the prioritization
agent refines it with multi-dimension scoring before approval.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .discovery import CandidatePattern

#: Stable demo IDs matching the spec narrative (rank 1 -> H17, ...).
DEMO_IDS = ("H17", "H21", "H29")

#: Support below this is not testable (mirrors discovery.MIN_SUPPORT).
MIN_SUPPORT_HINT = 10


def _novelty(pattern: dict) -> str:
    """Heuristic novelty: richer conjunctions are less likely to be known ICPs."""
    size = len(pattern)
    if size >= 4:
        return "High"
    if size >= 2:
        return "Medium"
    return "Low"


def _testability(n: int) -> str:
    """Heuristic testability from support size."""
    if n >= 20:
        return "High"
    if n >= MIN_SUPPORT_HINT:
        return "Medium"
    return "Low"


def build_hypotheses(candidates: list[CandidatePattern]) -> list[dict]:
    """Convert ranked candidates into hypothesis dicts (validated by models.Hypothesis).

    IDs are stable per rank (H17/H21/H29...) so the demo story survives
    re-runs. Statuses start at ``Candidate``.
    """
    now = datetime.now(timezone.utc).isoformat()
    out: list[dict] = []
    for i, cand in enumerate(candidates):
        hid = DEMO_IDS[i] if i < len(DEMO_IDS) else f"H{i + 1:02d}"
        out.append(
            {
                "id": hid,
                "title": cand.title,
                "pattern": dict(cand.pattern),
                "evidence": {
                    "wins": cand.wins,
                    "support": cand.n,
                    "rate": cand.rate,
                    "baseline": cand.baseline,
                    "lift": cand.lift,
                    "spec_key": cand.key,
                },
                "novelty": _novelty(cand.pattern),
                "testability": _testability(cand.n),
                "priority": cand.score,
                "status": "Candidate",
                "created_at": now,
                "updated_at": now,
            }
        )
    return out
