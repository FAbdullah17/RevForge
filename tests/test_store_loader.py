"""Store + loader tests: reset determinism, fresh-DB safety, validation."""
from backend import store
from backend.config import DATA_DIR
from backend import data_loader


def test_reset_twice_identical():
    r1 = store.reset_all()
    snap = {n: store.list_all(n) for n in ("accounts", "hypotheses", "experiments", "results", "knowledge")}
    r2 = store.reset_all()
    assert r1 == r2
    for n in snap:
        assert store.list_all(n) == snap[n]


def test_reset_restores_accounts_from_seed():
    counts = store.reset_all()
    assert counts["accounts"] == 142
    assert counts["hypotheses"] == 0
    rows = store.list_all("accounts")
    assert len(rows) == 142


def test_fresh_db_recreated(tmp_path):
    # Point store at a missing file — tables are created, reads return [].
    real_db = DATA_DIR / "revforge.db"
    try:
        store._db_path_for_tests(tmp_path / "fresh.db")
        assert store.list_all("hypotheses") == []
        assert (tmp_path / "fresh.db").exists()
    finally:
        store._db_path_for_tests(real_db)


def test_loader_stats_match_seed():
    store.reset_all()
    s = data_loader.stats()
    assert s == {"n": 142, "won": 87, "lost": 55, "win_rate": round(87 / 142, 4)}


def test_loader_validates_and_exposes_frame():
    store.reset_all()
    df = data_loader.load_accounts_df()
    assert len(df) == 142
    for c in ("employees", "new_vp_sales", "sdr_openings", "tech", "intent", "outcome"):
        assert c in df.columns
    assert set(df["outcome"].unique()) <= {"won", "lost"}


def test_upsert():
    store.reset_all()
    row = {"id": "H1", "title": "t"}
    store.upsert("hypotheses", row)
    row2 = {"id": "H1", "title": "t2"}
    store.upsert("hypotheses", row2)
    rows = store.list_all("hypotheses")
    assert len(rows) == 1 and rows[0]["title"] == "t2"
    # cleanup
    store.replace_all("hypotheses", [])
