#!/usr/bin/env bash
# Live graph8 end-to-end: full RevForge loop on transport=live.
# Creates REAL workspace objects (2 lists + 1 campaign, "[RevForge TEST]" prefixed).
# The campaign is deleted afterwards; lists have no delete endpoint and stay.
# Usage: scripts/g8_live_e2e.sh
# End state: local JSON reset to clean; :8001 server stopped.
set -euo pipefail

PY=.venv/bin/python
LIVE=http://127.0.0.1:8001
LOCAL=http://127.0.0.1:8000
START=$(date +%s)

pass() { echo "  PASS $1"; }
fail() { echo "  FAIL $1"; exit 1; }
cleanup() { kill "$SRV" 2>/dev/null || true; }
trap cleanup EXIT

echo "== live e2e: starting :8001 with MOCK_GRAPH8=0 =="
MOCK_GRAPH8=0 MOCK_LLM=1 setsid nohup .venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8001 \
  > /tmp/opencode/revforge-live.log 2>&1 < /dev/null &
SRV=$!
for _ in $(seq 1 30); do curl -s -m 2 "$LIVE/health" > /dev/null && break; sleep 1; done
curl -s "$LIVE/health" | $PY -c "import json,sys; d=json.load(sys.stdin); assert d['ok'] and not d['mock_graph8'], d" \
  || fail "live server not in live mode"

echo "-- seed + discover (local history) --"
curl -s -X POST "$LIVE/api/seed" > /dev/null
curl -s -X POST "$LIVE/api/discover" -H 'Content-Type: application/json' -d '{"source":"seed","top_k":3}' \
  | $PY -c "import json,sys; assert json.load(sys.stdin)['hypotheses'][0]['id']=='H17'" || fail "discover"

echo "-- approve + live cohorts (30/30: minimum n for a verdict) --"
curl -s -X POST "$LIVE/api/hypotheses/H17/approve" > /dev/null
COHORT=$(curl -s -X POST "$LIVE/api/hypotheses/H17/test" -H 'Content-Type: application/json' -d '{"treatment_n":30,"control_n":30}')
echo "$COHORT" | $PY -c "
import json,sys
d = json.load(sys.stdin)
assert d['experiment']['transport'] == 'live', d['experiment']
t, c = d['cohort']['treatment'], d['cohort']['control']
assert t['n'] == 30 and c['n'] == 30 and t['companies_searched'] > 0
print('  treatment companies:', t['companies_searched'], '| buyers:', t['buyers_found'])
print('  exp:', d['experiment']['id'])
" || fail "cohorts"
EXP=$(echo "$COHORT" | $PY -c "import json,sys; print(json.load(sys.stdin)['experiment']['id'])")
pass "live cohorts on transport=live"

echo "-- launch (REAL list + campaign) --"
CMP=$(curl -s -X POST "$LIVE/api/experiments/$EXP/launch" \
  | $PY -c "import json,sys; e=json.load(sys.stdin)['experiment']; print(e['graph8_campaign_id'])") || fail "launch"
echo "  campaign: $CMP"
case "$CMP" in cmp-*|list-*) fail "mock id leaked into live run";; esac
pass "launch"

echo "-- sync (seeded fixtures) + evaluate --"
curl -s -X POST "$LIVE/api/experiments/$EXP/sync-outcomes" > /dev/null
curl -s -X POST "$LIVE/api/experiments/$EXP/evaluate" \
  | $PY -c "import json,sys; v=json.load(sys.stdin)['verdict']; assert v['verdict']=='Validated' and 1.9 <= v['lift'] <= 2.1, v; print('  verdict:', v['verdict'], v['lift'])" \
  || fail "evaluate"
pass "evaluate"

echo "-- cleanup: delete test campaign --"
source .env 2>/dev/null
curl -s -m 20 -X DELETE -H "Authorization: Bearer $G8_API_KEY" \
  "https://be.graph8.com/api/v1/campaigns/$CMP" | head -c 200; echo
echo "  NOTE: test lists stay (no list-delete endpoint); prefixed [RevForge TEST]."

echo "-- reset shared JSON to clean --"
curl -s -X POST "$LOCAL/api/seed" > /dev/null

END=$(date +%s)
echo "== LIVE E2E PASSED in $((END - START))s =="
