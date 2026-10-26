"""Which funds Bibit's robo holds for each risk profile, as the user typed them in.

The robo's picks are only visible inside the Bibit app (and change over time), so they are entered by hand after each
product-data update and kept as a dated history. The comparison on the Rekomendasi tab uses the newest entry for the
profile being compared; without one it falls back to the three funds seen in the user's screenshots for profiles 4.5
and 5 and says so.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import storage
from .products import ROBO_FUNDS

ROBO_FILE = Path(__file__).parent.parent / "data" / "robo_picks.json"
CONFIRMED_LEVELS = (4.5, 5.0)  # levels whose funds were read from the user's own robo screenshots
SKIP = "(tidak ada / lewati)"


def load(path: Path | None = None) -> list[dict]:
    store = storage.current() if path is None else None
    if store:
        return [e for e in store.list_robo() if "level" in e and "picks" in e]
    path = path or ROBO_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [e for e in data.get("entries", []) if isinstance(e, dict) and "level" in e and "picks" in e]


def save_entry(level: float, picks: dict[str, str], data_as_of: str, path: Path | None = None,
               now: datetime | None = None) -> dict:
    """Append one dated entry (skipped categories are dropped) and return it."""
    store = storage.current() if path is None else None
    path = path or ROBO_FILE
    entry = {
        "level": float(level), "saved_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "data_as_of": data_as_of, "picks": {c: n for c, n in picks.items() if n and n != SKIP},
    }
    if store:
        store.append_robo(entry)
        return entry
    entries = load(path) + [entry]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return entry


def latest(level: float, entries: list[dict]) -> dict | None:
    mine = [e for e in entries if abs(float(e["level"]) - float(level)) < 1e-9]
    return max(mine, key=lambda e: e["saved_at"]) if mine else None


def resolve(level: float, entries: list[dict]) -> tuple[dict[str, str], dict]:
    """(category -> fund name, meta). meta['source'] is 'input', 'screenshot' or 'unverified'."""
    entry = latest(level, entries)
    if entry:
        return dict(entry["picks"]), {"source": "input", "saved_at": entry["saved_at"], "data_as_of": entry["data_as_of"]}
    source = "screenshot" if float(level) in CONFIRMED_LEVELS else "unverified"
    return dict(ROBO_FUNDS), {"source": source, "saved_at": None, "data_as_of": None}


def missing_from(picks: dict[str, str], catalog: pd.DataFrame) -> list[str]:
    """Fund names that are no longer in the product catalog (delisted, renamed or mistyped)."""
    known = set(catalog["name"].astype(str))
    return [n for n in picks.values() if n not in known]


def is_stale(meta: dict, catalog_date: str) -> bool:
    """True when the entry was made for older product data than the catalog now holds."""
    return meta["source"] == "input" and str(meta["data_as_of"]) < str(catalog_date)


def fund_rows(picks: dict[str, str], catalog: pd.DataFrame) -> dict[str, pd.Series]:
    out = {}
    for cat, name in picks.items():
        hit = catalog.loc[catalog["name"] == name]
        if not hit.empty:
            out[cat] = hit.iloc[0]
    return out
