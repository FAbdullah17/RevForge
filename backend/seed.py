"""Revenue-history generator: fresh random mock data on every run.

Each call picks a random dataset size and a random hero pattern to embed
strongly (~20% of accounts, ~82% win rate); remaining patterns stay near
baseline so a different hypothesis wins each run. All four heroes map to
discovery specs, so repeated runs exercise every hypothesis case.

Run: .venv/bin/python -m backend.seed  (writes seed.json + loads the DB)
Tests pin explicit arguments; production calls leave them random.
"""
import json
import random

MIN_N = 500
MAX_N = 2000
FIXED_SEED = 42

COMPANIES = [
    "Northwind", "Acme", "Globex", "Initech", "Umbrella", "Stark", "Wayne",
    "Hooli", "Massive", "Soylent", "Tyrell", "Weyland", "Cyberdyne", "Aperture",
]
INDUSTRIES = ["SaaS", "Fintech", "HealthTech", "Retail", "Manufacturing"]
TECHS = ["Salesforce", "HubSpot", "Pipedrive", "Other"]
REGIONS = ["US", "EU"]
PERSONAS = ["VP Sales", "CRO", "CMO", "Head of Sales"]

#: Hero pattern -> (attribute overrides, discovery spec key it should win).
HEROES = {
    "full_stack": (
        {"employees": (150, 500), "new_vp_sales": True, "sdr_openings": (3, 6),
         "tech": "Salesforce", "intent": "high"},
        "vp_sdr_intent_stack",
    ),
    "sf_midmarket": (
        {"employees": (150, 500), "tech": "Salesforce", "intent": "high"},
        "salesforce_midmarket_intent",
    ),
    "vp_hiring": (
        {"new_vp_sales": True, "sdr_openings": (3, 6)},
        "leadership_hiring_momentum",
    ),
    "high_sf": (
        {"tech": "Salesforce", "intent": "high"},
        "high_intent_salesforce",
    ),
}

HERO_SHARE = 0.20
HERO_WIN_RATE = 0.82


def _break_hero_match(account: dict) -> None:
    """Strip hero conjunctions one dimension at a time; guaranteed to end clean."""
    fixes = [
        lambda a: a.update(tech="HubSpot" if a["tech"] == "Salesforce" else "Other"),
        lambda a: a.update(intent="low" if a["intent"] == "high" else "medium"),
        lambda a: a.update(new_vp_sales=False, vp_hire_days_ago=None),
        lambda a: a.update(sdr_openings=0),
    ]
    for fix in fixes:
        if not _matches_any_hero(account):
            return
        fix(account)
    if _matches_any_hero(account):  # paranoia: a profile no hero can match
        account.update(tech="Other", intent="low", new_vp_sales=False,
                       sdr_openings=0, vp_hire_days_ago=None)


def _hero_predicate(hero: str, a: dict) -> bool:
    """True when an account matches the hero conjunction (leakage guard: never stored)."""
    p, _ = HEROES[hero]
    if "employees" in p and not (p["employees"][0] <= a["employees"] <= p["employees"][1]):
        return False
    if p.get("new_vp_sales") and not a["new_vp_sales"]:
        return False
    if "sdr_openings" in p and not (p["sdr_openings"][0] <= a["sdr_openings"] <= p["sdr_openings"][1]):
        return False
    if "tech" in p and a["tech"] != p["tech"]:
        return False
    if "intent" in p and a["intent"] != p["intent"]:
        return False
    return True


def _matches_any_hero(a: dict) -> bool:
    return any(_hero_predicate(h, a) for h in HEROES)


def _gen_hero_account(rng: random.Random, hero: str, outcome: str, idx: int) -> dict:
    p, _ = HEROES[hero]
    if "employees" in p:
        employees = rng.randint(*p["employees"])
    else:
        # Stay out of the mid-market band so size-based specs can't free-ride.
        employees = rng.choice([rng.randint(20, 140), rng.randint(501, 1200)])
    if "sdr_openings" in p:
        sdr = rng.randint(*p["sdr_openings"])
    else:
        # Stay below the hiring bar so hiring-based specs can't free-ride.
        sdr = rng.randint(0, 2)
    new_vp = True if p.get("new_vp_sales") else False
    return {
        "id": f"ACC{idx:05d}",
        "company": f"{rng.choice(COMPANIES)}-{idx}",
        "industry": rng.choice(["SaaS", "SaaS", "Fintech", "HealthTech"]),
        "employees": employees,
        "region": "US",
        "tech": p.get("tech", rng.choice(TECHS)),
        "new_vp_sales": new_vp,
        "vp_hire_days_ago": rng.randint(5, 90) if new_vp else None,
        "sdr_openings": sdr,
        "intent": p.get("intent", rng.choice(["medium", "low"])),
        "persona_title": rng.choice(["VP Sales", "CRO"]),
        "outcome": outcome,
        "deal_size": rng.randint(20000, 120000),
        "is_hero_pattern": True,
    }


def _gen_other_account(rng: random.Random, idx: int) -> dict:
    employees = rng.choice([
        rng.randint(20, 140), rng.randint(150, 500), rng.randint(501, 1200),
    ])
    new_vp = rng.random() < 0.22
    sdr = rng.choices([0, 1, 2, 3, 4, 5], weights=[30, 25, 18, 12, 9, 6])[0]
    tech = rng.choices(TECHS, weights=[30, 30, 15, 25])[0]
    intent = rng.choices(["high", "medium", "low"], weights=[28, 37, 35])[0]
    account = {
        "id": f"ACC{idx:05d}",
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
        "is_hero_pattern": False,
    }
    # Break every hero conjunction so only seeded heroes match one fully.
    _break_hero_match(account)
    return account


def generate(rng: random.Random | None = None, n: int | None = None,
             hero: str | None = None, win_rate: float | None = None) -> dict:
    """Build one dataset. All-None means a fresh random draw every call.

    Args:
        rng: Random source (pass Random(fixed) for deterministic tests).
        n: Dataset size (default: random choice from SIZES).
        hero: Embedded strong pattern (default: random choice from HEROES).
        win_rate: Overall win rate (default: uniform 0.55–0.65).
    """
    rng = rng or random.Random()
    n = n if n is not None else rng.randint(MIN_N, MAX_N)
    hero = hero or rng.choice(sorted(HEROES))
    win_rate = win_rate if win_rate is not None else rng.uniform(0.55, 0.65)

    n_won = int(n * win_rate)
    hero_n = max(1, min(n, int(n * HERO_SHARE)))
    hero_won = min(int(hero_n * HERO_WIN_RATE), n_won)

    accounts: list[dict] = []
    idx = 1
    for _ in range(hero_won):
        accounts.append(_gen_hero_account(rng, hero, "won", idx))
        idx += 1
    for _ in range(hero_n - hero_won):
        accounts.append(_gen_hero_account(rng, hero, "lost", idx))
        idx += 1
    others = [_gen_other_account(rng, idx + j) for j in range(n - hero_n)]
    scored = []
    for a in others:
        w = 0.5 + (0.15 if a["intent"] == "high" else 0) + (0.05 if a["tech"] == "Salesforce" else 0)
        scored.append((rng.random() - w, a))
    scored.sort(key=lambda x: x[0])
    for k, (_, a) in enumerate(scored):
        a["outcome"] = "won" if k < n_won - hero_won else "lost"
    accounts.extend(a for _, a in scored)
    rng.shuffle(accounts)
    for j, a in enumerate(accounts, 1):
        a["id"] = f"ACC{j:05d}"
        a["company"] = f"{a['company'].split('-')[0]}-{j}"

    wins = sum(1 for a in accounts if a["outcome"] == "won")
    assert len(accounts) == n and wins == n_won, (len(accounts), wins)
    pat = [a for a in accounts if a["is_hero_pattern"]]
    assert len(pat) == hero_n and sum(1 for a in pat if a["outcome"] == "won") == hero_won

    _, spec_key = HEROES[hero]
    meta = {
        "n_total": n,
        "n_won": n_won,
        "n_lost": n - n_won,
        "hero": hero,
        "hero_spec": spec_key,
        "hero_n": hero_n,
        "hero_won": hero_won,
        "fields": ["employees", "new_vp_sales", "sdr_openings", "tech", "intent", "industry", "region", "persona_title"],
    }
    return {"meta": meta, "accounts": accounts}


def main(fixed: bool = True) -> None:
    """Write seed.json + load the DB. Fixed args keep the file deterministic;
    pass fixed=False (or call generate() directly) for a fresh random draw."""
    from . import store
    from .config import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if fixed:
        payload = generate(rng=random.Random(FIXED_SEED), n=2000,
                           hero="full_stack", win_rate=0.6127)
    else:
        payload = generate()
    out = DATA_DIR / "seed.json"
    out.write_text(json.dumps(payload, indent=2))
    store.replace_all("accounts", payload["accounts"])
    m = payload["meta"]
    print(f"wrote {out} ({m['n_total']} accounts, {m['n_won']} won, hero={m['hero']})")


if __name__ == "__main__":
    import sys

    main(fixed="--random" not in sys.argv)
