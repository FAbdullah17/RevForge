"""Seed tests: determinism, counts, embedded pattern integrity."""
from backend.seed import generate


def _is_h17(a: dict) -> bool:
    return (
        150 <= a["employees"] <= 500
        and a["new_vp_sales"] is True
        and a["sdr_openings"] >= 3
        and a["tech"] == "Salesforce"
        and a["intent"] == "high"
    )


def test_counts():
    p = generate()
    assert p["meta"]["n_total"] == 142
    assert p["meta"]["n_won"] == 87
    acc = p["accounts"]
    assert len(acc) == 142
    assert sum(1 for a in acc if a["outcome"] == "won") == 87
    assert sum(1 for a in acc if a["outcome"] == "lost") == 55


def test_deterministic():
    assert generate() == generate()


def test_pattern_block():
    p = generate()
    pat = [a for a in p["accounts"] if a["is_h17_pattern"]]
    assert len(pat) == 28
    assert sum(1 for a in pat if a["outcome"] == "won") == 23
    for a in pat:
        assert _is_h17(a)


def test_no_unlabeled_full_match():
    # Only seeded 28 may fully match H17 — discovery must find them, not noise.
    p = generate()
    for a in p["accounts"]:
        if not a["is_h17_pattern"]:
            assert not _is_h17(a), a["id"]


def test_pattern_has_lift():
    p = generate()
    acc = p["accounts"]
    base = sum(1 for a in acc if a["outcome"] == "won") / len(acc)
    pat = [a for a in acc if a["is_h17_pattern"]]
    prate = sum(1 for a in pat if a["outcome"] == "won") / len(pat)
    assert prate > base
    assert prate / base > 1.2  # discoverable lift
