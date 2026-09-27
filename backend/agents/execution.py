"""Execution agent: hypothesis -> graph8 search -> experiment cohorts.

Translates a Revenue Hypothesis into structured buyer-graph filters,
runs the full prospect pipeline (search -> people -> enrich -> signals),
and assembles treatment + control cohorts. Testing the *revenue
hypothesis*, not email copy: treatment matches the discovered stack,
control is the baseline market.

Only module (with the API layer) allowed to import ``backend.graph8``.
Deterministic under mock: same hypothesis in, same cohorts out.
"""
from __future__ import annotations

from typing import Any

from .. import graph8

#: Cohort size guardrails (keep payloads and JSON stores small).
MIN_COHORT = 1
MAX_COHORT = 200

#: Hypothesis pattern keys that select live signal state (vs static attrs).
SIGNAL_KEYS = {"intent", "sdr_openings_gte", "new_vp_sales"}


def hypothesis_to_filter(pattern: dict[str, Any]) -> dict[str, Any]:
    """Map hypothesis pattern keys onto graph8 search filters.

    Raises:
        ValueError: Pattern carries no mappable constraint (nothing to test).
    """
    filt: dict[str, Any] = {}
    if pattern.get("employees") == "150-500":
        filt["employees_min"] = 150
        filt["employees_max"] = 500
    if pattern.get("new_vp_sales") is True:
        filt["new_vp_sales"] = True
    if isinstance(pattern.get("sdr_openings_gte"), int):
        filt["sdr_min"] = pattern["sdr_openings_gte"]
    if isinstance(pattern.get("tech"), str):
        filt["tech"] = pattern["tech"]
    if isinstance(pattern.get("intent"), str):
        filt["intent"] = pattern["intent"]
    if not filt:
        raise ValueError(f"pattern {pattern!r} maps to an empty graph8 filter")
    return filt


def live_signal_keys(pattern: dict[str, Any]) -> list[str]:
    """Pattern dimensions observable as *current* signals (why-now evidence)."""
    return sorted(k for k in pattern if k in SIGNAL_KEYS)


def build_cohort(
    hypothesis: dict[str, Any],
    treatment_n: int = 50,
    control_n: int = 50,
) -> dict[str, Any]:
    """Build treatment + control cohorts for one hypothesis.

    Pipeline per group: search companies -> find buyers -> enrich ->
    confirm live signals. Control reuses the same pipeline over the
    non-matching market (baseline), so groups differ only in the pattern.

    Raises:
        ValueError: Bad sizes, unmappable pattern, or insufficient market
            (message states what was available — never silent truncation).
    """
    if not (MIN_COHORT <= treatment_n <= MAX_COHORT):
        raise ValueError(f"treatment_n must be {MIN_COHORT}..{MAX_COHORT}")
    if not (MIN_COHORT <= control_n <= MAX_COHORT):
        raise ValueError(f"control_n must be {MIN_COHORT}..{MAX_COHORT}")

    filt = hypothesis_to_filter(hypothesis.get("pattern", {}))

    matched = graph8.search_companies(filt)
    buyers = graph8.find_people([c["id"] for c in matched])
    enriched = graph8.enrich(buyers)
    signals = graph8.get_signals([c["id"] for c in matched])
    if len(enriched) < treatment_n:
        raise ValueError(
            f"only {len(enriched)} enriched treatment contacts for filter {filt}, "
            f"need {treatment_n}"
        )
    treatment = enriched[:treatment_n]

    matched_ids = {m["id"] for m in matched}
    baseline = graph8.search_companies({**filt, "exclude_ids": sorted(matched_ids)})
    base_buyers = graph8.enrich(graph8.find_people([c["id"] for c in baseline]))
    if len(base_buyers) < control_n:
        raise ValueError(
            f"only {len(base_buyers)} baseline contacts available, need {control_n}"
        )
    control = base_buyers[:control_n]

    return {
        "filter": filt,
        "live_signals": live_signal_keys(hypothesis.get("pattern", {})),
        "treatment": {
            "n": len(treatment),
            "companies_searched": len(matched),
            "buyers_found": len(buyers),
            "enriched": len(enriched),
            "signals_checked": len(signals),
            "company_ids": [c["company_id"] for c in treatment],
            "contact_ids": [c["id"] for c in treatment],
        },
        "control": {
            "n": len(control),
            "companies_searched": len(baseline),
            "company_ids": [c["company_id"] for c in control],
            "contact_ids": [c["id"] for c in control],
        },
    }


def transport() -> str:
    """Active graph8 transport ('mock' or 'live'), recorded on experiments."""
    return graph8.transport()


def launch_campaign(exp_id: str, treatment_ids: list[str], control_ids: list[str]) -> dict[str, str]:
    """Create graph8 lists + campaign for both cohorts.

    Two lists keep treatment/control attributable; one campaign executes
    the treatment motion while the control rides the baseline motion.
    Returns list + campaign ids (deterministic under mock).
    """
    t_list = graph8.create_list(treatment_ids, name=f"{exp_id}-treatment")
    c_list = graph8.create_list(control_ids, name=f"{exp_id}-control")
    campaign = graph8.create_campaign(t_list["list_id"], name=exp_id)
    return {
        "treatment_list_id": t_list["list_id"],
        "control_list_id": c_list["list_id"],
        "campaign_id": campaign["campaign_id"],
    }
