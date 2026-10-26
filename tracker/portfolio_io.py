"""Reading, checking and saving the user's portfolio files (data/holdings.csv and data/transactions.csv).

Every entry point (CSV upload, manual form, table editor) goes through the same validators so a bad row is rejected with
a plain message instead of silently reaching the recommender. Pure pandas: no Streamlit here, so it is easy to test.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import storage

CATEGORIES = ["pasar_uang", "pendapatan_tetap", "campuran", "saham", "sbn"]
HOLDINGS_COLS = ["product", "category", "current_value"]
TX_COLS = ["date", "product", "category", "type", "amount"]
TX_TYPES = ["BUY", "SELL"]
DATA_DIR = Path(__file__).parent.parent / "data"
ARCHIVE_DIR = DATA_DIR / "archive"

HOLDINGS_TEMPLATE = "product,category,current_value\nContoh Reksa Dana Pasar Uang,pasar_uang,1500000\n"
TX_TEMPLATE = "date,product,category,type,amount\n2026-09-05,Contoh Reksa Dana Pasar Uang,pasar_uang,BUY,500000\n"

_ALIASES = {  # tolerated header spellings in uploaded files
    "produk": "product", "nama": "product", "nama_produk": "product", "kategori": "category", "jenis": "category",
    "nilai": "current_value", "nilai_sekarang": "current_value", "value": "current_value",
    "tanggal": "date", "tipe": "type", "nominal": "amount", "jumlah": "amount",
}
_CATEGORY_ALIASES = {
    "pasar uang": "pasar_uang", "obligasi": "pendapatan_tetap", "pendapatan tetap": "pendapatan_tetap",
    "campuran": "campuran", "saham": "saham", "sbn": "sbn",
    "pu": "pasar_uang", "pt": "pendapatan_tetap", "rdpu": "pasar_uang", "rdpt": "pendapatan_tetap",
    "rdc": "campuran", "rds": "saham",
}


def parse_amount(value) -> float | None:
    """'Rp1.500.000' / '1.500.000' / '1,500,000' / '1500000.50' / 1500000 -> float. None if it is not a number."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"(?i)rp|\s", "", str(value))
    if not text:
        return None
    if re.fullmatch(r"-?\d{1,3}([.,]\d{3})+", text):          # thousands separators only
        text = re.sub(r"[.,]", "", text)
    elif "," in text and "." in text:                          # 1.500.000,50 or 1,500,000.50
        dec = "," if text.rfind(",") > text.rfind(".") else "."
        text = text.replace("," if dec == "." else ".", "").replace(dec, ".")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def normalize_category(value) -> str | None:
    text = str(value).strip().lower().replace("-", "_")
    if text in CATEGORIES:
        return text
    return _CATEGORY_ALIASES.get(text.replace("_", " "))


def read_csv_bytes(raw: bytes) -> pd.DataFrame:
    """Parse an uploaded CSV (comma, semicolon or tab separated; UTF-8 with or without BOM) with normalised headers."""
    text = raw.decode("utf-8-sig", errors="replace")
    df = pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str, skip_blank_lines=True)
    df.columns = [_ALIASES.get(c.strip().lower().replace(" ", "_"), c.strip().lower().replace(" ", "_")) for c in df.columns]
    return df


def detect_kind(df: pd.DataFrame) -> str | None:
    cols = set(df.columns)
    if {"current_value", "product"} <= cols:
        return "holdings"
    if {"date", "type", "amount", "product"} <= cols:
        return "transactions"
    return None


def clean_holdings(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Valid holdings (one row per product, values summed if repeated) and a list of problems found."""
    errors: list[str] = []
    missing = [c for c in HOLDINGS_COLS if c not in df.columns]
    if missing:
        return pd.DataFrame(columns=HOLDINGS_COLS), [f"Kolom tidak ada: {', '.join(missing)}."]
    rows = []
    for i, row in df.reset_index(drop=True).iterrows():
        n = i + 2  # header is line 1
        name = "" if pd.isna(row["product"]) else str(row["product"]).strip()
        cat = normalize_category(row["category"])
        value = parse_amount(row["current_value"])
        if not name:
            errors.append(f"Baris {n}: nama produk kosong.")
        elif cat is None:
            errors.append(f"Baris {n} ({name}): jenis '{row['category']}' tidak dikenal. Pakai: {', '.join(CATEGORIES)}.")
        elif value is None or value < 0:
            errors.append(f"Baris {n} ({name}): nilai '{row['current_value']}' bukan angka rupiah yang valid.")
        else:
            rows.append((name, cat, value))
    out = pd.DataFrame(rows, columns=HOLDINGS_COLS)
    if not out.empty:
        out = out.groupby(["product", "category"], as_index=False, sort=False)["current_value"].sum()
    return out, errors


def clean_transactions(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    errors: list[str] = []
    missing = [c for c in TX_COLS if c not in df.columns]
    if missing:
        return pd.DataFrame(columns=TX_COLS), [f"Kolom tidak ada: {', '.join(missing)}."]
    rows = []
    for i, row in df.reset_index(drop=True).iterrows():
        n = i + 2
        name = "" if pd.isna(row["product"]) else str(row["product"]).strip()
        date = pd.to_datetime(row["date"], errors="coerce", dayfirst=False)
        cat = normalize_category(row["category"])
        kind = str(row["type"]).strip().upper()
        kind = {"BELI": "BUY", "JUAL": "SELL"}.get(kind, kind)
        amount = parse_amount(row["amount"])
        problem = (
            "nama produk kosong" if not name else
            f"tanggal '{row['date']}' tidak valid (pakai YYYY-MM-DD)" if pd.isna(date) else
            f"jenis '{row['category']}' tidak dikenal" if cat is None else
            f"tipe '{row['type']}' harus BUY atau SELL" if kind not in TX_TYPES else
            f"nominal '{row['amount']}' harus angka lebih dari 0" if amount is None or amount <= 0 else None
        )
        if problem:
            errors.append(f"Baris {n}: {problem}.")
        else:
            rows.append((date.date().isoformat(), name, cat, kind, amount))
    out = pd.DataFrame(rows, columns=TX_COLS)
    return out.sort_values("date", kind="stable").reset_index(drop=True) if not out.empty else out, errors


def merge(existing: pd.DataFrame, new: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Add `new` rows to `existing`. Holdings: a product already present is replaced by the newer value."""
    if kind == "holdings":
        keep = existing[~existing["product"].str.strip().str.lower().isin(new["product"].str.strip().str.lower())]
        return pd.concat([keep, new], ignore_index=True)[HOLDINGS_COLS]
    both = pd.concat([existing, new], ignore_index=True)[TX_COLS].drop_duplicates()
    return both.sort_values("date", kind="stable").reset_index(drop=True)


def infer_category(name: str, catalog: pd.DataFrame) -> str | None:
    hit = catalog.loc[catalog["name"].astype(str).str.strip().str.lower() == name.strip().lower(), "category"]
    return normalize_category(hit.iloc[0]) if not hit.empty else None


def set_holding(holdings: pd.DataFrame, product: str, category: str, value: float) -> pd.DataFrame:
    """Insert or replace one product's current value."""
    new = pd.DataFrame([(product.strip(), category, float(value))], columns=HOLDINGS_COLS)
    return merge(holdings, new, "holdings")


def apply_transaction_to_holdings(holdings: pd.DataFrame, product: str, category: str, kind: str, amount: float) -> pd.DataFrame:
    """A BUY adds to the product's value, a SELL subtracts (never below zero; a zero position is dropped)."""
    key = product.strip().lower()
    mask = holdings["product"].str.strip().str.lower() == key
    current = float(holdings.loc[mask, "current_value"].sum())
    value = current + amount if kind == "BUY" else max(0.0, current - amount)
    rest = holdings[~mask]
    if value <= 0:
        return rest.reset_index(drop=True)
    return pd.concat([rest, pd.DataFrame([(product.strip(), category, value)], columns=HOLDINGS_COLS)], ignore_index=True)


def ensure_files(directory: Path | None = None) -> None:
    """Create header-only holdings/transactions files when they are missing, so the app never starts without them."""
    if directory is None and storage.current():
        return  # data lives in the database; there are no files to create
    d = directory or DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    for name, cols in (("holdings.csv", HOLDINGS_COLS), ("transactions.csv", TX_COLS)):
        if not (d / name).exists():
            (d / name).write_text(",".join(cols) + "\n", encoding="utf-8")


def read_current(directory: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    store = storage.current() if directory is None else None
    if store:
        return store.read_holdings(), store.read_transactions()
    d = directory or DATA_DIR
    holdings = pd.read_csv(d / "holdings.csv", dtype={"product": str, "category": str})
    tx = pd.read_csv(d / "transactions.csv", dtype={"product": str, "category": str, "type": str})
    holdings["current_value"] = pd.to_numeric(holdings["current_value"], errors="coerce")  # header-only file -> numeric dtype
    tx["amount"] = pd.to_numeric(tx["amount"], errors="coerce")
    return holdings, tx


def save(holdings: pd.DataFrame | None = None, tx: pd.DataFrame | None = None, directory: Path | None = None) -> list[Path]:
    """Write the given frames to CSV. The previous non-empty file is copied to data/archive first."""
    store = storage.current() if directory is None else None
    if store:
        if holdings is not None:
            store.write_holdings(holdings[HOLDINGS_COLS])
        if tx is not None:
            store.write_transactions(tx[TX_COLS])
        return []
    d = directory or DATA_DIR
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    written = []
    for name, frame, cols in (("holdings", holdings, HOLDINGS_COLS), ("transactions", tx, TX_COLS)):
        if frame is None:
            continue
        path = d / f"{name}.csv"
        if path.exists() and len(pd.read_csv(path)) > 0:
            (d / "archive").mkdir(parents=True, exist_ok=True)
            (d / "archive" / f"{name}_{stamp}.csv").write_bytes(path.read_bytes())
        out = frame[cols].copy()
        if name == "holdings":
            out["current_value"] = out["current_value"].round(0).astype("int64")
        else:
            out["amount"] = out["amount"].round(0).astype("int64")
        tmp = path.with_suffix(".tmp")
        out.to_csv(tmp, index=False, encoding="utf-8", lineterminator="\n")
        tmp.replace(path)
        written.append(path)
    return written
