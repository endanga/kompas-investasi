"""Database storage for the user's own data: holdings, transactions, saved recommendations and robo picks.

The same code runs on SQLite (a local file, handy for trying it out) and PostgreSQL (Supabase, Neon, ...), because it is
written with SQLAlchemy Core and only portable statements. Product catalogue files are NOT stored here: they are public
data that ships with the app (data/*.csv) and is refreshed from a computer with a browser.

With no database configured, `current()` returns None and every caller keeps using the files in data/.
"""
from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd
import sqlalchemy as sa

from . import settings

HOLDINGS_COLS = ["product", "category", "current_value"]
TX_COLS = ["date", "product", "category", "type", "amount"]

metadata = sa.MetaData()
holdings_t = sa.Table(
    "holdings", metadata, sa.Column("product", sa.String, primary_key=True), sa.Column("category", sa.String, nullable=False),
    sa.Column("current_value", sa.Float, nullable=False))
transactions_t = sa.Table(
    "transactions", metadata, sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("date", sa.String(10), nullable=False), sa.Column("product", sa.String, nullable=False),
    sa.Column("category", sa.String, nullable=False), sa.Column("type", sa.String(4), nullable=False),
    sa.Column("amount", sa.Float, nullable=False))
recommendations_t = sa.Table(
    "recommendations", metadata, sa.Column("name", sa.String, primary_key=True), sa.Column("saved_at", sa.String, nullable=False),
    sa.Column("snapshot", sa.JSON, nullable=False))
robo_t = sa.Table(
    "robo_picks", metadata, sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("level", sa.Float, nullable=False), sa.Column("saved_at", sa.String, nullable=False),
    sa.Column("data_as_of", sa.String, nullable=False), sa.Column("picks", sa.JSON, nullable=False))


def _as_dict(value) -> dict:
    return json.loads(value) if isinstance(value, str) else dict(value)


class SqlStore:
    def __init__(self, url: str):
        self.url = url
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("postgresql"):
            # Supabase/Neon poolers run in transaction mode, which cannot reuse server-side prepared statements.
            kwargs["connect_args"] = {"prepare_threshold": None}
        if url.endswith(":memory:") or url == "sqlite://":
            kwargs.update(poolclass=sa.pool.StaticPool, connect_args={"check_same_thread": False})
        self.engine = sa.create_engine(url, **kwargs)
        self.init_schema()

    @property
    def dialect(self) -> str:
        return self.engine.dialect.name

    def label(self) -> str:
        return {"postgresql": "Database PostgreSQL", "sqlite": "Database SQLite"}.get(self.dialect, f"Database {self.dialect}")

    def init_schema(self) -> None:
        metadata.create_all(self.engine)
        if self.dialect == "postgresql":
            # Row level security with no policy: the public Supabase REST API can never read these tables.
            with self.engine.begin() as conn:
                for table in metadata.tables:
                    conn.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))

    # ------------------------------------------------------------------ holdings and transactions
    def read_holdings(self) -> pd.DataFrame:
        with self.engine.connect() as conn:
            rows = conn.execute(sa.select(*[holdings_t.c[c] for c in HOLDINGS_COLS]).order_by(holdings_t.c.product)).fetchall()
        return pd.DataFrame([tuple(r) for r in rows], columns=HOLDINGS_COLS).astype({"current_value": "float64"})

    def write_holdings(self, df: pd.DataFrame) -> None:
        rows = [{"product": str(r.product), "category": str(r.category), "current_value": float(r.current_value)}
                for r in df[HOLDINGS_COLS].itertuples(index=False)]
        with self.engine.begin() as conn:  # replace as one transaction: a failure leaves the old rows intact
            conn.execute(sa.delete(holdings_t))
            if rows:
                conn.execute(sa.insert(holdings_t), rows)

    def read_transactions(self) -> pd.DataFrame:
        with self.engine.connect() as conn:
            rows = conn.execute(sa.select(*[transactions_t.c[c] for c in TX_COLS]).order_by(
                transactions_t.c.date, transactions_t.c.id)).fetchall()
        return pd.DataFrame([tuple(r) for r in rows], columns=TX_COLS).astype({"amount": "float64"})

    def write_transactions(self, df: pd.DataFrame) -> None:
        rows = [{"date": str(r.date)[:10], "product": str(r.product), "category": str(r.category), "type": str(r.type),
                 "amount": float(r.amount)} for r in df[TX_COLS].itertuples(index=False)]
        with self.engine.begin() as conn:
            conn.execute(sa.delete(transactions_t))
            if rows:
                conn.execute(sa.insert(transactions_t), rows)

    # ------------------------------------------------------------------ saved recommendations
    def save_recommendation(self, snap: dict, name: str) -> str:
        with self.engine.begin() as conn:
            conn.execute(sa.delete(recommendations_t).where(recommendations_t.c.name == name))
            conn.execute(sa.insert(recommendations_t), {"name": name, "saved_at": snap["saved_at"], "snapshot": snap})
        return name

    def list_recommendations(self) -> list[dict]:
        """Newest first, each with the same '_file' key the file backend sets."""
        with self.engine.connect() as conn:
            rows = conn.execute(sa.select(recommendations_t.c.name, recommendations_t.c.snapshot).order_by(
                recommendations_t.c.saved_at.desc())).fetchall()
        out = []
        for name, snap in rows:
            item = _as_dict(snap)
            item["_file"] = name
            out.append(item)
        return out

    # ------------------------------------------------------------------ robo picks
    def list_robo(self) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(sa.select(robo_t.c.level, robo_t.c.saved_at, robo_t.c.data_as_of, robo_t.c.picks).order_by(
                robo_t.c.saved_at, robo_t.c.id)).fetchall()
        return [{"level": lv, "saved_at": at, "data_as_of": d, "picks": _as_dict(p)} for lv, at, d, p in rows]

    def append_robo(self, entry: dict) -> None:
        with self.engine.begin() as conn:
            conn.execute(sa.insert(robo_t), {k: entry[k] for k in ("level", "saved_at", "data_as_of", "picks")})


@lru_cache(maxsize=4)
def _store_for(url: str) -> SqlStore:
    return SqlStore(url)


def current() -> SqlStore | None:
    """The configured database store, or None when the app should use local files."""
    url = settings.database_url()
    return _store_for(url) if url else None


def describe() -> str:
    store = current()
    return store.label() if store else "File lokal (folder data)"
