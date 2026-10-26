"""Saved recommendations: a dated record of what the system advised, so a later run (with refreshed product data)
can show what changed. One JSON file per save in data/recommendations/."""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import storage

HISTORY_DIR = Path(__file__).parent.parent / "data" / "recommendations"
PICK_FIELDS = ["product_id", "name", "return_1y_pct", "return_3y_pct", "drawdown_1y_pct", "aum_idr", "score",
               "alasan", "url", "held_idr"]


def _clean(value):
    """JSON-safe scalar: NaN/NumPy numbers become None/float/int."""
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def snapshot(rec, inputs: dict, data_as_of: str, note: str = "", now: datetime | None = None,
             projection: dict | None = None, portfolio: dict | None = None) -> dict:
    """Plain-dict record of a Recommendation plus the inputs and data date that produced it.

    `projection` ({"inflation": float, "rates": {scenario: annual blended rate}}) is kept so a saved record can be
    turned into a report later with the assumptions it was made with."""
    now = now or datetime.now()
    snap = {
        "saved_at": now.isoformat(timespec="seconds"),
        "data_as_of": data_as_of,
        "note": note.strip(),
        "inputs": {k: _clean(v) for k, v in inputs.items()},
        "profile": {"key": rec.profile_key, "level": rec.level, "name": rec.profile_key.split("_", 2)[-1]},
        "allocation": {c: float(s) for c, s in rec.allocation.items()},
        "monthly_amounts": {c: float(a) for c, a in rec.monthly_amounts.items()},
        "stress_loss": float(rec.stress_loss),
        "within_limit": bool(rec.within_limit),
        "picks": {
            cat: [{f: _clean(row.get(f)) for f in PICK_FIELDS} for _, row in df.iterrows()]
            for cat, df in rec.picks.items()
        },
    }
    if rec.notes:
        snap["notes"] = list(rec.notes)
    if portfolio:
        snap["portfolio"] = portfolio
    if projection:
        snap["projection"] = {"inflation": float(projection["inflation"]),
                              "rates": {k: float(v) for k, v in projection["rates"].items()}}
    return snap


def save(snap: dict, directory: Path | None = None) -> Path:
    """Store a snapshot (database when one is configured, else a JSON file). Returns a path whose .name identifies it."""
    stamp = datetime.fromisoformat(snap["saved_at"]).strftime("%Y-%m-%d_%H%M%S")
    store = storage.current() if directory is None else None
    if store:
        return Path(store.save_recommendation(snap, f"{stamp}.json"))
    directory = directory or HISTORY_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stamp}.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_saved(directory: Path | None = None) -> list[dict]:
    """All saved recommendations, newest first. Unreadable files are skipped."""
    store = storage.current() if directory is None else None
    if store:
        return store.list_recommendations()
    directory = directory or HISTORY_DIR
    if not directory.exists():
        return []
    out = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
            snap["_file"] = path.name
            out.append(snap)
        except (OSError, json.JSONDecodeError):
            continue
    return out


def compare(old: dict, new: dict, catalog: pd.DataFrame | None = None) -> list[dict]:
    """Per category: the old top pick vs the new one, and whether the old pick is still sold / still ranked."""
    still_sold = set(catalog["product_id"]) if catalog is not None else None
    rows = []
    for cat in dict.fromkeys([*old["picks"], *new["picks"]]):
        old_picks, new_picks = old["picks"].get(cat, []), new["picks"].get(cat, [])
        old_top = old_picks[0] if old_picks else None
        new_top = new_picks[0] if new_picks else None
        if old_top is None:
            status = "kategori baru"
        elif new_top is None:
            status = "kategori hilang"
        elif old_top["product_id"] == new_top["product_id"]:
            status = "sama"
        else:
            status = "berubah"
        rank_now = None
        if old_top is not None:
            ids = [p["product_id"] for p in new_picks]
            rank_now = ids.index(old_top["product_id"]) + 1 if old_top["product_id"] in ids else None
        rows.append({
            "kategori": cat,
            "produk_utama_lama": old_top["name"] if old_top else None,
            "produk_utama_sekarang": new_top["name"] if new_top else None,
            "status": status,
            "peringkat_lama_sekarang": rank_now,  # 1-3 if the old pick is still in the top 3, else None
            "masih_dijual": None if (old_top is None or still_sold is None) else old_top["product_id"] in still_sold,
        })
    return rows


def describe_changes(old: dict, new: dict, rows: list[dict]) -> list[str]:
    """Plain-language bullets: what is different now compared with the saved recommendation."""
    notes = []
    if old["profile"]["key"] != new["profile"]["key"]:
        notes.append(f"Profil risiko berubah dari {old['profile']['level']:g} ke {new['profile']['level']:g}.")
    if old["data_as_of"] != new["data_as_of"]:
        notes.append(f"Data produk berbeda: rekomendasi lama memakai data {old['data_as_of']}, sekarang {new['data_as_of']}.")
    for r in rows:
        if r["status"] == "berubah":
            tail = ""
            if r["masih_dijual"] is False:
                tail = " (produk lama sudah tidak dijual di Bibit)"
            elif r["peringkat_lama_sekarang"]:
                tail = f" (produk lama sekarang peringkat {r['peringkat_lama_sekarang']})"
            else:
                tail = " (produk lama keluar dari 3 besar)"
            notes.append(f"{r['kategori']}: {r['produk_utama_lama']} → {r['produk_utama_sekarang']}{tail}.")
    if not notes:
        notes.append("Tidak ada perubahan pada produk utama maupun profil risiko.")
    return notes
