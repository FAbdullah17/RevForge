#!/usr/bin/env bash
# Live graph8 end-to-end: fetch -> enrich -> dry-fire -> SQLite.
# Creates REAL workspace objects ([RevForge TEST] lists, campaign, sequences).
# Sequences are staged, NEVER run: no outreach is sent to anyone.
# Enrichment spends unlock credits (~1/contact); cohorts stay small (10/10).
# Cleanup archives sequences + deletes the campaign (lists have no delete
# endpoint and stay, clearly named). Ends with shared JSON/DB reset to clean.
# Usage: scripts/g8_live_e2e.sh
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
curl -s -X POST "$LIVE/api/seed?fixed=true" > /dev/null
curl -s -X POST "$LIVE/api/discover" -H 'Content-Type: application/json' -d '{"source":"seed","top_k":3}' \
  | $PY -c "import json,sys; assert json.load(sys.stdin)['hypotheses'][0]['id']=='H17'" || fail "discover"

echo "-- approve + live cohorts (10/10, credit-capped) --"
curl -s -X POST "$LIVE/api/hypotheses/H17/approve" > /dev/null
COHORT=$(curl -s -X POST "$LIVE/api/hypotheses/H17/test" -H 'Content-Type: application/json' -d '{"treatment_n":10,"control_n":10}')
echo "$COHORT" | $PY -c "
import json,sys
d = json.load(sys.stdin)
assert d['experiment']['transport'] == 'live', d['experiment']
t, c = d['cohort']['treatment'], d['cohort']['control']
assert t['n'] == 10 and c['n'] == 10 and t['companies_searched'] > 0
assert len(t['contacts']) == 10 and len(c['contacts']) == 10
print('  treatment companies:', t['companies_searched'], '| buyers:', t['buyers_found'])
print('  exp:', d['experiment']['id'])
" || fail "cohorts"
EXP=$(echo "$COHORT" | $PY -c "import json,sys; print(json.load(sys.stdin)['experiment']['id'])")
pass "live cohorts on transport=live"

echo "-- launch: lists + enrich + dry-fire sequences (NEVER run) --"
LAUNCH=$(curl -s -X POST "$LIVE/api/experiments/$EXP/launch")
echo "$LAUNCH" | $PY -c "
import json,sys
e = json.load(sys.stdin)['experiment']
assert e['status'] == 'launched', e
assert e['treatment'].get('sequence_id') and e['control'].get('sequence_id')
assert len(e['treatment'].get('contacts_enriched', [])) == 10
assert e.get('credits_spent', 0) >= 0
print('  campaign:', e['graph8_campaign_id'])
print('  sequences:', e['treatment']['sequence_id'], '/', e['control']['sequence_id'])
print('  credits spent:', e.get('credits_spent'))
" || fail "launch"
CMP=$(echo "$LAUNCH" | $PY -c "import json,sys; print(json.load(sys.stdin)['experiment']['graph8_campaign_id'])")
SEQS=$(echo "$LAUNCH" | $PY -c "import json,sys; e=json.load(sys.stdin)['experiment']; print(e['treatment']['sequence_id'], e['control']['sequence_id'])")
case "$CMP" in cmp-*|list-*) fail "mock id leaked into live run";; esac
pass "launch"

echo "-- sync (live enrollment, zero engagement) + evaluate --"
curl -s -X POST "$LIVE/api/experiments/$EXP/sync-outcomes" \
  | $PY -c "
import json,sys
rows = {r['group']: r for r in json.load(sys.stdin)['results']}
assert set(rows) == {'treatment', 'control'}
assert all(r['source'] == 'live' for r in rows.values()), rows
assert all(r['sent'] > 0 and r['positive'] == 0 for r in rows.values()), rows
print('  enrolled:', {g: r['sent'] for g, r in rows.items()})
" || fail "sync"
curl -s -X POST "$LIVE/api/experiments/$EXP/evaluate" \
  | $PY -c "
import json,sys
v = json.load(sys.stdin)['verdict']
assert v['verdict'] == 'Inconclusive', v  # dry-fire: nothing sent, nothing replied
print('  verdict:', v['verdict'], '-', v['reason'])
" || fail "evaluate"
pass "evaluate (honest dry-fire verdict)"

echo "-- verify SQLite rows --"
$PY -c "
from backend import store
assert len(store.list_all('experiments')) >= 1
assert len(store.results_for('$EXP')) == 2
assert len(store.list_all('knowledge')) == 1
print('  experiments/results/knowledge persisted')
"
pass "sqlite"

echo "-- cleanup: archive sequences, delete campaign --"
source .env 2>/dev/null
$PY -c "
import os, httpx
h = {'Authorization': 'Bearer ' + os.environ['G8_API_KEY']}
with httpx.Client(base_url='https://be.graph8.com/api/v1', timeout=25) as c:
    print('  campaign:', c.delete('/campaigns/$CMP', headers=h).json().get('data'))
" 2>/dev/null || curl -s -m 20 -X DELETE -H "Authorization: Bearer $G8_API_KEY" \
  "https://be.graph8.com/api/v1/campaigns/$CMP" | head -c 200; echo
for S in $SEQS; do
  curl -s -m 20 -X DELETE -H "Authorization: Bearer $G8_API_KEY" \
    "https://be.graph8.com/api/v1/sequences/$S" | head -c 120; echo
done
echo "  NOTE: test lists + asserted contacts stay (no list-delete endpoint); prefixed [RevForge TEST]."

echo "-- reset shared state to clean --"
curl -s -X POST "$LOCAL/api/seed?fixed=true" > /dev/null

END=$(date +%s)
echo "== LIVE E2E PASSED in $((END - START))s =="
