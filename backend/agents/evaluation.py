"""Evaluation agent: do the outcomes support the hypothesis?

Compares treatment vs control positive-reply rates and returns one of:
Validated / Rejected / Inconclusive. Rules are deliberately conservative —
the system must never claim certainty from weak samples (no p-hacking,
no peeking adjustments, just pre-registered bars):

* Either group sent < MIN_N ................. Inconclusive (too small)
* lift >= MIN_LIFT_VALIDATE (1.2) ........... Validated
* lift < 1.0 (underperforms baseline) ....... Rejected
* 1.0 <= lift < 1.2 ......................... Inconclusive (directional only)

Pure functions, no I/O. Persistence lives in ``pipeline.evaluate``.
"""
from __future__ import annotations

from typing import Any, Literal

#: Minimum sends per group before any claim is allowed.
MIN_N = 30

#: Lift bar for validation. 1.2 = +20% relative over baseline control.
MIN_LIFT_VALIDATE = 1.2

Verdict = Literal["Validated", "Rejected", "Inconclusive"]


def _confidence(sent_t: int, sent_c: int) -> str:
    smaller = min(sent_t, sent_c)
    if smaller >= 100:
        return "high"
    if smaller >= 50:
        return "med"
    return "low"


def evaluate_pair(treatment: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    """Judge one treatment/control result pair.

    Args:
        treatment/control: Result-style dicts with sent + positive.

    Returns:
        Dict with treatment_rate, control_rate, lift (0.0 when undefined),
        verdict, confidence, reason, n_total. Deterministic.
    """
    sent_t, pos_t = int(treatment.get("sent", 0)), int(treatment.get("positive", 0))
    sent_c, pos_c = int(control.get("sent", 0)), int(control.get("positive", 0))
    rate_t = round(pos_t / sent_t, 4) if sent_t else 0.0
    rate_c = round(pos_c / sent_c, 4) if sent_c else 0.0

    base: dict[str, Any] = {
        "treatment_rate": rate_t,
        "control_rate": rate_c,
        "lift": 0.0,
        "verdict": "Inconclusive",
        "confidence": _confidence(sent_t, sent_c),
        "reason": "",
        "n_total": sent_t + sent_c,
    }
    if sent_t < MIN_N or sent_c < MIN_N:
        base["reason"] = (
            f"sample too small ({sent_t} vs {sent_c} sends, need >={MIN_N} per group)"
        )
        return base
    if rate_c <= 0:
        if rate_t > 0:
            base.update(verdict="Validated",
                        reason="control converted at 0%, treatment converted")
        else:
            base["reason"] = "neither group converted"
        return base
    lift = round(rate_t / rate_c, 3)
    base["lift"] = lift
    if lift >= MIN_LIFT_VALIDATE:
        base.update(verdict="Validated",
                    reason=f"+{round((lift - 1) * 100)}% relative lift over baseline")
    elif lift < 1.0:
        base.update(verdict="Rejected",
                    reason=f"underperforms baseline ({round((1 - lift) * 100)}% below)")
    else:
        base["reason"] = f"directional only ({lift}x, need >={MIN_LIFT_VALIDATE}x)"
    return base
