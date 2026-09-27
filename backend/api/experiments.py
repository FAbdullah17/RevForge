"""Experiment routes: build cohorts, launch, ingest outcomes, evaluate."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import pipeline, store
from ..agents.execution import MAX_COHORT, MIN_COHORT

router = APIRouter()


class TestRequest(BaseModel):
    """Cohort sizes. 50/50 default mirrors the spec's experiment design."""

    treatment_n: int = Field(default=50, ge=MIN_COHORT, le=MAX_COHORT)
    control_n: int = Field(default=50, ge=MIN_COHORT, le=MAX_COHORT)


@router.post("/api/hypotheses/{hyp_id}/test")
def test_hypothesis(hyp_id: str, body: TestRequest):
    """Build treatment + control cohorts via graph8; hypothesis -> Testing."""
    try:
        result = pipeline.build_experiment(hyp_id, body.treatment_n, body.control_n)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown hypothesis {hyp_id!r}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **result}


@router.get("/api/experiments")
def list_experiments():
    """All experiment drafts, newest last."""
    return {"experiments": store.list_all("experiments")}


@router.get("/api/experiments/{exp_id}")
def get_experiment(exp_id: str):
    """One experiment with its cohort snapshot."""
    for row in store.list_all("experiments"):
        if row.get("id") == exp_id:
            return {"experiment": row}
    raise HTTPException(status_code=404, detail=f"unknown experiment {exp_id!r}")


@router.post("/api/experiments/{exp_id}/launch")
def launch_experiment(exp_id: str):
    """Create graph8 lists + campaign. Draft -> Launched."""
    try:
        return {"ok": True, **pipeline.launch(exp_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown experiment {exp_id!r}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/experiments/{exp_id}/sync-outcomes")
def sync_outcomes(exp_id: str):
    """Ingest seeded mock outcomes (demo path). Launched -> Observed."""
    try:
        return {"ok": True, **pipeline.sync_outcomes(exp_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown experiment {exp_id!r}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/experiments/{exp_id}/evaluate")
def evaluate_experiment(exp_id: str):
    """Judge treatment vs control, update hypothesis + knowledge. Observed -> Evaluated."""
    try:
        return {"ok": True, **pipeline.evaluate(exp_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown experiment {exp_id!r}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/experiments/{exp_id}/results")
def experiment_results(exp_id: str):
    """Outcome rows for one experiment (lift + verdict attached at evaluation)."""
    if not any(e.get("id") == exp_id for e in store.list_all("experiments")):
        raise HTTPException(status_code=404, detail=f"unknown experiment {exp_id!r}")
    return {"experiment_id": exp_id, "results": store.results_for(exp_id)}


class WebhookEvent(BaseModel):
    """Live graph8 outcome event."""

    campaign_id: str
    group: Literal["treatment", "control"]
    sent: int = Field(ge=0)
    replies: int = Field(ge=0)
    positive: int = Field(ge=0)
    meetings: int = Field(ge=0)


@router.post("/webhooks/graph8")
def graph8_webhook(event: WebhookEvent):
    """Ingest a live outcome event. Unknown campaigns -> 404, bad counts -> 400."""
    try:
        result = pipeline.ingest_event(event.model_dump())
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"unknown campaign {event.campaign_id!r}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **result}
