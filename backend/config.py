"""Central config. Environment-driven; mock transports on by default for deterministic demos."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"

G8_API_KEY = os.getenv("G8_API_KEY", "")
G8_BASE_URL = os.getenv("G8_BASE_URL", "https://be.graph8.com/api/v1")

#: Workspace owner email, required when creating sequencer sequences.
G8_OWNER_EMAIL = os.getenv("G8_OWNER_EMAIL", "")
MOCK_GRAPH8 = os.getenv("MOCK_GRAPH8", "1") == "1"
MOCK_LLM = os.getenv("MOCK_LLM", "1") == "1"
PORT = int(os.getenv("PORT", "8000"))

#: Allowed browser origins when the UI is served separately from the API
#: (single-origin needs none of this). Comma-separated override supported.
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://127.0.0.1:8001,http://localhost:8001").split(",")
    if o.strip()
]

# Reference ICPs for novelty checks: patterns restating these score low novelty.
KNOWN_ICPS = ["US B2B SaaS 100-500 employees"]
