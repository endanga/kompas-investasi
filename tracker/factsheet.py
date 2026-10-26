"""Read the latest fund fact sheet of bond funds from Bibit's public document list, to see WHAT a bond fund holds.

The price history in the product table says how much a fund's price moved, not how safe its issuers are: a fund
full of corporate bonds can show a flat price for years and still lose money if one issuer defaults. The fact sheet
lists the ten largest holdings, so the share held in government bonds (FR / SBN / sukuk negara / INDOGB) is a rough,
honest sign of credit risk. It is NOT a credit rating: fact sheets do not carry ratings or duration.
"""
from __future__ import annotations

import json
import re
import urllib.request

MIN_HOLDINGS = 5          # fewer readable holdings than this and the share is reported as unknown
API = "https://api.bibit.id/products/{code}/factsheets"
_HEADERS = {"User-Agent": "Mozilla/5.0"}

_PCT_ONLY = re.compile(r"^(\d{1,3}(?:[.,]\d+)?)\s*%$")
_LABEL_THEN_PCT = re.compile(r"^(?P<label>\S.*?)\s+(?P<pct>\d{1,3}(?:[.,]\d+)?)\s*%$")
GOVERNMENT = re.compile(
    r"\bFR\s?\d{3,4}|\bPBS\s?\d+|\bSBSN\b|\bSBN\b|\bSR\s?\d{3}|\bORI\s?\d+|\bVR\s?\d+|\bINDOGB\b|republik indonesia|pemerintah|"
    r"\b(obligasi|obl\.?|sukuk|surat berharga)\s+(negara|negera)", re.I)       # "Bank Negara Indonesia" is a bank, not the state
# Positive evidence that a holding is a company's debt. A bare "Bank X" could be a bond OR a deposit, so it is NOT
# corporate: it is a holding whose class is unknown.
CORPORATE = re.compile(r"\b(PT|Tbk|Persero|Finance|Multifinance|Sukuk|Berkelanjutan|Tahap|Seri)\b", re.I)
# a line that names a holder at all: government, corporate, or a bank
_HOLDER = re.compile(CORPORATE.pattern + r"|\bBank\b|\bINDOGB\b", re.I)
# a group heading such as "Obligasi Pemerintah" is a bucket of many bonds, never a single issuer
_GROUP = re.compile(r"^(obligasi|sukuk|surat berharga)\s+(pemerintah|negara|korporasi|daerah)\s*$", re.I)
# lines that describe the holding's type or the table itself, never a holder
_NOT_HOLDER = re.compile(
    r"^(obligasi( fr| korporasi| negara| daerah)?|sukuk( negara| korporasi)?|ekuitas|saham|kas|pasar uang|deposito|"
    r"likuiditas|lainnya|eba|reksa dana|\d+ (tahun|bulan)|ytd|sejak.*|kinerja.*|tolak ukur.*|periode.*|"
    r"dalam negeri|luar negeri|top.*|10 besar.*|bank kustodian.*)$", re.I)


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


def classify(name: str) -> str:
    """'pemerintah', 'korporasi' or 'tidak diketahui'. Only positive evidence counts; nothing is guessed."""
    if GOVERNMENT.search(name):
        return "pemerintah"
    return "korporasi" if CORPORATE.search(name) else "tidak diketahui"


def is_group(name: str) -> bool:
    """A heading such as 'Obligasi Pemerintah' stands for many bonds, so it is not a single issuer."""
    return bool(_GROUP.match(name.strip())) and not any(ch.isdigit() for ch in name)


def _is_holder(label: str) -> bool:
    return bool(GOVERNMENT.search(label) or _HOLDER.search(label))


def _holding_on_line(lines: list[str], i: int) -> tuple[str, float] | None:
    """The holding that line `i` completes, if any: 'Holder 12.5%', or a bare percentage whose holder is 1-3 lines above."""
    m = _LABEL_THEN_PCT.match(lines[i])
    if m and _is_holder(m["label"]):
        return m["label"], _to_float(m["pct"])
    m = _PCT_ONLY.match(lines[i])
    if not m:
        return None
    for cand in reversed(lines[max(0, i - 3):i]):
        if _PCT_ONLY.match(cand) or _NOT_HOLDER.match(cand):
            continue
        return (cand, _to_float(m.group(1))) if _is_holder(cand) else None
    return None


def top_holdings(text: str) -> list[tuple[str, float]]:
    """(holder, weight %) pairs found in fact sheet text. Layouts differ, so this reads two common shapes:
    'Holder  12.5%' on one line, or the holder on a line and its percentage on a following line."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    seen, unique = set(), []                          # a holding listed twice must not count twice
    for i in range(len(lines)):
        hit = _holding_on_line(lines, i)
        if hit and hit not in seen and hit[1] <= 60:
            seen.add(hit)
            unique.append(hit)
    return unique[:10]


def government_share(text: str) -> tuple[float | None, int]:
    """(share of the top-10 weight held in government bonds in %, how many holdings were read).

    None when fewer than MIN_HOLDINGS holdings could be read: unknown is reported as unknown, never as 0.
    """
    holdings = top_holdings(text)
    total = sum(p for _, p in holdings)
    if len(holdings) < MIN_HOLDINGS or total <= 0:
        return None, len(holdings)
    gov = sum(p for name, p in holdings if GOVERNMENT.search(name))
    return round(100 * gov / total, 1), len(holdings)


def _get(url: str, timeout: int = 60) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=_HEADERS), timeout=timeout).read()


def latest_pdf(code: str) -> tuple[bytes, str, str]:
    """(PDF bytes, date, url) of the newest fact sheet of product `code` (e.g. 'RD556')."""
    items = json.loads(_get(API.format(code=code)))["data"]
    if not items:
        raise ValueError(f"{code}: belum ada fund fact sheet")
    items.sort(key=lambda d: d["date"], reverse=True)
    return _get(items[0]["file"]), items[0]["date"], items[0]["file"]


def _open(pdf: bytes):
    try:
        import pymupdf
    except ImportError as e:
        raise RuntimeError("Paket pymupdf belum terpasang. Jalankan: python -m pip install pymupdf") from e
    return pymupdf.open(stream=pdf, filetype="pdf")


def pdf_text(pdf: bytes) -> str:
    with _open(pdf) as doc:
        return "\n".join(page.get_text() for page in doc)


COLUMN_GAP = 12   # points; words closer than this on one row belong to the same table cell


def layout_text(pdf: bytes) -> str:
    """Text rebuilt row by row from word positions, one table cell per line.

    Some fact sheets (e.g. ABF Indonesia Bond Index) store a holdings table column by column, so plain extraction
    separates every name from its percentage. Rows that share a vertical position are put back together here.
    Only used when the plain text yields too few holdings, so documents that already read correctly are untouched.
    """
    out: list[str] = []
    with _open(pdf) as doc:
        for page in doc:
            rows: dict[int, list] = {}
            for w in page.get_text("words"):
                rows.setdefault(round(w[1] / 4), []).append(w)
            for key in sorted(rows):
                cell: list = []
                for w in sorted(rows[key], key=lambda x: x[0]):
                    if cell and w[0] - cell[-1][2] >= COLUMN_GAP:
                        out.append(" ".join(c[4] for c in cell))
                        cell = []
                    cell.append(w)
                if cell:
                    out.append(" ".join(c[4] for c in cell))
    return "\n".join(out)


def summarize(text: str) -> dict:
    """What a fact sheet's text says about holdings. Fields that could not be read are None, never 0.

    gov_top10_pct: share of the ten largest holdings that is government debt (not of the whole fund).
    unknown_top10_pct: share of those holdings whose class the text does not show (neither government nor
        clearly corporate); it stays in the denominator, so it never makes a fund look safer.
    top1_pct: weight of the largest single named holding. Group headings ("Obligasi Pemerintah") are not an issuer.
    top10_sum_pct: how much of the fund the readable holdings cover; the rest is not seen.
    A total above 100% means the text was misread, so nothing is reported.
    """
    holdings = top_holdings(text)
    total = sum(p for _, p in holdings)
    if len(holdings) < MIN_HOLDINGS or total <= 0 or total > 100.5:
        return {"gov_top10_pct": None, "unknown_top10_pct": None, "top10_n": len(holdings), "top1_pct": None,
                "top10_sum_pct": None}
    named = [p for name, p in holdings if not is_group(name)]

    def share(kind: str) -> float:
        return round(100 * sum(p for n, p in holdings if classify(n) == kind) / total, 1)

    return {"gov_top10_pct": share("pemerintah"), "unknown_top10_pct": share("tidak diketahui"), "top10_n": len(holdings),
            "top1_pct": max(named) if named else None, "top10_sum_pct": round(total, 1)}


def facts_from_pdf(pdf: bytes) -> dict:
    """summarize() on the plain text; if that finds too few holdings, once more on the row-by-row layout text."""
    facts = summarize(pdf_text(pdf))
    if facts["gov_top10_pct"] is None:
        alt = summarize(layout_text(pdf))
        if alt["gov_top10_pct"] is not None:
            facts = alt
    return facts


def read_fund(code: str) -> dict:
    """Fact sheet facts for one fund, plus the date and address of the fact sheet they came from."""
    pdf, date, url = latest_pdf(code)
    return {**facts_from_pdf(pdf), "factsheet_date": date, "factsheet_url": url}
