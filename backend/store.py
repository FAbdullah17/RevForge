"""Persistence layer. SQLite via SQLAlchemy, same function names throughout.

Single file database at ``data/revforge.db`` (WAL-capable, zero ops):
atomic transactions replace the old full-file JSON rewrites, so multiple
server processes can safely share one working copy. Each collection is a
table holding the validated row dict as JSON plus the columns we query
on (ids, status, linkage). ``seed.json`` stays a plain file — it is
canonical demo input, not runtime state.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, create_engine, delete, select

from .config import DATA_DIR

DB_PATH = DATA_DIR / "revforge.db"

metadata = MetaData()


def _collection(name: str, *keys: str) -> Table:
    """A document table: seq preserves insertion order, keys are queryable."""
    cols = [Column("seq", Integer, primary_key=True, autoincrement=True),
            Column("data", JSON, nullable=False)]
    cols += [Column(k, String, index=True) for k in keys]
    return Table(name, metadata, *cols)


ACCOUNTS = _collection("accounts", "id")
HYPOTHESES = _collection("hypotheses", "id", "status")
EXPERIMENTS = _collection("experiments", "id", "hypothesis_id", "status")
RESULTS = _collection("results", "experiment_id", "group")
KNOWLEDGE = _collection("knowledge", "id", "hypothesis_id")

TABLES = {
    "accounts": (ACCOUNTS, ["id"]),
    "hypotheses": (HYPOTHESES, ["id", "status"]),
    "experiments": (EXPERIMENTS, ["id", "hypothesis_id", "status"]),
    "results": (RESULTS, ["experiment_id", "group"]),
    "knowledge": (KNOWLEDGE, ["id", "hypothesis_id"]),
}

_ENGINE = None


def _engine():
    """Process-wide engine (check_same_thread off: uvicorn serves threaded)."""
    global _ENGINE
    if _ENGINE is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _ENGINE = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
        metadata.create_all(_ENGINE)
    return _ENGINE


def _reset_engine() -> None:
    """Drop the cached engine (tests pointing at a temp DB)."""
    global _ENGINE
    if _ENGINE is not None:
        _ENGINE.dispose()
        _ENGINE = None


def _key_values(name: str, row: dict[str, Any]) -> dict[str, Any]:
    _, keys = TABLES[name]
    return {k: (str(row[k]) if row.get(k) is not None else None) for k in keys}


def list_all(name: str) -> list[dict[str, Any]]:
    """All rows of a collection, in insertion order."""
    table, _ = TABLES[name]
    with _engine().connect() as conn:
        rows = conn.execute(select(table.c.data).order_by(table.c.seq)).all()
    return [dict(r[0]) for r in rows]


def insert(name: str, row: dict[str, Any]) -> dict[str, Any]:
    """Append one row."""
    table, _ = TABLES[name]
    with _engine().begin() as conn:
        conn.execute(table.insert().values(data=dict(row), **_key_values(name, row)))
    return row


def upsert(name: str, row: dict[str, Any], key: str = "id") -> dict[str, Any]:
    """Replace the row with the same key, or append when absent."""
    table, keys = TABLES[name]
    if key not in keys:
        raise ValueError(f"cannot upsert {name!r} on non-key {key!r}")
    with _engine().begin() as conn:
        existing = conn.execute(
            select(table.c.seq).where(table.c[key] == str(row.get(key)))
        ).first()
        if existing:
            conn.execute(
                table.update().where(table.c[key] == str(row.get(key))).values(
                    data=dict(row), **_key_values(name, row))
            )
        else:
            conn.execute(table.insert().values(data=dict(row), **_key_values(name, row)))
    return row


def replace_all(name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Atomically replace a collection (one transaction)."""
    table, _ = TABLES[name]
    with _engine().begin() as conn:
        conn.execute(delete(table))
        if rows:
            conn.execute(table.insert(), [
                {"data": dict(r), **_key_values(name, r)} for r in rows
            ])
    return list(rows)


def save_results(experiment_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Idempotent per-experiment write: replace this experiment's rows only."""
    with _engine().begin() as conn:
        conn.execute(delete(RESULTS).where(RESULTS.c.experiment_id == experiment_id))
        if rows:
            conn.execute(RESULTS.insert(), [
                {"data": dict(r), "experiment_id": experiment_id,
                 "group": str(r.get("group"))} for r in rows
            ])
    return results_for(experiment_id)


def results_for(experiment_id: str) -> list[dict[str, Any]]:
    """All result rows for one experiment (treatment + control)."""
    with _engine().connect() as conn:
        rows = conn.execute(
            select(RESULTS.c.data)
            .where(RESULTS.c.experiment_id == experiment_id)
            .order_by(RESULTS.c.seq)
        ).all()
    return [dict(r[0]) for r in rows]


def reset_all(empty: bool = True) -> dict[str, int]:
    """Reset working collections. Accounts are restored from seed.json."""
    seed_path = DATA_DIR / "seed.json"
    seed_accounts: list[dict[str, Any]] = []
    if seed_path.exists():
        try:
            payload = json.loads(seed_path.read_text())
            seed_accounts = payload["accounts"] if isinstance(payload, dict) else payload
        except (json.JSONDecodeError, KeyError):
            seed_accounts = []
    replace_all("accounts", seed_accounts)
    counts = {"accounts": len(seed_accounts)}
    for name in ("hypotheses", "experiments", "results", "knowledge"):
        replace_all(name, [])
        counts[name] = 0
    return counts


def _db_path_for_tests(path: Path) -> None:
    """Point the store at another file (tests only)."""
    global DB_PATH
    DB_PATH = path
    _reset_engine()
