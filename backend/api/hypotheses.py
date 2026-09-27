"""Hypothesis routes: detail, re-score, human approval. No scoring logic here."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import pipeline, store

router = APIRouter()


@router.get("/api/hypotheses")
def list_hypotheses():
    """All hypotheses, ranked by priority (desc)."""
    rows = store.list_all("hypotheses")
    rows = sorted(rows, key=lambda r: (-r.get("priority", 0), r.get("id", "")))
    return {"hypotheses": rows}


@router.get("/api/hypotheses/{hyp_id}")
def get_hypothesis(hyp_id: str):
    """Detail for one hypothesis including pattern checklist + breakdown."""
    for row in store.list_all("hypotheses"):
        if row.get("id") == hyp_id:
            return {"hypothesis": row}
    raise HTTPException(status_code=404, detail=f"unknown hypothesis '{hyp_id}' — it may have been reset; start over from Find patterns")


@router.post("/api/hypotheses/prioritize")
def prioritize_everything():
    """Re-score all hypotheses on the eight prioritization dimensions."""
    try:
        ranked = pipeline.prioritize_all()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"prioritize failed: {exc}") from exc
    return {"ok": True, "hypotheses": ranked}


@router.post("/api/hypotheses/{hyp_id}/prioritize")
def prioritize_single(hyp_id: str):
    """Re-score one hypothesis."""
    try:
        return {"ok": True, "hypothesis": pipeline.prioritize_one(hyp_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown hypothesis '{hyp_id}' — it may have been reset; start over from Find patterns") from None


@router.post("/api/hypotheses/{hyp_id}/approve")
def approve_hypothesis(hyp_id: str):
    """Human checkpoint: Candidate -> Prioritized (ready to test)."""
    try:
        return {"ok": True, "hypothesis": pipeline.approve(hyp_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown hypothesis '{hyp_id}' — it may have been reset; start over from Find patterns") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
