# RevForge — Autonomous Revenue Hypothesis Discovery

**Which customers buy the most? RevForge finds out — then proves it.**

Your CRM knows *how* to sell. RevForge discovers *what to sell to next*: it mines
past wins for hidden customer patterns, turns the best one into a testable bet,
runs a real market experiment through graph8 (test group vs comparison group),
and remembers the verdict — validated, disproven, or unclear — as lasting
revenue knowledge.

One loop, end to end:

```text
past deals → hidden pattern → bet → live market test → result → learning → next bet
```

RevForge does **not** replace your CRM, scoring, or campaigns — graph8 already
does all that, and RevForge calls it. It also never fakes certainty:
small samples and dry-fire runs honestly report *Unclear*.

---

## Setup — clone and run locally

Prerequisites: Python 3.11+, Git. Optional: Docker, a graph8 API key.

```bash
# 1. Clone
git clone <repo-url>
cd RevForge

# 2. Environment
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill in G8_API_KEY to use live graph8 data
```

```bash
# 3. Run (API + UI, one process)
.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/** and follow the on-screen steps:
Get data → Find patterns → Review the bet → Run the test → Results.

### Modes

| Env | Default | Meaning |
|---|---|---|
| `MOCK_GRAPH8=1` | yes | Deterministic demo: seeded history, mock market, no side effects |
| `MOCK_GRAPH8=0` | — | Live graph8 market data; launches create real lists/campaigns (prefixed `[RevForge TEST]`); sequences are staged, never run |
| `MOCK_LLM=1` | yes | Template explanations instead of LLM calls |

```bash
# Live mode example (needs G8_API_KEY in .env)
MOCK_GRAPH8=0 .venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000

# Split UI/API across two ports (pass ?api= to the page)
.venv/bin/uvicorn backend.app:app --port 8000 &
.venv/bin/python -m http.server 8001 --directory frontend
# → http://127.0.0.1:8001/templates/index.html?api=http://127.0.0.1:8000

# Docker (single container)
docker build -t revforge .
docker run -p 8000:8000 --env-file .env revforge
```

### Verify it works

```bash
.venv/bin/python -m pytest tests/ -q        # full suite (mock; live tests need G8_LIVE=1)
./scripts/demo_dryrun.sh                     # mock end-to-end against :8000
./scripts/g8_live_e2e.sh                     # live end-to-end (creates + cleans up test objects)
```

### Layout

```text
backend/            FastAPI app, linear agent pipeline, graph8 client, SQLite store
backend/agents/     discovery · hypothesis · prioritization · execution · evaluation
backend/api/        health, discover, hypotheses, experiments, webhooks
frontend/           guided 4-screen UI (no build step)
data/seed.json      deterministic history template (working DB rebuilds from it)
tests/              70+ tests; live ones gated behind G8_LIVE=1
scripts/            demo dry-run + live end-to-end
```

### Notes

* History regenerates fresh on every reset (random size 500–2000, rotating
  hidden winner); the committed seed file is only the deterministic template.
* Live enrichment spends ~1 unlock credit per contact; cohorts stay small by default.
* Runtime state lives in `data/revforge.db` (gitignored); `.env` holds your key (gitignored).
