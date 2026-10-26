"""Read bond-fund prospectuses from Bibit's public document list: policy limits and the audited portfolio table.

A prospectus is long (100+ pages) and changes a few times a year, so it is NOT part of the everyday refresh. Run it on
its own:  python -m tracker.refresh --prospectus   (PDFs are cached under data/cache/ and fetched again only when the
newest file changes).

What it reads, and what it does not:
  * The "Portofolio Efek / Efek Utang" note of the audited financial statements attached to the prospectus. It lists every
    bond with rating, face value, coupon, maturity date and its share of the WHOLE portfolio. It is a snapshot at the end
    of the financial year (e.g. 31 Dec 2025), so it is older than a fact sheet and is always reported with that date.
  * Verbatim sentences about minimum/maximum holdings from the investment policy. They are quoted, not interpreted.
  * The weighted-average time to maturity of the bonds. That is NOT duration: duration also depends on coupons and yields,
    and the documents do not state it. Nothing here is a credit rating of the fund itself.
Anything that cannot be read is left empty (None), never filled with a guess.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

from . import factsheet

LIST_API = "https://api.bibit.id/products/{code}/prospectus"
CACHE = Path(__file__).parent.parent / "data" / "cache" / "prospectus"
MIN_ROWS = 3             # fewer bond rows than this and the table is reported as unreadable

_MONTHS = {
    "jan": 1, "januari": 1, "january": 1, "feb": 2, "februari": 2, "february": 2, "mar": 3, "maret": 3, "march": 3,
    "apr": 4, "april": 4, "mei": 5, "may": 5, "jun": 6, "juni": 6, "june": 6, "jul": 7, "juli": 7, "july": 7,
    "agt": 8, "agu": 8, "aug": 8, "agustus": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "okt": 10, "oct": 10,
    "oktober": 10, "october": 10, "nov": 11, "november": 11, "des": 12, "dec": 12, "desember": 12, "december": 12,
}


# ---------------------------------------------------------------- choosing the newest document
def _name_date(name: str) -> tuple[int, int]:
    """(year, month) in a file name such as 'Prospektus_X_Juli_2026.pdf' or 'pembaharuan_..._030524_1.pdf' (ddmmyy)."""
    years = [int(y) for y in re.findall(r"(?<!\d)(20\d\d)(?!\d)", name)]
    month = 0
    for word in re.findall(r"[A-Za-z]+", name):
        month = _MONTHS.get(word.lower(), month)
    if not years:
        m = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)", name)
        if m and 1 <= int(m.group(2)) <= 12:
            return 2000 + int(m.group(3)), int(m.group(2))
        return 0, 0
    return max(years), month


def pick_latest(items: list[dict]) -> dict | None:
    """The newest document in the list: by year and month in the file name; the later entry wins a tie.

    The list carries no dates, so this is an inference from names. The chosen name is stored so it can be checked."""
    best, best_key = None, (-1, -1, -1)
    for i, it in enumerate(items):
        year, month = _name_date(it.get("name", ""))
        if (year, month, i) > best_key:
            best, best_key = it, (year, month, i)
    return best


# ---------------------------------------------------------------- reading the portfolio table
_NUM = r"\d{1,3}(?:\.\d{3})+"
_ROW = re.compile(
    rf"(?P<pre>.*?)(?P<nominal>{_NUM})\s+(?P<price>\d{{1,3}},\d{{1,2}})\s+(?P<fair>{_NUM})\s+(?P<coupon>\d{{1,2}},\d{{1,3}}|-)\s+"
    r"(?P<mat>\d{1,2}-[A-Za-z]{3,4}-\d{2})\s+(?P<pct>\d{1,3},\d{1,2})")
_RATING = re.compile(r"^(?P<pre>id|ir)?(?P<core>AAA|AA|A|BBB|BB|B|CCC|CC|C|D)(?P<sign>[+-])?(?P<suf>\((?:idn|sy|id)\))?$", re.I)
_GOV = re.compile(r"\bFR\s?\d{3,4}|\bPBS\s?\d+|\bSBSN\b|\bSR\s?\d{3}|\bORI\s?\d+|\bINDOGB\b|obligasi\s+pemerintah|government\s+bond|"
                  r"sukuk\s+negara|surat\s+berharga\s+(?:syariah\s+)?negara|obligasi\s+negara", re.I)
_YEAR_ONLY = re.compile(r"^(20\d\d)$")
_TABLE_START = re.compile(r"^\d+\.\s*Portofolio\s+Efek\b.{0,40}$", re.I)       # a numbered heading, not a glossary sentence
_TABLE_END = re.compile(r"^(?:b\.\s+Efek|b\.\s+Equity|Jumlah\s+portofolio|Total\s+(?:portofolio|investment))", re.I)
_TOTAL = re.compile(r"^Jumlah\b.*?(\d{1,3},\d{1,2})(?:\s+Total)?\s*$", re.I)
RECONCILE_TOLERANCE = 1.0          # points: parsed total vs the 'Jumlah' line printed in the document
_FULL_DATE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3,9}),?\s+(20\d\d)")


def _to_float(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _maturity(text: str) -> date | None:
    d, mon, yy = text.split("-")
    month = _MONTHS.get(mon.lower())
    return date(2000 + int(yy), month, int(d)) if month else None


def rating_token(token: str | None) -> str | None:
    """The letter grade in a rating cell ('idAAA', 'AA(idn)', 'irAA', 'idA+'), or None if the text is not a rating.

    A bare 'A', 'B', 'C' or 'D' is NOT accepted: in these tables it is usually a series letter ('Seri B'), and reading it
    as a rating would invent a credit grade."""
    m = _RATING.match(token.strip()) if token else None
    if not m:
        return None
    bare = not (m["pre"] or m["suf"] or m["sign"])
    if bare and m["core"].upper() in ("A", "B", "C", "D", "CC"):
        return None
    return m["core"].upper() + (m["sign"] or "")


def rating_bucket(token: str | None) -> str:
    """AAA / AA / A / BBB (investment grade), 'spekulatif' (BB and below), or 'tanpa peringkat terbaca'."""
    grade = rating_token(token)
    if grade is None:
        return "tanpa peringkat terbaca"
    return {"AAA": "AAA", "AA": "AA", "A": "A", "BBB": "BBB"}.get(grade.rstrip("+-"), "spekulatif")


def _table_lines(rows: list[str]) -> tuple[list[tuple[int, str]], int]:
    """(index, text) of the lines that belong to the first debt table, and where it starts.

    It begins at the numbered 'Portofolio Efek' note; the first bond row marks the real table. It ends at the next
    sub-note, a total line, or the prior-year comparison table."""
    lines, start, active, year, found = [], 0, False, None, False
    for i, row in enumerate(rows):
        text = row.strip()
        if not active:
            active, start = (True, i) if _TABLE_START.match(text) else (False, start)
            continue
        found = found or bool(_ROW.search(text))
        if found and _TABLE_END.match(text):
            break
        if _YEAR_ONLY.match(text):
            if found and text != year:
                break
            year = text
        lines.append((i, text))
    return lines, start


def _bond(rows: list[str], i: int, m: re.Match, year: str | None) -> dict:
    text = rows[i].strip()
    pre = m["pre"].split()
    token = pre[-1] if pre else None
    if not (rating_token(token) or token == "-"):
        nxt = rows[i + 1].strip() if i + 1 < len(rows) else ""
        token = nxt if rating_token(nxt) else None                  # rating wrapped onto the next line
    gov = bool(_GOV.search(text) or _GOV.search(" ".join(rows[max(0, i - 2):i + 1])))
    return {"gov": gov, "rating": None if gov else token, "pct": _to_float(m["pct"]), "nominal": _to_float(m["nominal"]),
            "maturity": _maturity(m["mat"]), "year": year}


def parse_rows(rows: list[str]) -> dict:
    """The debt table from page rows (one string per visual row). Pure function; {'bonds': []} when it is not found.

    Government bonds are recognised by name; a corporate bond's rating is the token just before the face value, or a rating
    alone on the line after it (wrapped cell). A bond whose rating cannot be read is counted as 'tanpa peringkat terbaca',
    never as rated."""
    rows = [r.replace(" | ", " ") for r in rows]
    lines, start = _table_lines(rows)
    bonds, year, reported = [], None, None
    for i, text in lines:
        if _YEAR_ONLY.match(text):
            year = text
            continue
        total = _TOTAL.match(text)
        if total:
            reported = _to_float(total.group(1))              # the document's own total, to check the parse against
            continue
        m = _ROW.search(text)
        if m:
            bonds.append(_bond(rows, i, m, year))
    return {"bonds": bonds, "start": start, "reported_total": reported}


def position_date(rows: list[str], year: int | None = None) -> date | None:
    """The nearest date ('31 Desember 2025') at the end of `rows`, and only one in `year` when given.

    The year is the table's own heading, so a date from unrelated text (a licence from 2016, say) cannot be taken for the
    date of the financial statements."""
    for row in reversed(rows):
        for d, mon, yy in reversed(_FULL_DATE.findall(row.replace(" | ", " "))):
            if mon.lower() in _MONTHS and (year is None or int(yy) == year):
                return date(int(yy), _MONTHS[mon.lower()], int(d))
    return None


def summarize(rows: list[str]) -> dict:
    """Government/corporate split, rating spread, and weighted time to maturity of the whole portfolio. None when unreadable."""
    parsed = parse_rows(rows)
    bonds = parsed["bonds"]
    year = int(bonds[0]["year"]) if bonds and bonds[0]["year"] else None
    pos = position_date(rows[max(0, parsed["start"] - 25):parsed["start"] + 1], year) if bonds else None
    total = round(sum(b["pct"] for b in bonds), 2)
    reported = parsed["reported_total"]
    empty = {"n_bonds": len(bonds), "position_date": pos, "parsed_pct": total, "reported_total_pct": reported, "reconciled": False,
             "covered_pct": None, "gov_pct": None, "corp_pct": None, "investment_grade_pct": None, "unrated_pct": None,
             "ratings": None, "wam_years": None}
    if len(bonds) < MIN_ROWS or total <= 0 or total > 100.5:
        return empty
    if reported is None or abs(total - reported) > RECONCILE_TOLERANCE:
        return empty                                          # part of the table was missed: report nothing rather than a partial picture
    gov = sum(b["pct"] for b in bonds if b["gov"])
    corp = [b for b in bonds if not b["gov"]]
    spread: dict[str, float] = {}
    for b in corp:
        spread[rating_bucket(b["rating"])] = spread.get(rating_bucket(b["rating"]), 0.0) + b["pct"]
    wam = None
    if pos is not None and all(b["maturity"] for b in bonds):
        wam = sum(b["pct"] * max((b["maturity"] - pos).days, 0) / 365.25 for b in bonds) / total
    return {"n_bonds": len(bonds), "position_date": pos, "parsed_pct": total, "reported_total_pct": reported, "reconciled": True,
            "covered_pct": round(total, 2), "gov_pct": round(gov, 2),
            "corp_pct": round(total - gov, 2), "investment_grade_pct": round(sum(spread.get(k, 0.0) for k in ("AAA", "AA", "A", "BBB")), 2),
            "unrated_pct": round(spread.get("tanpa peringkat terbaca", 0.0), 2),
            "ratings": {k: round(v, 2) for k, v in spread.items()}, "wam_years": None if wam is None else round(wam, 2)}


# ---------------------------------------------------------------- policy sentences (quoted, not interpreted)
_LIMIT = re.compile(r"(?:minimum|minimal|paling\s+sedikit)\s+(?:sebesar\s+)?\d{1,3}%[^.;]{0,250}?"
                    r"(?:maksimum|maksimal|paling\s+banyak)\s+(?:sebesar\s+)?\d{1,3}%[^.]{0,260}", re.I)
_GRADE = re.compile(r"peringkat[^.]{0,60}(?:layak\s+investasi|investasi)[^.]{0,260}", re.I)


def policy_start(flat: str) -> int:
    """Where the investment-policy limits begin in whitespace-normalised text: just after the first 'Kebijakan Investasi'
    heading that is followed by a minimum/maximum sentence, else the start of the text."""
    for m in re.finditer(r"kebijakan\s+investasi", flat, re.I):
        if _LIMIT.search(flat[m.end():m.end() + 900]):
            return m.end()
    return 0


def policy_quotes(text: str, limit: int = 4) -> list[str]:
    """The first few min/max sentences after the 'Kebijakan Investasi' heading, verbatim (whitespace tidied), plus the
    sentence about the required rating if there is one."""
    flat = re.sub(r"\s+", " ", text)
    start = policy_start(flat)
    out = [q.strip() for q in (m.group(0) for m in _LIMIT.finditer(flat[start:start + 12000]))][:limit]
    grade = _GRADE.search(flat[start:start + 12000])
    if grade and grade.group(0).strip() not in out:
        out.append(grade.group(0).strip())
    return out


# ---------------------------------------------------------------- PDF access
def page_rows(pdf: bytes) -> tuple[list[str], str]:
    """(visual rows with cells joined by ' | ', plain text) of the document."""
    rows, texts = [], []
    with factsheet._open(pdf) as doc:
        for page in doc:
            texts.append(page.get_text())
            by_y: dict[int, list] = {}
            for w in page.get_text("words"):
                by_y.setdefault(round(w[1] / 3), []).append(w)
            for key in sorted(by_y):
                rows.append(" | ".join(w[4] for w in sorted(by_y[key], key=lambda x: x[0])))
    return rows, "\n".join(texts)


def _meta_path(code: str, cache: Path) -> Path:
    return cache / f"{code}.json"


def fetch_latest(code: str, cache: Path = CACHE, log=print) -> tuple[bytes, dict]:
    """PDF bytes and {name, url} of the newest prospectus; served from the cache while the newest file name is unchanged."""
    items = json.loads(factsheet._get(LIST_API.format(code=code)))["data"]
    pick = pick_latest(items)
    if pick is None:
        raise ValueError(f"{code}: belum ada prospektus")
    pdf_path, meta_path = cache / f"{code}.pdf", _meta_path(code, cache)
    if pdf_path.exists() and meta_path.exists() and json.loads(meta_path.read_text(encoding="utf-8")).get("name") == pick["name"]:
        return pdf_path.read_bytes(), {"name": pick["name"], "url": pick["file"], "cached": True}
    log(f"  mengunduh {pick['name']} ...")
    pdf = factsheet._get(pick["file"], timeout=180)
    cache.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(pdf)
    meta_path.write_text(json.dumps({"name": pick["name"], "url": pick["file"]}, ensure_ascii=False), encoding="utf-8")
    return pdf, {"name": pick["name"], "url": pick["file"], "cached": False}


def read_fund(code: str, cache: Path = CACHE, log=print) -> dict:
    """Everything this module can say about one fund's newest prospectus."""
    pdf, meta = fetch_latest(code, cache, log)
    rows, text = page_rows(pdf)
    return {**summarize(rows), "policy": policy_quotes(text), "file": meta["name"], "url": meta["url"],
            "fetched": datetime.now().date().isoformat()}
