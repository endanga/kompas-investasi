"""One-off copy of the local data files into the configured database.

    python -m tracker.migrate                 # URL from KOMPAS_DATABASE_URL or .streamlit/secrets.toml
    python -m tracker.migrate --url postgresql://...   # or pass it directly
    python -m tracker.migrate --dry-run       # only report what would be copied

Safe to run twice: saved recommendations are replaced by name and robo entries are matched on time and level. Holdings and
transactions replace the database copy, so by default the script refuses when the database already has portfolio data
(use --force to overwrite it).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import history, portfolio_io, robo, settings, storage


def migrate(store: storage.SqlStore, data_dir: Path | None = None, force: bool = False, dry_run: bool = False) -> dict:
    """Copy files from `data_dir` into `store`. Returns counts of what was (or would be) written."""
    d = data_dir or portfolio_io.DATA_DIR
    holdings = pd.read_csv(d / "holdings.csv") if (d / "holdings.csv").exists() else pd.DataFrame(columns=portfolio_io.HOLDINGS_COLS)
    tx = pd.read_csv(d / "transactions.csv") if (d / "transactions.csv").exists() else pd.DataFrame(columns=portfolio_io.TX_COLS)
    recs = history.list_saved(d / "recommendations")
    robo_entries = robo.load(d / "robo_picks.json")

    existing_rows = len(store.read_holdings()) + len(store.read_transactions())
    if existing_rows and (len(holdings) or len(tx)) and not force:
        raise RuntimeError(f"Database sudah berisi {existing_rows} baris portofolio. Pakai --force untuk menimpanya.")

    known_robo = {(e["saved_at"], float(e["level"])) for e in store.list_robo()}
    new_robo = [e for e in robo_entries if (e["saved_at"], float(e["level"])) not in known_robo]
    counts = {"holdings": len(holdings), "transactions": len(tx), "recommendations": len(recs), "robo_picks": len(new_robo)}
    if dry_run:
        return counts

    if len(holdings) or force:
        store.write_holdings(holdings)
    if len(tx) or force:
        store.write_transactions(tx)
    for snap in recs:
        name = snap["_file"]
        store.save_recommendation({k: v for k, v in snap.items() if k != "_file"}, name)
    for entry in new_robo:
        store.append_robo(entry)
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Salin data pribadi dari folder data/ ke database.")
    ap.add_argument("--url", help="URL database; bila kosong dipakai KOMPAS_DATABASE_URL atau secrets.toml")
    ap.add_argument("--force", action="store_true", help="timpa portofolio yang sudah ada di database")
    ap.add_argument("--dry-run", action="store_true", help="hanya tampilkan jumlah data yang akan disalin")
    args = ap.parse_args(argv)
    url = settings.normalise_url(args.url) if args.url else settings.database_url()
    if not url:
        print("URL database belum diatur. Isi KOMPAS_DATABASE_URL atau berikan --url.", file=sys.stderr)
        return 2
    try:
        counts = migrate(storage.SqlStore(url), force=args.force, dry_run=args.dry_run)
    except Exception as e:  # connection, permission or overwrite-guard problems
        print(f"GAGAL: {e}", file=sys.stderr)
        return 1
    verb = "Akan disalin" if args.dry_run else "Tersalin"
    print(f"{verb}: " + ", ".join(f"{n} {k}" for k, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
