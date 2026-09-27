"""Deterministic seed generator.

Target: 142 closed accounts, 87 won / 55 lost, with embedded H17 pattern:
  employees 150-500 + new_vp_sales + sdr_openings>=3 + Salesforce + high intent
  -> 28 accounts, 23 won / 5 lost (82% win vs ~61% baseline)

Run: .venv/bin/python -m backend.seed  (or python backend/seed.py)
Output: data/seed.json {meta, accounts}
Deterministic: random.Random(42). Reruns produce identical file.
"""
import json
import random
from pathlib import Path

SEED = 42
N_TOTAL = 142
N_WON = 87
N_PATTERN = 28
N_PATTERN_WON = 23

COMPANIES = [
    "Northwind", "Acme", "Globex", "Initech", "Umbrella", "Stark", "Wayne",
    "Hooli", "Massive", "Soylent", "Tyrell", "Weyland", "Cyberdyne", "Aperture",
]
INDUSTRIES = ["SaaS", "Fintech", "HealthTech", "Retail", "Manufacturing"]
TECHS = ["Salesforce", "HubSpot", "Pipedrive", "Other"]
REGIONS = ["US", "EU"]
PERSONAS = ["VP Sales", "CRO", "CMO", "Head of Sales"]


def _gen_pattern_account(rng: random.Random, i: int, outcome: str, idx: int) -> dict:
    employees = rng.randint(150, 500)
    return {
        "id": f"ACC{idx:03d}",
        "company": f"{rng.choice(COMPANIES)}-{idx}",
        "industry": rng.choice(["SaaS", "SaaS", "Fintech", "HealthTech"]),
        "employees": employees,
        "region": "US",
        "tech": "Salesforce",
        "new_vp_sales": True,
        "vp_hire_days_ago": rng.randint(5, 90),
        "sdr_openings": rng.randint(3, 6),
        "intent": "high",
        "persona_title": rng.choice(["VP Sales", "CRO"]),
        "outcome": outcome,
        "deal_size": rng.randint(20000, 120000),
        "is_h17_pattern": True,
    }


def _gen_other_account(rng: random.Random, idx: int) -> dict:
    # Random attrs, then break H17 match on at least one dimension.
    employees = rng.choice([
        rng.randint(20, 140), rng.randint(150, 500), rng.randint(501, 1200),
    ])
    new_vp = rng.random() < 0.22
    sdr = rng.choices([0, 1, 2, 3, 4, 5], weights=[30, 25, 18, 12, 9, 6])[0]
    tech = rng.choices(TECHS, weights=[30, 30, 15, 25])[0]
    intent = rng.choices(["high", "medium", "low"], weights=[28, 37, 35])[0]
    # Force-break full H17 conjunction so only seeded 28 match it.
    if employees >= 150 and employees <= 500 and new_vp and sdr >= 3 and tech == "Salesforce" and intent == "high":
        tech = "HubSpot"
    return {
        "id": f"ACC{idx:03d}",
        "company": f"{rng.choice(COMPANIES)}-{idx}",
        "industry": rng.choice(INDUSTRIES),
        "employees": employees,
        "region": rng.choice(REGIONS),
        "tech": tech,
        "new_vp_sales": new_vp,
        "vp_hire_days_ago": rng.randint(5, 200) if new_vp else None,
        "sdr_openings": sdr,
        "intent": intent,
        "persona_title": rng.choice(PERSONAS),
        "outcome": "won",  # placeholder, fixed below
        "deal_size": rng.randint(8000, 120000),
        "is_h17_pattern": False,
    }


def generate() -> dict:
    rng = random.Random(SEED)
    accounts: list[dict] = []
    idx = 1
    # 1. Pattern block: 23 won + 5 lost.
    for _ in range(N_PATTERN_WON):
        accounts.append(_gen_pattern_account(rng, idx, "won", idx))
        idx += 1
    for _ in range(N_PATTERN - N_PATTERN_WON):
        accounts.append(_gen_pattern_account(rng, idx, "lost", idx))
        idx += 1
    # 2. Others: need 64 more wins to reach 87 total.
    n_other = N_TOTAL - N_PATTERN
    n_other_won = N_WON - N_PATTERN_WON
    others = [_gen_other_account(rng, idx + j) for j in range(n_other)]
    # Assign wins with mild signal (non-pattern high-intent slightly more likely),
    # then hard-fix exact counts deterministically.
    scored = []
    for a in others:
        w = 0.5 + (0.15 if a["intent"] == "high" else 0) + (0.05 if a["tech"] == "Salesforce" else 0)
        scored.append((rng.random() - w, a))
    scored.sort(key=lambda x: x[0])
    for k, (_, a) in enumerate(scored):
        a["outcome"] = "won" if k < n_other_won else "lost"
    accounts.extend([a for _, a in scored])
    # 3. Shuffle deterministically so pattern rows aren't clustered.
    rng.shuffle(accounts)
    # Re-id after shuffle to keep ACC001.. sequential in file order.
    for j, a in enumerate(accounts, 1):
        a["id"] = f"ACC{j:03d}"
        a["company"] = f"{a['company'].split('-')[0]}-{j}"

    wins = sum(1 for a in accounts if a["outcome"] == "won")
    assert len(accounts) == N_TOTAL and wins == N_WON, (len(accounts), wins)
    pat = [a for a in accounts if a["is_h17_pattern"]]
    assert len(pat) == N_PATTERN and sum(1 for a in pat if a["outcome"] == "won") == N_PATTERN_WON

    meta = {
        "seed": SEED,
        "n_total": N_TOTAL,
        "n_won": N_WON,
        "n_lost": N_TOTAL - N_WON,
        "h17": {"n": N_PATTERN, "won": N_PATTERN_WON, "note": "embedded discoverable pattern"},
        "fields": ["employees", "new_vp_sales", "sdr_openings", "tech", "intent", "industry", "region", "persona_title"],
    }
    return {"meta": meta, "accounts": accounts}


def main() -> None:
    from . import store
    from .config import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = generate()
    out = DATA_DIR / "seed.json"
    out.write_text(json.dumps(payload, indent=2))
    # Materialize the working copy into the database.
    store.replace_all("accounts", payload["accounts"])
    print(f"wrote {out} ({payload['meta']['n_total']} accounts, {payload['meta']['n_won']} won)")


if __name__ == "__main__":
    main()
