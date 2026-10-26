"""Catalog of funds sold on Bibit, loaded from data/products.csv (a dated snapshot of bibit.id/reksadana)."""
from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path

import pandas as pd

PRODUCTS_FILE = Path(__file__).parent.parent / "data" / "products.csv"
REQUIRED_COLUMNS = ["product_id", "name", "category", "as_of", "aum_idr", "return_1y_pct", "return_3y_pct", "drawdown_1y_pct",
                    "syariah_dari_nama"]
MIN_USABLE_FUNDS = 5   # fewer rows than this cannot produce a meaningful recommendation
RESTORABLE = ("products.csv", "obligasi_fr.csv", "sbn_ritel.csv", "instrumen_sbn_fr.csv", "sbn_berikutnya.json")

# Funds used by Bibit's robo for the Dana Pensiun goal (seen in the user's screenshot), per category.
ROBO_FUNDS = {
    "pasar_uang": "Sucorinvest Money Market Fund",
    "pendapatan_tetap": "ABF Indonesia Bond Index Fund",
    "saham": "BNI-AM Indeks IDX30",
}


SYARIAH_WORDS = re.compile(r"syariah|sharia|islam", re.I)


def is_syariah(name: str) -> bool:
    """Guess from the product name only: 'Syariah' and the English 'Sharia' spelling both count.

    The official sharia status (OJK / DSN-MUI) is not in the data, so this is a guess and says so in the app.
    """
    return bool(SYARIAH_WORDS.search(str(name)))


PROSPECTUS_FILE = PRODUCTS_FILE.parent / "prospectus.csv"
PROSPECTUS_SHOWN = ["position_date", "reconciled", "gov_pct", "corp_pct", "investment_grade_pct", "unrated_pct", "wam_years",
                    "ratings", "policy", "file", "url", "fetched"]


def load_prospectus() -> pd.DataFrame | None:
    """Facts read from prospectuses (data/prospectus.csv), or None when the file is missing, empty or unreadable."""
    try:
        if not PROSPECTUS_FILE.exists() or PROSPECTUS_FILE.stat().st_size == 0:
            return None
        df = pd.read_csv(PROSPECTUS_FILE)
    except Exception:  # a broken optional file must never take the app down
        return None
    return df if "product_id" in df.columns and not df.empty else None


def load_products() -> pd.DataFrame:
    df = pd.read_csv(PRODUCTS_FILE)
    if "name" in df.columns:  # recomputed on every load, so an older snapshot gets the corrected rule without a new refresh
        df["syariah_dari_nama"] = ["ya" if is_syariah(n) else "tidak" for n in df["name"]]
    pros = load_prospectus()
    if pros is not None and "product_id" in df.columns:
        keep = pros[["product_id"] + [c for c in PROSPECTUS_SHOWN if c in pros.columns]].drop_duplicates("product_id")
        df = df.merge(keep.rename(columns={c: f"pros_{c}" for c in PROSPECTUS_SHOWN}), on="product_id", how="left")
    return df


def check_catalog(df: pd.DataFrame) -> str | None:
    """None when the fund table can drive the app, else a plain-language reason it cannot."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return f"Kolom wajib tidak ada di products.csv: {', '.join(missing)}."
    if df.empty:
        return "products.csv tidak berisi satu pun reksa dana (hanya baris judul)."
    if len(df) < MIN_USABLE_FUNDS:
        return f"products.csv hanya berisi {len(df)} reksa dana, terlalu sedikit untuk membuat rekomendasi."
    try:
        date.fromisoformat(str(df["as_of"].iloc[0]))
    except ValueError:
        return f"Tanggal data (kolom as_of) tidak valid: '{df['as_of'].iloc[0]}'."
    return None


def try_load_products() -> tuple[pd.DataFrame | None, str | None]:
    """(catalog, None) when usable, otherwise (None, reason). Never raises, so the app can show a recovery screen."""
    if not PRODUCTS_FILE.exists():
        return None, "File products.csv tidak ditemukan di folder data."
    try:
        df = pd.read_csv(PRODUCTS_FILE)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, OSError, UnicodeDecodeError) as e:
        return None, f"products.csv tidak bisa dibaca ({type(e).__name__})."
    reason = check_catalog(df)
    return (None, reason) if reason else (df, None)


def _read_optional(name: str) -> pd.DataFrame:
    """A side table (SBN, FR, instruments): an empty frame instead of an error when the file is missing or blank."""
    path = PRODUCTS_FILE.with_name(name)
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def list_archives(archive_dir: Path | None = None) -> list[dict]:
    """Old snapshots saved by the refresh (newest first) whose fund table is still usable."""
    root = archive_dir or PRODUCTS_FILE.with_name("archive")
    out = []
    for folder in sorted((d for d in root.glob("*") if d.is_dir()), key=lambda d: d.name, reverse=True) if root.exists() else []:
        try:
            df = pd.read_csv(folder / "products.csv")
        except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
            continue
        if check_catalog(df) is None:
            out.append({"name": folder.name, "as_of": str(df["as_of"].iloc[0]), "funds": len(df), "path": folder})
    return out


def restore_archive(folder: Path, target_dir: Path | None = None) -> list[str]:
    """Copy a snapshot's files back into data/. Each file is replaced atomically; returns the names restored."""
    target = target_dir or PRODUCTS_FILE.parent
    restored = []
    for name in RESTORABLE:
        src = folder / name
        if src.exists():
            tmp = target / f"{name}.tmp"
            shutil.copy2(src, tmp)
            tmp.replace(target / name)
            restored.append(name)
    return restored


def load_sbn() -> pd.DataFrame:
    """SBN Ritel series already issued on Bibit (primary market: only buyable during the offering period)."""
    return _read_optional("sbn_ritel.csv")


def load_next_sbn() -> dict | None:
    """The next SBN offering announced on bibit.id/sbn, or None when it has not been recorded."""
    path = PRODUCTS_FILE.with_name("sbn_berikutnya.json")
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


def load_fr() -> pd.DataFrame:
    """Obligasi FR series listed on Bibit (secondary market: tradable any time, price moves)."""
    return _read_optional("obligasi_fr.csv")


def load_instruments() -> pd.DataFrame:
    """Characteristics of each SBN/FR instrument type as stated on bibit.id."""
    return _read_optional("instrumen_sbn_fr.csv")


def robo_shocks(products: pd.DataFrame, robo_funds: dict[str, str] | None = None) -> dict[str, float]:
    """Observed 1-year drawdown (negative fraction) of each robo fund, keyed by category.

    Past drawdown only: the next bad year can be worse. Missing funds are skipped.
    """
    shocks = {}
    for category, name in (robo_funds or ROBO_FUNDS).items():
        row = products.loc[products["name"] == name]
        if not row.empty and pd.notna(row.iloc[0]["drawdown_1y_pct"]):
            shocks[category] = float(row.iloc[0]["drawdown_1y_pct"]) / 100.0
    return shocks
