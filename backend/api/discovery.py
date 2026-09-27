"""Discovery routes: run analysis. Listing lives in api/hypotheses."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import pipeline

router = APIRouter()


class DiscoverRequest(BaseModel):
    """Discover body. Only local seed data until live reads are wired."""

    source: Literal["seed"] = "seed"
    top_k: int = 3


@router.post("/api/discover")
def run_discover(body: DiscoverRequest):
    """Analyze revenue outcomes -> persist up to top_k Candidate hypotheses."""
    if body.top_k < 1 or body.top_k > 10:
        raise HTTPException(status_code=400, detail="top_k must be 1..10")
    try:
        result = pipeline.discover(source=body.source, top_k=body.top_k)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # fail loudly, never silent empty
        raise HTTPException(status_code=500, detail=f"discovery failed: {exc}") from exc
    return {"ok": True, **result}
