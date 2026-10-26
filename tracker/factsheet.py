"""Read the latest fund fact sheet of bond funds from Bibit's public document list, to see WHAT a bond fund holds.

The price history in the product table says how much a fund's price moved, not how safe its issuers are: a fund
full of corporate bonds can show a flat price for years and still lose money if one issuer defaults. The fact sheet
lists the ten largest holdings, so the share held in government bonds (FR / SBN / sukuk negara) is a rough, honest
sign of credit risk. It is NOT a credit rating: fact sheets do not carry ratings or duration.
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
    r"\bFR\s?\d{3,4}|\bPBS\s?\d+|\bSBSN\b|\bSBN\b|\bSR\s?\d{3}|\bORI\s?\d+|\bVR\s?\d+|republik indonesia|pemerintah|"
    r"\b(obligasi|obl\.?|sukuk|surat berharga)\s+(negara|negera)", re.I)       # "Bank Negara Indonesia" is a bank, not the state
# a line that names a holder: a company, a bank, or a government series
_HOLDER = re.compile(r"\b(PT|Tbk|Bank|Finance|Multifinance|Sukuk|Berkelanjutan|Tahap|Seri|Persero)\b|, PT\b", re.I)
# lines that describe the holding's type or the table itself, never a holder
_NOT_HOLDER = re.compile(
    r"^(obligasi( fr| korporasi| negara| daerah)?|sukuk( negara| korporasi)?|ekuitas|saham|kas|pasar uang|deposito|"
    r"likuiditas|lainnya|eba|reksa dana|\d+ (tahun|bulan)|ytd|sejak.*|kinerja.*|tolak ukur.*|periode.*|"
    r"dalam negeri|luar negeri|top.*|10 besar.*|bank kustodian.*)$", re.I)


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


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


def latest_pdf(code: str) -> tuple[bytes, str]:
    """(PDF bytes, date) of the newest fact sheet of product `code` (e.g. 'RD556')."""
    items = json.loads(_get(API.format(code=code)))["data"]
    if not items:
        raise ValueError(f"{code}: belum ada fund fact sheet")
    items.sort(key=lambda d: d["date"], reverse=True)
    return _get(items[0]["file"]), items[0]["date"]


def pdf_text(pdf: bytes) -> str:
    try:
        import pymupdf
    except ImportError as e:
        raise RuntimeError("Paket pymupdf belum terpasang. Jalankan: python -m pip install pymupdf") from e
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def read_fund(code: str) -> dict:
    """Fact sheet facts for one fund: {'gov_top10_pct', 'top10_n', 'factsheet_date'}."""
    pdf, date = latest_pdf(code)
    share, n = government_share(pdf_text(pdf))
    return {"gov_top10_pct": share, "top10_n": n, "factsheet_date": date}
