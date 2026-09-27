"""Outcome ingestion: mock fixtures + live event validation.

Two paths write ``results.json`` rows (validated by ``models.Result``):
* Mock (``sync``): deterministic seeded fixtures per cohort size. The
  treatment converts ~2x the control — the embedded H17 edge surviving
  into simulated execution. Always labeled ``source=seeded``.
* Live (``webhook``): real graph8 outcome events, labeled ``source=live``.
  Strictly validated; unknown campaigns rejected (no junk rows).

Rates are positive-reply rates (positive / sent). Verdict assignment lives
with the evaluation agent; this module only records measurable outcomes.
"""
from __future__ import annotations

from typing import Any, Literal

#: Mock positive-reply rates per group. Fixed fixtures keep the demo
#: deterministic; the 2x gap mirrors the discovered historical lift.
MOCK_RATES = {"treatment": 0.08, "control": 0.04}

Group = Literal["treatment", "control"]


def mock_outcomes(n: int, group: Group) -> dict[str, int]:
    """Deterministic fixture counts for a cohort of size n."""
    positive = round(n * MOCK_RATES[group])
    replies = min(n, positive * 2 + 1)
    meetings = positive // 2
    return {"sent": n, "replies": replies, "positive": positive, "meetings": meetings}


def build_result(experiment_id: str, group: Group, counts: dict[str, int], source: str) -> dict[str, Any]:
    """Assemble a Result row with computed rate. Raises on bad counts."""
    sent = int(counts.get("sent", 0))
    replies = int(counts.get("replies", 0))
    positive = int(counts.get("positive", 0))
    meetings = int(counts.get("meetings", 0))
    for name, v in (("sent", sent), ("replies", replies), ("positive", positive), ("meetings", meetings)):
        if v < 0:
            raise ValueError(f"{name} must be >= 0, got {v}")
    if sent <= 0:
        raise ValueError("sent must be > 0")
    if positive > sent:
        raise ValueError(f"positive ({positive}) cannot exceed sent ({sent})")
    if replies > sent:
        raise ValueError(f"replies ({replies}) cannot exceed sent ({sent})")
    if meetings > positive:
        raise ValueError(f"meetings ({meetings}) cannot exceed positive ({positive})")
    if source not in ("live", "seeded", "simulated"):
        raise ValueError(f"unknown source {source!r}")
    return {
        "experiment_id": experiment_id,
        "group": group,
        "sent": sent,
        "replies": replies,
        "positive": positive,
        "meetings": meetings,
        "rate": round(positive / sent, 4),
        "lift": 0.0,  # stamped with lift + verdict at evaluation time
        "n_small": sent < 30,
        "verdict": "Inconclusive",
        "source": source,
    }
