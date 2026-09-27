"""FastAPI entry. Serves frontend + API."""
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.system import router as system_router
from .api.discovery import router as discovery_router
from .api.hypotheses import router as hypotheses_router
from .api.experiments import router as experiments_router
from .config import CORS_ORIGINS, TEMPLATES_DIR, STATIC_DIR

log = logging.getLogger("revforge")

app = FastAPI(title="RevForge")

# Split deployments (UI on another port): allow the configured origins.
# Single-origin serving needs no CORS headers in practice.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(Exception)
async def unhandled_to_json(request, exc):
    """Demo safety net: never leak a stack trace — always clean JSON."""
    if isinstance(exc, HTTPException):
        raise exc
    log.exception("unhandled %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"ok": False, "detail": "internal error"})

app.include_router(system_router)
app.include_router(discovery_router)
app.include_router(hypotheses_router)
app.include_router(experiments_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    html = (TEMPLATES_DIR / "index.html").read_text()
    return HTMLResponse(html)


@app.get("/health")
def health_root():
    # duplicate for judges curling /health
    from .config import MOCK_GRAPH8, MOCK_LLM

    return {"ok": True, "mock_graph8": MOCK_GRAPH8, "mock_llm": MOCK_LLM}
