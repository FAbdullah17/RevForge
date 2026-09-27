"""System routes: health + fresh random data + stats. No business logic here."""
from fastapi import APIRouter

from .. import data_loader, seed, store
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
def reset_seed(fixed: bool = False):
    """Load data: fresh random draw by default, deterministic template when fixed.

    Tests use fixed=true; demos and the UI get a new dataset every call.
    """
    if fixed:
        counts = store.reset_all()
        return {"ok": True, "reset": counts, "stats": data_loader.stats(),
                "dataset": {"n": counts["accounts"], "won": data_loader.stats()["won"]}}
    payload = seed.generate()
    payload = seed.generate()
    store.replace_all("accounts", payload["accounts"])
    for name in ("hypotheses", "experiments", "results", "knowledge"):
        store.replace_all(name, [])
    m = payload["meta"]
    counts = {"accounts": m["n_total"], "hypotheses": 0, "experiments": 0,
              "results": 0, "knowledge": 0}
    return {"ok": True, "reset": counts, "stats": data_loader.stats(),
            "dataset": {"n": m["n_total"], "won": m["n_won"]}}
