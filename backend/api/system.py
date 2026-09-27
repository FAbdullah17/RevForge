"""System routes: health + seed reset + stats. No business logic here."""
from fastapi import APIRouter

from .. import data_loader, store
from ..config import MOCK_GRAPH8, MOCK_LLM

router = APIRouter()


@router.get("/health")
def health():
    return {"ok": True, "mock_graph8": MOCK_GRAPH8, "mock_llm": MOCK_LLM}


@router.get("/api/stats")
def get_stats():
    return {"ok": True, "stats": data_loader.stats(), "source": "revforge.db"}


@router.get("/api/accounts")
def list_accounts(limit: int = 10):
    rows = store.list_all("accounts")
    return {"n": len(rows), "accounts": rows[:limit]}


@router.get("/api/knowledge")
def list_knowledge():
    return {"knowledge": store.list_all("knowledge")}


@router.post("/api/seed")
def reset_seed():
    counts = store.reset_all()
    return {"ok": True, "reset": counts, "stats": data_loader.stats()}
