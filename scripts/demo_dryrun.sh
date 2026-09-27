#!/usr/bin/env bash
# RevForge demo dry-run: full loop against a running server with assertions.
# Dataset-agnostic: works on whatever fresh random history /api/seed drew.
# Usage: scripts/demo_dryrun.sh [BASE_URL]
# Exit non-zero on the first failed check. Resets to clean state at the end.
#
# Checks (product success criteria):
#   1. discovery finds an unencoded pattern (top lift > 1.2, evidence coherent)
#   2. hypothesis is explicit (pattern + evidence present)
#   3. graph8 boundary executed (campaign id issued)
#   4. measurable outcome collected (treatment + control rows)
#   5. verdict computed from the result (Validated, lift 2.0 on 50/50 fixtures)
#   6. knowledge stored for future decisions
set -euo pipefail

BASE="${1:-http://127.0.0.1:8000}"
PY=.venv/bin/python
START=$(date +%s)

pass() { echo "  PASS $1"; }
fail() { echo "  FAIL $1"; exit 1; }

echo "== RevForge dry-run @ $BASE =="

echo "-- health --"
HEALTH=$(curl -s "$BASE/health")
echo "$HEALTH" | $PY -c "import json,sys; assert json.load(sys.stdin)['ok']" || fail "health"
echo "$HEALTH" | $PY -c "
import json,sys
d = json.load(sys.stdin)
assert d['mock_graph8'], 'refusing: server is LIVE; mock dry-run would mislead. Use scripts/g8_live_e2e.sh instead.'
" || fail "not mock mode"
pass "backend ok (mock mode confirmed)"

echo "-- seed: fresh random dataset --"
curl -s -X POST "$BASE/api/seed" | $PY -c "
import json,sys
d = json.load(sys.stdin)
print('  dataset:', d['dataset'])
" || fail "seed"

echo "-- 1+2. discover: unencoded pattern -> explicit hypothesis --"
DISC=$(curl -s -X POST "$BASE/api/discover" -H 'Content-Type: application/json' -d '{"source":"seed","top_k":3}')
TOP=$(echo "$DISC" | $PY -c "
import json,sys
hyps = json.load(sys.stdin)['hypotheses']
assert len(hyps) == 3
top = hyps[0]
ev = top['evidence']
assert ev['lift'] > 1.2, ev
assert 0 < ev['wins'] <= ev['support']
assert abs(ev['rate'] - ev['wins'] / ev['support']) < 1e-3
assert top['pattern']
print(top['id'])
print('  top:', top['id'], top['title'], 'lift', ev['lift'], file=sys.stderr)
") || fail "discovery"
pass "discovery (top pick coherent, lift > 1.2)"

echo "-- approve + cohorts --"
curl -s -X POST "$BASE/api/hypotheses/$TOP/approve" > /dev/null || fail "approve"
EXP=$(curl -s -X POST "$BASE/api/hypotheses/$TOP/test" -H 'Content-Type: application/json' -d '{"treatment_n":50,"control_n":50}' \
  | $PY -c "import json,sys; d=json.load(sys.stdin); t=d['cohort']['treatment']; assert t['companies_searched']>0 and t['n']==50; print(d['experiment']['id'])") \
  || fail "cohorts"
echo "  experiment $EXP"
pass "cohorts (50/50)"

echo "-- 3. graph8 execution --"
CMP=$(curl -s -X POST "$BASE/api/experiments/$EXP/launch" \
  | $PY -c "import json,sys; e=json.load(sys.stdin)['experiment']; assert e['status']=='launched'; print(e['graph8_campaign_id'])") \
  || fail "launch"
echo "  campaign $CMP"
pass "launch"

echo "-- 4. outcomes --"
curl -s -X POST "$BASE/api/experiments/$EXP/sync-outcomes" \
  | $PY -c "
import json,sys
rows = {r['group']: r for r in json.load(sys.stdin)['results']}
assert set(rows) == {'treatment', 'control'}
assert (rows['treatment']['positive'], rows['control']['positive']) == (4, 2)
assert all(r['source'] == 'seeded' for r in rows.values())
" || fail "outcomes"
pass "outcomes (4/50 vs 2/50, SEEDED)"

echo "-- 5+6. verdict + knowledge --"
curl -s -X POST "$BASE/api/experiments/$EXP/evaluate" \
  | $PY -c "
import json,sys
d = json.load(sys.stdin)
assert d['verdict']['verdict'] == 'Validated' and d['verdict']['lift'] == 2.0, d['verdict']
assert d['knowledge']['hypothesis_id'] == '$TOP' and d['knowledge']['verdict'] == 'Validated'
" || fail "evaluate"
pass "verdict VALIDATED 2.0x, knowledge stored"

echo "-- reset to clean demo state --"
curl -s -X POST "$BASE/api/seed" > /dev/null || fail "final reset"

END=$(date +%s)
echo "== ALL CHECKS PASSED in $((END - START))s =="
