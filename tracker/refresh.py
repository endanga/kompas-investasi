"""Refresh the product snapshots in data/ from Bibit's public product pages with one command:

    python -m tracker.refresh

The pages are opened in a headless Edge/Chrome and the tables a visitor sees are read. Bibit's product API
returns an obfuscated payload that its own page decodes; this module deliberately does not decode it.
Old snapshots are archived under data/archive/ so past recommendations stay traceable.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import factsheet, prospectus
from .products import is_syariah

DATA = Path(__file__).parent.parent / "data"
ARCHIVE = DATA / "archive"
BASE = "https://bibit.id"
PAGE_SIZE = 100
MAX_PAGES = 10
MIN_FUNDS = 50  # fewer than this means the page did not load properly; keep the old snapshot

FILES = {
    "funds": DATA / "products.csv",
    "sbn": DATA / "sbn_ritel.csv",
    "fr": DATA / "obligasi_fr.csv",
    "next_sbn": DATA / "sbn_berikutnya.json",
}

CATEGORY = {
    "Pasar Uang": "pasar_uang",
    "Obligasi": "pendapatan_tetap",
    "Saham": "saham",
    "Campuran": "campuran",
    "Reksadana Global": "global",
}
UNITS = {"T": 1e12, "B": 1e9, "M": 1e6}
FUND_COLUMNS = ["product_id", "name", "jenis_bibit", "category", "syariah_dari_nama",
                "return_1d_pct", "return_1m_pct", "return_3m_pct", "return_ytd_pct", "return_1y_pct",
                "return_3y_pct", "return_5y_pct", "return_10y_pct", "last_nav", "drawdown_1y_pct",
                "aum_idr", "url", "as_of", "gov_top10_pct", "top10_n", "top1_pct", "top10_sum_pct", "unknown_top10_pct", "factsheet_date", "factsheet_url"]

_JS_FUND_ROWS = """() => {
  const t = [...document.querySelectorAll('table')].find(x => x.innerText.includes('Last NAV'));
  if (!t) return [];
  return [...t.querySelectorAll('tbody tr')].map(tr => {
    const c = [...tr.querySelectorAll('td')].map(td => td.innerText.trim());
    const a = tr.querySelector('a');
    return { name: a ? a.innerText.trim() : c[0], path: a ? a.getAttribute('href') : '', cells: c.slice(1) };
  });
}"""
_JS_FR = """() => {
  const t = [...document.querySelectorAll('table')].find(x => x.innerText.includes('Harga Beli'));
  const rows = t ? [...t.querySelectorAll('tr')].map(tr =>
    [...tr.querySelectorAll('th,td')].map(c => c.innerText.trim().replace(/\\n+/g, ' | '))) : [];
  return { rows, text: document.body.innerText };
}"""
_JS_PAGE = "() => ({ title: document.title, text: document.body.innerText })"


# ---------------------------------------------------------------- parsing (pure, unit-tested)
def _clean(s: str) -> str:
    return s.replace("​", "")


def _pct(s: str) -> float | None:
    s = s.strip()
    if s in ("N/A", "-", ""):
        return None
    return round(float(s.replace("%", "").replace(",", "")), 2)


def _exact_pct(s: str) -> float | None:
    """Percentage without rounding: bond coupons have 3 decimals (e.g. 5.875%)."""
    s = s.strip()
    return None if s in ("N/A", "-", "") else float(s.replace("%", "").replace(",", ""))


def _num(s: str) -> float | None:
    s = s.strip()
    return None if s in ("N/A", "-", "") else float(s.replace(",", ""))


def _aum(s: str) -> int | None:
    m = re.fullmatch(r"([\d.,]+)\s*([TBM])", s.strip())
    return int(float(m.group(1).replace(",", "")) * UNITS[m.group(2)]) if m else None


def parse_funds(rows: list[dict], as_of: str) -> pd.DataFrame:
    """Rows scraped from the fund table -> tidy frame. Cell order follows the page's columns."""
    out, seen = [], set()
    for r in rows:
        if not r["path"] or r["path"] in seen or len(r["cells"]) != 12:
            continue
        seen.add(r["path"])
        jenis, d1, m1, m3, ytd, y1, y3, y5, y10, nav, dd, aum = r["cells"]
        out.append({
            "product_id": r["path"].rsplit("/", 1)[-1], "name": r["name"], "jenis_bibit": jenis,
            "category": CATEGORY.get(jenis, "lainnya"),
            "syariah_dari_nama": "ya" if is_syariah(r["name"]) else "tidak",
            "return_1d_pct": _pct(d1), "return_1m_pct": _pct(m1), "return_3m_pct": _pct(m3),
            "return_ytd_pct": _pct(ytd), "return_1y_pct": _pct(y1), "return_3y_pct": _pct(y3),
            "return_5y_pct": _pct(y5), "return_10y_pct": _pct(y10), "last_nav": _num(nav),
            "drawdown_1y_pct": _pct(dd), "aum_idr": _aum(aum), "url": BASE + r["path"], "as_of": as_of,
        })
    return pd.DataFrame(out, columns=FUND_COLUMNS)


_SBN_PATTERN = re.compile(
    r"(?P<kode>[A-Z]{2,3}\d{3}-T\d)\s+(?P<jenis>[^\n]+?)\s+Kupon Imbal Hasil\s+(?P<kupon>[\d.]+)% / Tahun\s+"
    r"Periode Pembelian\s+(?P<beli>[^\n]+?)\s+Jatuh Tempo\s+(?P<tempo>[^\n]+?)\s+Lihat Memo"
)


def parse_sbn(text: str, as_of: str) -> pd.DataFrame:
    rows = [{
        "kode": m["kode"], "jenis": m["jenis"].strip(), "kupon_pct": float(m["kupon"]),
        "periode_pembelian": m["beli"].strip(), "jatuh_tempo": m["tempo"].strip(), "as_of": as_of,
    } for m in _SBN_PATTERN.finditer(_clean(text))]
    return pd.DataFrame(rows, columns=["kode", "jenis", "kupon_pct", "periode_pembelian", "jatuh_tempo", "as_of"])


def parse_next_sbn(title: str, text: str, as_of: str) -> dict | None:
    """Upcoming SBN offering, read from the page title ('... ST017 ... Mulai 6 November 2026')."""
    m = re.search(r"\b((?:ST|SBR|ORI|SR)\d{3})\b.*?Mulai\s+(\d{1,2}\s+\w+\s+\d{4})", _clean(title))
    if not m:
        return None
    detail = re.search(rf"{m.group(1)}\s+(Syariah|Konvensional)?\s*([A-Za-z ]+?)\s+(Floating[^\n]*|Fixed[^\n]*)\n",
                       _clean(text))
    return {"kode": m.group(1), "mulai": m.group(2), "judul": title.strip(),
            "keterangan": " ".join(g.strip() for g in detail.groups() if g) if detail else "", "as_of": as_of}


_FR_COLUMNS = ["seri", "tipe", "label", "yield_pct", "kupon_pct", "harga_beli_pct", "harga_jual_pct",
               "jatuh_tempo", "as_of"]
_FR_FEATURED = re.compile(
    r"(?P<seri>(?:FR|PBS)\d+)\s+(?P<tipe>FR Syariah|Obligasi FR)\s+Yield\s+(?P<y>[\d.]+)%\s+Kupon\s+(?P<k>[\d.]+)%\s+"
    r"Harga Beli\s+(?P<b>[\d.]+)%\s+Jatuh Tempo:\s+(?P<t>[^\n]+)"
)


def parse_fr(rows: list[list[str]], text: str, as_of: str) -> pd.DataFrame:
    out = []
    for cells in rows[1:]:
        if len(cells) != 6:
            continue
        series, yld, kupon, beli, jual, tempo = cells
        parts = [p.strip() for p in _clean(series).split("|")]
        out.append({
            "seri": parts[0], "tipe": parts[-1], "label": "Top Short Term" if "Top Short Term" in parts else "",
            "yield_pct": _pct(yld), "kupon_pct": _exact_pct(kupon), "harga_beli_pct": _pct(beli),
            "harga_jual_pct": _pct(jual), "jatuh_tempo": tempo.strip(), "as_of": as_of,
        })
    have = {r["seri"] for r in out}
    for m in _FR_FEATURED.finditer(_clean(text)):  # series highlighted outside the table (e.g. PBS038)
        if m["seri"] not in have:
            have.add(m["seri"])
            out.append({"seri": m["seri"], "tipe": m["tipe"], "label": "", "yield_pct": float(m["y"]),
                        "kupon_pct": float(m["k"]), "harga_beli_pct": float(m["b"]), "harga_jual_pct": None,
                        "jatuh_tempo": m["t"].strip(), "as_of": as_of})
    return pd.DataFrame(out, columns=_FR_COLUMNS)


# ---------------------------------------------------------------- fetching
def _launch(p):
    """Open a normal (visible, minimized) Edge/Chrome window.

    bibit.id blocks headless browsers outright, so a real window is used. No user-agent spoofing or other
    disguise is applied: the page is opened the way a visitor would open it.
    """
    for channel in ("msedge", "chrome"):
        try:
            return p.chromium.launch(channel=channel, headless=False, args=["--start-minimized"])
        except Exception:  # try the next installed browser
            continue
    raise RuntimeError("Microsoft Edge atau Google Chrome tidak ditemukan. Pasang salah satunya, lalu ulangi.")


def _wait(page, selector: str) -> None:
    """Wait for `selector`; if the site served a block page instead, say so plainly."""
    try:
        page.wait_for_selector(selector, timeout=45_000)
    except Exception as e:
        body = page.evaluate("document.body ? document.body.innerText : ''")
        if "you have been blocked" in body.lower():
            raise RuntimeError(
                "bibit.id memblokir akses otomatis saat ini. Tunggu beberapa saat lalu coba lagi, "
                "atau perbarui data lewat Claude Code (skill refresh-bibit-data)."
            ) from e
        raise


def fetch_raw(log=print) -> dict:
    """Open the public pages in a headless browser and return what a visitor sees."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("Paket playwright belum terpasang. Jalankan: python -m pip install playwright") from e
    raw: dict = {"funds": []}
    with sync_playwright() as p:
        browser = _launch(p)
        try:
            page = browser.new_page()
            for n in range(1, MAX_PAGES + 1):
                log(f"Reksa dana halaman {n}...")
                page.goto(f"{BASE}/reksadana?limit={PAGE_SIZE}&page={n}&tradable=1", wait_until="domcontentloaded")
                _wait(page, "table tbody tr a[href^='/reksadana/']")
                rows = page.evaluate(_JS_FUND_ROWS)
                raw["funds"] += rows
                if len(rows) < PAGE_SIZE:
                    break
            log("Obligasi FR...")
            page.goto(f"{BASE}/obligasifr", wait_until="domcontentloaded")
            _wait(page, "table tbody tr")
            raw["fr"] = page.evaluate(_JS_FR)
            log("SBN Ritel...")
            page.goto(f"{BASE}/sbn", wait_until="domcontentloaded")
            page.wait_for_function("document.body.innerText.includes('Kupon Imbal Hasil')", timeout=45_000)
            raw["sbn"] = page.evaluate(_JS_PAGE)
        finally:
            browser.close()
    return raw


# ---------------------------------------------------------------- writing
@dataclass
class RefreshReport:
    as_of: str
    funds: int = 0
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed_datasets: list[str] = field(default_factory=list)
    unchanged_datasets: list[str] = field(default_factory=list)
    archived_to: str | None = None
    warnings: list[str] = field(default_factory=list)
    ok: bool = True

    def summary(self) -> str:
        lines = [f"Data produk diperbarui ({self.as_of}): {self.funds} reksa dana."]
        if self.added:
            lines.append(f"Produk baru ({len(self.added)}): " + ", ".join(self.added[:8]) + (" ..." if len(self.added) > 8 else ""))
        if self.removed:
            lines.append(f"Produk hilang ({len(self.removed)}): " + ", ".join(self.removed[:8]) + (" ..." if len(self.removed) > 8 else ""))
        if self.changed_datasets:
            lines.append("Berubah: " + ", ".join(self.changed_datasets))
        if self.unchanged_datasets:
            lines.append("Tidak berubah: " + ", ".join(self.unchanged_datasets))
        if self.archived_to:
            lines.append(f"Data lama diarsipkan di {self.archived_to}")
        lines += [f"Peringatan: {w}" for w in self.warnings]
        return "\n".join(lines)


def _as_saved(df: pd.DataFrame) -> pd.DataFrame:
    """The frame as it would look after a save/load round trip, without the date column.

    Needed because e.g. '' becomes NaN and ints can become floats once written to CSV and read back.
    """
    text = df.drop(columns=["as_of"], errors="ignore").to_csv(index=False)
    return pd.read_csv(io.StringIO(text))


def _differs(old: pd.DataFrame | None, new: pd.DataFrame) -> bool:
    if old is None:
        return True
    a, b = _as_saved(old), _as_saved(new)
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return True
    key = a.columns[0]
    return not a.sort_values(key).reset_index(drop=True).equals(b.sort_values(key).reset_index(drop=True))


def _read(path: Path) -> pd.DataFrame | None:
    return pd.read_csv(path) if path.exists() and path.stat().st_size > 0 else None


def build(raw: dict, as_of: str) -> dict:
    """Raw page contents -> the datasets to write (pure; no I/O)."""
    return {
        "funds": parse_funds(raw["funds"], as_of),
        "fr": parse_fr(raw["fr"]["rows"], raw["fr"]["text"], as_of),
        "sbn": parse_sbn(raw["sbn"]["text"], as_of),
        "next_sbn": parse_next_sbn(raw["sbn"]["title"], raw["sbn"]["text"], as_of),
    }


def _fund_set_changes(old: pd.DataFrame | None, new: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Names of funds that appeared / disappeared between two snapshots."""
    if old is None:
        return [], []
    old_names = dict(zip(old["product_id"], old["name"]))
    new_names = dict(zip(new["product_id"], new["name"]))
    return ([n for i, n in new_names.items() if i not in old_names],
            [n for i, n in old_names.items() if i not in new_names])


def _funds_look_complete(new: pd.DataFrame, old: pd.DataFrame | None) -> bool:
    """A half-loaded page must never replace a good snapshot."""
    return len(new) >= MIN_FUNDS and (old is None or len(new) >= 0.5 * len(old))


def _next_sbn_changed(new: dict) -> bool:
    path = FILES["next_sbn"]
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {k: v for k, v in old.items() if k != "as_of"} != {k: v for k, v in new.items() if k != "as_of"}


def _archive_current(old_funds: pd.DataFrame | None, now: datetime) -> str | None:
    """Copy the files about to be replaced into data/archive/<old as_of>_<time>/."""
    old_date = str(old_funds["as_of"].iloc[0]) if old_funds is not None and "as_of" in old_funds else "lama"
    folder = ARCHIVE / f"{old_date}_{now:%H%M%S}"
    for path in FILES.values():
        if path.exists():
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, folder / path.name)
    return str(folder.relative_to(DATA.parent)) if folder.exists() else None


def _commit(plan: dict[str, pd.DataFrame], next_sbn: dict | None) -> None:
    for key, df in plan.items():
        tmp = FILES[key].with_suffix(".tmp")
        df.to_csv(tmp, index=False, encoding="utf-8")
        tmp.replace(FILES[key])
    if next_sbn is not None:
        FILES["next_sbn"].write_text(json.dumps(next_sbn, ensure_ascii=False, indent=2), encoding="utf-8")


def write(datasets: dict, as_of: str, now: datetime | None = None, dry_run: bool = False) -> RefreshReport:
    """Validate, archive the old snapshot when something changed, then replace the files."""
    report = RefreshReport(as_of=as_of)
    funds: pd.DataFrame = datasets["funds"]
    old_funds = _read(FILES["funds"])

    if not _funds_look_complete(funds, old_funds):
        report.ok = False
        report.warnings.append(
            f"Hanya {len(funds)} reksa dana terbaca (sebelumnya {0 if old_funds is None else len(old_funds)}); "
            "data lama dipertahankan. Halaman mungkin belum termuat sempurna, coba lagi."
        )
        return report
    report.funds = len(funds)
    report.added, report.removed = _fund_set_changes(old_funds, funds)

    plan: dict[str, pd.DataFrame] = {}
    for key in ("funds", "fr", "sbn"):
        if key != "funds" and datasets[key].empty:
            report.warnings.append(f"Data '{FILES[key].name}' tidak terbaca; file lama dipertahankan.")
            continue
        plan[key] = datasets[key]
        changed = _differs(_read(FILES[key]), datasets[key])
        (report.changed_datasets if changed else report.unchanged_datasets).append(FILES[key].name)
    next_sbn = datasets.get("next_sbn")
    if next_sbn is not None:
        changed = _next_sbn_changed(next_sbn)
        (report.changed_datasets if changed else report.unchanged_datasets).append(FILES["next_sbn"].name)
    if dry_run:
        return report

    if report.changed_datasets:  # archive only when something really changed
        report.archived_to = _archive_current(old_funds, now or datetime.now())
    _commit(plan, next_sbn)
    return report


def format_markdown(output: str) -> str:
    """Tidy CLI output for display: drop progress lines, bold the headline, bullet the rest."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip() and not ln.strip().endswith("...")]
    if not lines:
        return "Tidak ada keluaran dari pembaruan."

    def code_files(line: str) -> str:
        head, sep, tail = line.partition(": ")
        if sep and head in ("Berubah", "Tidak berubah"):
            return f"{head}: " + ", ".join(f"`{name}`" for name in tail.split(", "))
        return re.sub(r"(data[\\/]archive[\\/]\S+)", r"`\1`", line)

    first, rest = lines[0], lines[1:]
    if first.startswith("GAGAL"):
        return "\n".join([f"**{first}**", *[f"- {code_files(ln)}" for ln in rest]])
    head = re.sub(r"^Data produk diperbarui \(([^)]+)\): (\d+) reksa dana\.$", r"**Data produk diperbarui** (\1): \2 reksa dana", first)
    return "\n".join([head if head != first else f"**{first}**", *[f"- {code_files(ln)}" for ln in rest]])


FACTSHEET_COLUMNS = ["gov_top10_pct", "top10_n", "top1_pct", "top10_sum_pct", "unknown_top10_pct", "factsheet_date",
                     "factsheet_url"]


def add_factsheets(funds: pd.DataFrame, old: pd.DataFrame | None, log=print) -> tuple[pd.DataFrame, list[str]]:
    """Fill the fact sheet columns for bond funds from each fund's latest fact sheet.

    A fund whose fact sheet cannot be fetched keeps its previous values (never erased), and is named in the warnings.
    """
    funds = funds.copy()
    for col in FACTSHEET_COLUMNS:
        funds[col] = None
    if old is not None and set(FACTSHEET_COLUMNS) <= set(old.columns):
        prev = old.set_index("product_id")[FACTSHEET_COLUMNS]
        for col in FACTSHEET_COLUMNS:
            funds[col] = funds["product_id"].map(prev[col])
    failed: list[str] = []
    bonds = funds[funds["category"] == "pendapatan_tetap"]
    for n, (idx, row) in enumerate(bonds.iterrows(), 1):
        log(f"Fund fact sheet {n}/{len(bonds)}...")
        try:
            facts = factsheet.read_fund(row["product_id"])
        except Exception as e:  # network, missing document, or a missing PDF library
            failed.append(f"{row['name']} ({str(e)[:60]})")
            continue
        for col, value in facts.items():
            funds.at[idx, col] = value
    warnings = [f"Fund fact sheet {len(failed)} dana pendapatan tetap gagal dibaca, nilai lama dipertahankan: "
                + ", ".join(failed[:3]) + (" ..." if len(failed) > 3 else "")] if failed else []
    return funds, warnings


def run(dry_run: bool = False, log=print) -> RefreshReport:
    as_of = datetime.now().date().isoformat()
    raw = fetch_raw(log)
    datasets = build(raw, as_of)
    datasets["funds"], notes = add_factsheets(datasets["funds"], _read(FILES["funds"]), log)
    report = write(datasets, as_of, dry_run=dry_run)
    report.warnings += notes
    return report


PROSPECTUS_FILE = DATA / "prospectus.csv"
PROSPECTUS_COLUMNS = ["product_id", "name", "file", "url", "position_date", "n_bonds", "parsed_pct", "reported_total_pct", "reconciled",
                      "gov_pct", "corp_pct", "investment_grade_pct", "unrated_pct", "wam_years", "ratings", "policy", "fetched"]


def run_prospectus(log=print) -> tuple[pd.DataFrame, list[str]]:
    """Read the newest prospectus of every bond fund into data/prospectus.csv (PDFs cached under data/cache/).

    A fund that fails keeps its previous row and is named in the warnings; nothing is guessed. Figures derived from the
    portfolio table are stored only when the parsed total matches the document's own 'Jumlah' line."""
    funds = _read(FILES["funds"])
    if funds is None:
        raise RuntimeError("data/products.csv belum ada; jalankan pembaruan data penuh dulu.")
    old = _read(PROSPECTUS_FILE)
    previous = {} if old is None else {r["product_id"]: r for r in old.to_dict("records")}
    bonds = funds[funds["category"] == "pendapatan_tetap"]
    rows, warnings = [], []
    for n, row in enumerate(bonds.to_dict("records"), 1):
        log(f"Prospektus {n}/{len(bonds)}: {row['name']}")
        try:
            facts = prospectus.read_fund(row["product_id"], log=log)
        except Exception as e:  # network, missing document, or a missing PDF library
            warnings.append(f"{row['name']} ({str(e)[:70]})")
            if row["product_id"] in previous:
                rows.append(previous[row["product_id"]])
            continue
        rows.append({
            "product_id": row["product_id"], "name": row["name"], "file": facts["file"], "url": facts["url"],
            "position_date": facts["position_date"].isoformat() if facts["position_date"] else None, "n_bonds": facts["n_bonds"],
            "parsed_pct": facts["parsed_pct"], "reported_total_pct": facts["reported_total_pct"], "reconciled": facts["reconciled"],
            "gov_pct": facts["gov_pct"], "corp_pct": facts["corp_pct"], "investment_grade_pct": facts["investment_grade_pct"],
            "unrated_pct": facts["unrated_pct"], "wam_years": facts["wam_years"],
            "ratings": json.dumps(facts["ratings"], ensure_ascii=False) if facts["ratings"] else None,
            "policy": json.dumps(facts["policy"], ensure_ascii=False), "fetched": facts["fetched"],
        })
    out = pd.DataFrame(rows, columns=PROSPECTUS_COLUMNS)
    tmp = PROSPECTUS_FILE.with_suffix(".tmp")
    out.to_csv(tmp, index=False, encoding="utf-8")
    tmp.replace(PROSPECTUS_FILE)
    return out, warnings


def prospectus_summary(out: pd.DataFrame, warnings: list[str]) -> str:
    ok = int(out["reconciled"].fillna(False).astype(bool).sum()) if len(out) else 0
    lines = [f"Prospektus dibaca untuk {len(out)} dana obligasi; tabel portofolio cocok dengan total di dokumen untuk {ok}.",
             "Posisi portofolio mengikuti laporan keuangan di prospektus (akhir tahun buku), bukan kondisi hari ini."]
    unreconciled = out[~out["reconciled"].fillna(False).astype(bool)]["name"].tolist() if len(out) else []
    if unreconciled:
        lines.append(f"Peringatan: {len(unreconciled)} dana tabelnya belum terbaca utuh (angka turunan tidak disimpan): "
                     + ", ".join(unreconciled[:4]) + (" ..." if len(unreconciled) > 4 else ""))
    if warnings:
        lines.append(f"Peringatan: {len(warnings)} dana gagal diproses, baris lama dipertahankan: " + ", ".join(warnings[:3]))
    return "\n".join(lines)


def run_factsheets_only(log=print) -> RefreshReport:
    """Re-read only the fund fact sheets into the current products.csv (no browser, prices untouched)."""
    old = _read(FILES["funds"])
    if old is None:
        raise RuntimeError("data/products.csv belum ada; jalankan pembaruan data penuh dulu.")
    funds, notes = add_factsheets(old.drop(columns=FACTSHEET_COLUMNS, errors="ignore"), old, log)
    tmp = FILES["funds"].with_suffix(".tmp")
    funds.to_csv(tmp, index=False, encoding="utf-8")
    tmp.replace(FILES["funds"])
    known = int(funds["gov_top10_pct"].notna().sum())
    return RefreshReport(as_of=str(old["as_of"].iloc[0]), funds=len(funds), changed_datasets=[FILES["funds"].name],
                         warnings=[f"Fact sheet terbaca untuk {known} dana pendapatan tetap."] + notes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Perbarui data produk Bibit di folder data/.")
    ap.add_argument("--dry-run", action="store_true", help="hanya tampilkan perubahan, jangan tulis file")
    ap.add_argument("--factsheets-only", action="store_true", help="hanya baca ulang fund fact sheet, harga tidak disentuh")
    ap.add_argument("--prospectus", action="store_true",
                    help="baca prospektus terbaru dana obligasi (jarang berubah; PDF di-cache di data/cache)")
    args = ap.parse_args(argv)
    try:
        log = lambda msg: print(msg, file=sys.stderr)  # noqa: E731  progress -> stderr
        if args.prospectus:
            print(prospectus_summary(*run_prospectus(log)))
            return 0
        report = run_factsheets_only(log) if args.factsheets_only else run(dry_run=args.dry_run, log=log)
    except Exception as e:  # network, browser, or page-layout problems
        print(f"GAGAL memperbarui data: {e}", file=sys.stderr)
        return 1
    print(report.summary())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
