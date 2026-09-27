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
            "contacts": [_slim(c) for c in treatment],
        },
        "control": {
            "n": len(control),
            "companies_searched": len(baseline),
            "company_ids": [c["company_id"] for c in control],
            "contact_ids": [c["id"] for c in control],
            "contacts": [_slim(c) for c in control],
        },
    }


def _slim(c: dict[str, Any]) -> dict[str, Any]:
    """Contact fields worth persisting on the experiment snapshot."""
    return {k: c.get(k, "") for k in (
        "id", "company_id", "company", "title", "email", "linkedin_url",
        "first_name", "last_name", "verified",
    )}


def transport() -> str:
    """Active graph8 transport ('mock' or 'live'), recorded on experiments."""
    return graph8.transport()


def live_transport() -> bool:
    """True when calls really reach graph8 (not mock)."""
    return not graph8._use_mock()


def sequence_enrolled(sequence_id: str) -> int:
    """Enrolled member count of a staged sequence (dry-fire sent count)."""
    return len(graph8._live_sequence_contacts(sequence_id))


def launch_campaign(exp_id: str, treatment: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    """Create graph8 lists + campaign for both cohorts.

    Two lists keep treatment/control attributable; one campaign executes
    the treatment motion while the control rides the baseline motion.
    On live transport this also runs the enrichment chain (assert into
    the lists, unlock, verify) and stages one drafted sequence per group
    with members enrolled — sequences are never run (dry-fire only).
    Returns ids, enrichment spend, and merged contact snapshots.
    """
    t_list = graph8.create_list(treatment.get("contact_ids", []), name=f"{exp_id}-treatment")
    c_list = graph8.create_list(control.get("contact_ids", []), name=f"{exp_id}-control")
    campaign = graph8.create_campaign(t_list["list_id"], name=exp_id)
    result: dict[str, Any] = {
        "treatment_list_id": t_list["list_id"],
        "control_list_id": c_list["list_id"],
        "campaign_id": campaign["campaign_id"],
    }
    if graph8.transport() == "live":
        if not treatment.get("contacts") or not control.get("contacts"):
            raise ValueError(
                "experiment snapshot has no contact rows; rebuild cohorts before launching"
            )
        result.update(_live_enrich_and_stage(
            exp_id, t_list["list_id"], c_list["list_id"],
            treatment.get("contacts", []), control.get("contacts", []),
        ))
    return result


def _live_enrich_and_stage(exp_id: str, t_list_id: int, c_list_id: int,
                           t_contacts: list[dict[str, Any]],
                           c_contacts: list[dict[str, Any]]) -> dict[str, Any]:
    """Live-only: enrich members and stage (never run) one sequence per group."""
    from ..config import G8_OWNER_EMAIL

    if not G8_OWNER_EMAIL:
        raise ValueError("G8_OWNER_EMAIL is not set; sequences need a workspace owner email")

    groups = {}
    credits = 0
    for label, list_id, rows in (("treatment", t_list_id, t_contacts),
                                 ("control", c_list_id, c_contacts)):
        asserted = graph8._live_assert_contacts(list_id, rows)
        unlocked = graph8._live_unlock_list(list_id)
        credits += int(unlocked.get("credits_charged", 0) or 0)
        members = graph8._live_list_members(list_id)
        pks = [m["pk"] for m in members if m["pk"] not in ("", None)]
        verdicts = graph8._live_verify_pks(pks) if pks else {}
        merged = []
        for m in members:
            merged.append({
                "pk": m["pk"], "email": m["email"] or "",
                "verified": bool(verdicts.get(m["pk"], False)),
                "linkedin_url": m["linkedin_url"],
                "first_name": m["first_name"], "last_name": m["last_name"],
            })
        seq_id = graph8._live_create_sequence(f"{exp_id}-{label}", list_id, G8_OWNER_EMAIL)
        if pks:
            graph8._live_enroll(seq_id, list_id, pks)
        groups[label] = {
            "list_id": list_id, "sequence_id": seq_id,
            "asserted": asserted, "contacts": merged,
        }
    return {"groups": groups, "credits_spent": credits}
