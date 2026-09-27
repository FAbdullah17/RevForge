"""Linear pipeline: discover -> hypothesize -> prioritize -> test -> launch -> observe -> evaluate.

Each stage is a pure agent module; this file only orchestrates and
persists. Stages keep stable signatures so orchestration can evolve
without rewriting them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import data_loader, outcomes, store
from .agents import discovery, evaluation, execution, hypothesis, prioritize
from .llm import explain_pattern
from .models import Experiment, Hypothesis, Knowledge, Result


def discover(source: str = "seed", top_k: int = 3) -> dict:
    """Run pattern discovery over historical accounts.

    Args:
        source: Only ``"seed"`` (local JSON). ``"graph8"`` is reserved
            for live data reads once that integration is confirmed.
        top_k: Max hypotheses to persist.

    Returns:
        Dict with stats, hypotheses, and source. Hypotheses are
        validated via the Hypothesis model and atomically persisted
        (replace-all) with status ``Candidate``.

    Raises:
        ValueError: Unknown source or empty dataset.
    """
    if source != "seed":
        raise ValueError(f"unknown source {source!r}; only 'seed' is supported")
    df = data_loader.load_accounts_df()
    if df.empty:
        raise ValueError("no accounts loaded; POST /api/seed first")
    candidates = discovery.find_patterns(df, top_k=top_k)
    rows = hypothesis.build_hypotheses(candidates)
    # Fail fast on schema drift before touching the store.
    validated = [Hypothesis(**r).model_dump() for r in rows]
    for v in validated:
        spec_key = next(
            (c.key for c in candidates if c.title == v["title"]), ""
        )
        v["explanation"] = explain_pattern(
            v["title"], v["pattern"], {**v["evidence"], "spec_key": spec_key}
        )
    store.replace_all("hypotheses", validated)
    ranked = prioritize_all()  # full 8-dimension scoring + novelty check
    return {"stats": data_loader.stats(), "hypotheses": ranked, "source": source}


def _touch(row: dict) -> dict:
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    return row


def prioritize_all() -> list[dict]:
    """Re-score every stored hypothesis on all eight dimensions.

    Updates ``priority``, ``priority_breakdown``, ``novelty`` and
    ``novelty_reason`` in place (status untouched). Returns ranked rows.
    """
    total = data_loader.stats()["n"]
    ranked: list[dict] = []
    for row in store.list_all("hypotheses"):
        scored = prioritize.score_hypothesis(row, total)
        row["priority"] = scored["priority"]
        row["priority_breakdown"] = scored["breakdown"]
        row["novelty"] = scored["novelty_detail"]["label"]
        row["novelty_reason"] = scored["novelty_detail"]["reason"]
        ranked.append(_touch(Hypothesis(**row).model_dump()))
    ranked.sort(key=lambda r: (-r["priority"], r["id"]))
    store.replace_all("hypotheses", ranked)
    return ranked


def prioritize_one(hyp_id: str) -> dict:
    """Re-score a single hypothesis. Raises KeyError when unknown."""
    total = data_loader.stats()["n"]
    rows = store.list_all("hypotheses")
    for i, row in enumerate(rows):
        if row.get("id") == hyp_id:
            scored = prioritize.score_hypothesis(row, total)
            row["priority"] = scored["priority"]
            row["priority_breakdown"] = scored["breakdown"]
            row["novelty"] = scored["novelty_detail"]["label"]
            row["novelty_reason"] = scored["novelty_detail"]["reason"]
            rows[i] = _touch(Hypothesis(**row).model_dump())
            store.replace_all("hypotheses", rows)
            return rows[i]
    raise KeyError(f"unknown hypothesis {hyp_id!r}")


def approve(hyp_id: str) -> dict:
    """Human checkpoint: Candidate -> Prioritized (ready to test).

    Raises:
        KeyError: Unknown id.
        ValueError: Wrong status (only Candidate can be approved).
    """
    rows = store.list_all("hypotheses")
    for i, row in enumerate(rows):
        if row.get("id") == hyp_id:
            if row.get("status") != "Candidate":
                raise ValueError(
                    f"hypothesis {hyp_id!r} is {row.get('status')!r}, "
                    "only 'Candidate' can be approved"
                )
            row["status"] = "Prioritized"
            rows[i] = _touch(Hypothesis(**row).model_dump())
            store.replace_all("hypotheses", rows)
            return rows[i]
    raise KeyError(f"unknown hypothesis {hyp_id!r}")


def _next_experiment_id(hyp_id: str) -> str:
    """First free E<nn>-<k> id (H17 -> E17-1, E17-2, ...)."""
    stem = hyp_id[1:] if hyp_id.startswith("H") else hyp_id
    taken = {e.get("id") for e in store.list_all("experiments")}
    k = 1
    while f"E{stem}-{k}" in taken:
        k += 1
    return f"E{stem}-{k}"


def build_experiment(hyp_id: str, treatment_n: int = 50, control_n: int = 50) -> dict:
    """Turn an approved hypothesis into a draft experiment with cohorts.

    Runs the full graph8 prospect pipeline and persists the cohort
    snapshot on the experiment. Moves the hypothesis
    Prioritized -> Testing.

    Raises:
        KeyError: Unknown hypothesis.
        ValueError: Wrong status (only Prioritized can be tested) or
            cohort problem (bad sizes, insufficient market).
    """
    rows = store.list_all("hypotheses")
    hyp = next((r for r in rows if r.get("id") == hyp_id), None)
    if hyp is None:
        raise KeyError(f"unknown hypothesis {hyp_id!r}")
    if hyp.get("status") != "Prioritized":
        raise ValueError(
            f"hypothesis {hyp_id!r} is {hyp.get('status')!r}, "
            "only 'Prioritized' can be tested (approve it first)"
        )
    cohort = execution.build_cohort(hyp, treatment_n=treatment_n, control_n=control_n)
    exp = Experiment(
        id=_next_experiment_id(hyp_id),
        hypothesis_id=hyp_id,
        transport=execution.transport(),
        treatment={
            "n": cohort["treatment"]["n"],
            "filter": cohort["filter"],
            "company_ids": cohort["treatment"]["company_ids"],
            "contact_ids": cohort["treatment"]["contact_ids"],
        },
        control={
            "n": cohort["control"]["n"],
            "company_ids": cohort["control"]["company_ids"],
            "contact_ids": cohort["control"]["contact_ids"],
        },
    ).model_dump()
    exp["cohort"] = cohort  # full pipeline trace for the Test view
    store.insert("experiments", exp)
    hyp["status"] = "Testing"
    store.replace_all(
        "hypotheses",
        [_touch(Hypothesis(**r).model_dump()) if r.get("id") == hyp_id else r for r in rows],
    )
    return {"experiment": exp, "cohort": cohort}


def _get_experiment(exp_id: str) -> tuple[dict, list[dict]]:
    exps = store.list_all("experiments")
    exp = next((e for e in exps if e.get("id") == exp_id), None)
    if exp is None:
        raise KeyError(f"unknown experiment {exp_id!r}")
    return exp, exps


def _save_experiment(exp: dict, exps: list[dict]) -> dict:
    out = _touch(Experiment(**exp).model_dump())
    # Preserve the cohort snapshot (transport field, not part of the model).
    out["cohort"] = exp.get("cohort", {})
    store.replace_all(
        "experiments", [out if e.get("id") == exp["id"] else e for e in exps]
    )
    return out


def launch(exp_id: str) -> dict:
    """Launch a draft experiment: graph8 lists + campaign. Draft -> Launched.

    Raises:
        KeyError: Unknown experiment.
        ValueError: Wrong status (only Draft can launch).
    """
    exp, exps = _get_experiment(exp_id)
    if exp.get("status") != "draft":
        raise ValueError(
            f"experiment {exp_id!r} is {exp.get('status')!r}, only 'draft' can launch"
        )
    ids = execution.launch_campaign(
        exp_id,
        exp["treatment"].get("contact_ids", []),
        exp["control"].get("contact_ids", []),
    )
    exp["treatment"]["list_id"] = ids["treatment_list_id"]
    exp["control"]["list_id"] = ids["control_list_id"]
    exp["graph8_campaign_id"] = ids["campaign_id"]
    exp["status"] = "launched"
    exp["launched_at"] = datetime.now(timezone.utc).isoformat()
    return {"experiment": _save_experiment(exp, exps)}


def sync_outcomes(exp_id: str) -> dict:
    """Ingest mock (seeded) outcomes for a launched experiment.

    Idempotent: re-sync rewrites the same rows. Moves Launched -> Observed.

    Raises:
        KeyError: Unknown experiment.
        ValueError: Not launched yet.
    """
    exp, exps = _get_experiment(exp_id)
    if exp.get("status") not in ("launched", "observed"):
        raise ValueError(
            f"experiment {exp_id!r} is {exp.get('status')!r}, launch it first"
        )
    rows = [
        Result(**outcomes.build_result(
            exp_id, group,
            outcomes.mock_outcomes(int(exp[group].get("n", 0)), group),
            source="seeded",
        )).model_dump()
        for group in ("treatment", "control")
    ]
    stored = store.save_results(exp_id, rows)
    exp["status"] = "observed"
    return {"experiment": _save_experiment(exp, exps), "results": stored}


def ingest_event(event: dict) -> dict:
    """Ingest one live graph8 outcome event (webhook path).

    Event: {campaign_id, group, sent, replies, positive, meetings}.
    Stored with source=live. Experiment -> Observed once both groups
    have reported.

    Raises:
        KeyError: Unknown campaign.
        ValueError: Bad group or counts.
    """
    group = event.get("group")
    if group not in ("treatment", "control"):
        raise ValueError(f"group must be treatment|control, got {group!r}")
    exps = store.list_all("experiments")
    exp = next((e for e in exps if e.get("graph8_campaign_id") == event.get("campaign_id")), None)
    if exp is None:
        raise KeyError(f"unknown campaign {event.get('campaign_id')!r}")
    row = Result(**outcomes.build_result(
        exp["id"], group,
        {k: event.get(k, 0) for k in ("sent", "replies", "positive", "meetings")},
        source="live",
    )).model_dump()
    stored = store.save_results(exp["id"], [row] + [r for r in store.results_for(exp["id"]) if r.get("group") != group])
    groups = {r.get("group") for r in stored}
    if groups >= {"treatment", "control"} and exp.get("status") == "launched":
        exp["status"] = "observed"
        exp = _save_experiment(exp, exps)
    return {"experiment": exp, "result": row, "results": stored}


def _next_knowledge_id(hyp_id: str) -> str:
    """First free K<nn>-<k> id."""
    stem = hyp_id[1:] if hyp_id.startswith("H") else hyp_id
    taken = {k.get("id") for k in store.list_all("knowledge")}
    k = 1
    while f"K{stem}-{k}" in taken:
        k += 1
    return f"K{stem}-{k}"


def evaluate(exp_id: str) -> dict:
    """Judge an observed experiment and persist the learning.

    Compares treatment vs control, stamps lift + verdict on both result
    rows, moves the experiment Observed -> Evaluated, moves the
    hypothesis Testing -> Validated/Rejected/Inconclusive, and appends a
    revenue-knowledge row (failures stored too — the system remembers
    what did *not* work).

    Idempotent: re-evaluating recomputes the same verdict.

    Raises:
        KeyError: Unknown experiment.
        ValueError: Not observed yet, or a group is missing outcomes.
    """
    exp, exps = _get_experiment(exp_id)
    if exp.get("status") not in ("observed", "evaluated"):
        raise ValueError(
            f"experiment {exp_id!r} is {exp.get('status')!r}, collect outcomes first"
        )
    rows = store.results_for(exp_id)
    groups = {r.get("group"): r for r in rows}
    if set(groups) != {"treatment", "control"}:
        raise ValueError(f"experiment {exp_id!r} is missing outcome rows")
    verdict = evaluation.evaluate_pair(groups["treatment"], groups["control"])

    stamped = []
    for r in rows:
        r["lift"] = verdict["lift"]
        r["verdict"] = verdict["verdict"]
        stamped.append(Result(**r).model_dump())
    stored = store.save_results(exp_id, stamped)

    exp["status"] = "evaluated"
    exp["ended_at"] = datetime.now(timezone.utc).isoformat()
    exp = _save_experiment(exp, exps)

    hyp_id = exp["hypothesis_id"]
    hyps = store.list_all("hypotheses")
    hyp = next((h for h in hyps if h.get("id") == hyp_id), None)
    if hyp is not None:
        hyp["status"] = verdict["verdict"]
        store.replace_all(
            "hypotheses",
            [_touch(Hypothesis(**h).model_dump()) if h.get("id") == hyp_id else h for h in hyps],
        )
        pattern = hyp.get("pattern", {})
    else:
        pattern = {}

    knowledge = Knowledge(
        id=_next_knowledge_id(hyp_id),
        hypothesis_id=hyp_id,
        pattern=pattern,
        verdict=verdict["verdict"],
        confidence=verdict["confidence"],
    ).model_dump()
    # One knowledge row per hypothesis: re-evaluation replaces, never duplicates.
    kept = [k for k in store.list_all("knowledge") if k.get("hypothesis_id") != hyp_id]
    store.replace_all("knowledge", kept + [knowledge])
    return {"experiment": exp, "results": stored, "verdict": verdict, "knowledge": knowledge}
