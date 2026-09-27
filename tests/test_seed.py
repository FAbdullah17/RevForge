"""Seed tests: fixed-arg determinism, random-draw variety, hero integrity."""
import random

import pandas as pd

from backend.agents import discovery
from backend.models import Account
from backend.seed import FIXED_SEED, HEROES, MAX_N, MIN_N, _hero_predicate, generate


def test_fixed_args_deterministic():
    def build():
        return generate(rng=random.Random(FIXED_SEED), n=2000, hero="full_stack", win_rate=0.61)
    assert build() == build()


def test_counts_match_args():
    p = generate(rng=random.Random(7), n=1700, hero="sf_midmarket", win_rate=0.58)
    acc = p["accounts"]
    assert len(acc) == 1700 == p["meta"]["n_total"]
    assert sum(1 for a in acc if a["outcome"] == "won") == int(1700 * 0.58)
    assert p["meta"]["hero"] == "sf_midmarket"
    assert p["meta"]["hero_spec"] == HEROES["sf_midmarket"][1]


def test_hero_block_integrity():
    p = generate(rng=random.Random(11), n=2000, hero="vp_hiring", win_rate=0.6)
    pat = [a for a in p["accounts"] if a["is_hero_pattern"]]
    assert len(pat) == max(10, int(2000 * 0.20))
    assert sum(1 for a in pat if a["outcome"] == "won") == int(len(pat) * 0.82)
    for a in pat:
        assert _hero_predicate("vp_hiring", a)


def test_no_unlabeled_hero_match():
    p = generate(rng=random.Random(13), n=1000, hero="high_sf", win_rate=0.6)
    for a in p["accounts"]:
        if not a["is_hero_pattern"]:
            assert not _hero_predicate("high_sf", a), a["id"]


def test_hero_has_lift():
    p = generate(rng=random.Random(17), n=2000, hero="full_stack", win_rate=0.61)
    acc = p["accounts"]
    base = sum(1 for a in acc if a["outcome"] == "won") / len(acc)
    pat = [a for a in acc if a["is_hero_pattern"]]
    prate = sum(1 for a in pat if a["outcome"] == "won") / len(pat)
    assert prate / base > 1.2  # discoverable lift


def test_every_hero_wins_its_run():
    """Each embedded hero must top discovery: repeated runs cover all cases."""
    for i, (hero, (_, spec)) in enumerate(HEROES.items()):
        p = generate(rng=random.Random(1000 + i), n=2000, hero=hero, win_rate=0.61)
        df = pd.DataFrame([Account(**r).model_dump() for r in p["accounts"]])
        top = discovery.find_patterns(df, top_k=3)
        assert top and top[0].key == spec, (hero, [c.key for c in top])


def test_random_draws_vary_and_stay_valid():
    seen_sizes, seen_heroes = set(), set()
    for i in range(6):
        p = generate(rng=random.Random(5000 + i))
        m = p["meta"]
        assert MIN_N <= m["n_total"] <= MAX_N
        assert m["hero"] in HEROES
        assert m["n_won"] + m["n_lost"] == m["n_total"]
        seen_sizes.add(m["n_total"])
        seen_heroes.add(m["hero"])
    assert len(seen_heroes) > 1  # rotation actually happens
