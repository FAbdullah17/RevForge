"""Historical data loader. Normalizes stored accounts -> pandas DataFrame.

Only module (besides seed.py) that interprets account rows.
Discovery must consume via load_accounts_df(), never raw storage.
"""
import pandas as pd

from . import store
from .models import Account

REQUIRED = ["id", "employees", "new_vp_sales", "sdr_openings", "tech", "intent", "outcome"]


def _read_accounts() -> list[dict]:
    """Working-copy accounts from the database (populated via seed/reset)."""
    return store.list_all("accounts")


def load_accounts_df() -> pd.DataFrame:
    rows = _read_accounts()
    if not rows:
        return pd.DataFrame(columns=REQUIRED)
    # Validate via Pydantic (raises on bad seed — fail fast).
    valid = [Account(**r).model_dump() for r in rows]
    df = pd.DataFrame(valid)
    return df


def stats() -> dict:
    df = load_accounts_df()
    if df.empty:
        return {"n": 0, "won": 0, "lost": 0, "win_rate": 0.0}
    won = int((df["outcome"] == "won").sum())
    n = len(df)
    return {"n": n, "won": won, "lost": n - won, "win_rate": round(won / n, 4)}
