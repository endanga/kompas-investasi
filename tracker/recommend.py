"""Robo-style recommender: user's tolerance + horizon -> Bibit risk level -> funds per category.

Every step is a visible rule. Past returns do not predict the future, so the ranking leans on
drawdown, size and track record rather than on last year's winner. This is a learning aid, not licensed advice.
"""
from __future__ import annotations

import math
import re
from datetime import date
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import metrics

MIN_AUM_IDR = 100e9  # ignore funds smaller than Rp100 miliar (closure/liquidity risk)
TOP_N = 3
INDEX_LIKE = re.compile(r"indeks|index|idx|lq\s?45|kehati|msci|ihsg", re.I)
FOREIGN_CCY = re.compile(r"\busd\b|dolar|dollar", re.I)
LEVEL_KEY = re.compile(r"^bibit_([\d.]+)_")

# Weight of each criterion (percentile rank inside the category, higher = better). Sums to 1 per category.
WEIGHTS = {
    "pasar_uang": {"return_1y_pct": 0.40, "aum_idr": 0.30, "drawdown_1y_pct": 0.30},
    # A flat price is not safety: a fund of corporate bonds can look calm until one issuer defaults. So the share of
    # government bonds in the top holdings (fact sheet) counts too. An unreadable fact sheet is scored like the WORST
    # readable fund: unknown must never beat a fund that is known to be corporate.
    "pendapatan_tetap": {"return_3y_ann": 0.25, "drawdown_1y_pct": 0.15, "aum_idr": 0.25, "gov_top10_pct": 0.35},
    # Index funds get the biggest weight: simple, transparent holdings, and one lucky active year proves little.
    "saham": {"drawdown_1y_pct": 0.25, "aum_idr": 0.25, "index_like": 0.35, "return_3y_pct": 0.15},
    "campuran": {"drawdown_1y_pct": 0.35, "aum_idr": 0.25, "return_3y_pct": 0.40},
}
CRITERIA_LABEL = {
    "return_1y_pct": "return 1 tahun",
    "return_3y_pct": "return 3 tahun",
    "drawdown_1y_pct": "penurunan terdalam kecil",
    "aum_idr": "dana kelolaan besar",
    "return_3y_ann": "return 3 tahun per tahun",
    "gov_top10_pct": "isi didominasi obligasi negara",
    "index_like": "berbasis indeks",
}


def horizon_level_cap(horizon_years: float) -> float:
    """Generic rule: the shorter the goal, the lower the highest Bibit level considered."""
    if horizon_years < 3:
        return 3.0
    if horizon_years < 5:
        return 5.0
    return 10.0


def level_of(profile_key: str) -> float | None:
    m = LEVEL_KEY.match(profile_key)
    return float(m.group(1)) if m else None


def eligible(products: pd.DataFrame, category: str, syariah_only: bool, min_aum: float = MIN_AUM_IDR) -> pd.DataFrame:
    df = products[products["category"] == category]
    df = df[~df["name"].str.contains(FOREIGN_CCY)]
    df = df[df["aum_idr"].fillna(0) >= min_aum]
    df = df[df["return_1y_pct"].notna() & df["drawdown_1y_pct"].notna()]
    if category != "pasar_uang":
        df = df[df["return_3y_pct"].notna()]  # needs a 3-year track record
    if syariah_only:
        df = df[df["syariah_dari_nama"] == "ya"]
    return df.copy()


OPTIONAL = {"gov_top10_pct"}   # criteria that may be unknown for some funds, or absent from an older products file


def _ann(total_pct: float, years: float) -> float:
    r = metrics.annualize_total_return(total_pct, years) if pd.notna(total_pct) else None
    return np.nan if r is None else r * 100


SOURCES = {
    "return_3y_ann": "tabel produk Bibit", "return_1y_pct": "tabel produk Bibit", "return_3y_pct": "tabel produk Bibit",
    "drawdown_1y_pct": "tabel produk Bibit (1 tahun)", "aum_idr": "tabel produk Bibit",
    "gov_top10_pct": "fund fact sheet (10 besar)", "index_like": "nama produk (tebakan)",
}


def _percentiles(df: pd.DataFrame, col: str) -> pd.Series:
    """Percentile rank inside the category (higher = better). Missing values are never rewarded:
    a required criterion scores 0, an optional one scores like the worst fund whose value IS known."""
    ranks = df[col].rank(pct=True, na_option="keep")
    if col in OPTIONAL:
        floor = ranks.min() if ranks.notna().any() else 0.0
        return ranks.fillna(floor)
    return ranks.fillna(0.0)


def _weights(df: pd.DataFrame, category: str) -> dict[str, float]:
    """The criteria actually used: an optional one with no data at all is left out instead of counted as zero."""
    return {c: w for c, w in WEIGHTS.get(category, WEIGHTS["campuran"]).items() if df[c].notna().any() or c not in OPTIONAL}


def score_breakdown(ranked: pd.DataFrame, category: str, name: str) -> pd.DataFrame:
    """Per-criterion view of one fund's quality score: value, percentile inside the category, weight and source.

    This is the PRODUCT quality score. How risky the whole portfolio is lives elsewhere (stress tests).
    """
    weights = _weights(ranked, category)
    total_w = sum(weights.values())
    row = ranked[ranked["name"] == name].iloc[0]
    rows = []
    for col, w in weights.items():
        known = pd.notna(row[col])
        pct = _percentiles(ranked, col).loc[row.name]
        rows.append({"kriteria": CRITERIA_LABEL.get(col, col), "nilai": row[col] if known else None,
                     "persentil": round(float(pct), 2), "bobot": round(w / total_w, 3),
                     "sumber": SOURCES.get(col, "-") if known else SOURCES.get(col, "-") + " (tidak terbaca, dinilai setara dana terburuk yang terbaca)"})
    return pd.DataFrame(rows)


def rank_category(products: pd.DataFrame, category: str, syariah_only: bool = False,
                  min_aum: float = MIN_AUM_IDR) -> pd.DataFrame:
    """Eligible funds of one category, best first, with a score and a plain-language reason."""
    df = eligible(products, category, syariah_only, min_aum)
    if df.empty:
        return df
    df["return_3y_ann"] = df["return_3y_pct"].map(lambda x: _ann(x, 3))
    if "gov_top10_pct" not in df:                      # a products file from before fact sheets were read
        df["gov_top10_pct"] = np.nan
    df["index_like"] = df["name"].str.contains(INDEX_LIKE).astype(float)
    weights = _weights(df, category)
    total_w = sum(weights.values())
    score = pd.Series(0.0, index=df.index)
    for col, w in weights.items():
        score += (w / total_w) * _percentiles(df, col)
    df["score"] = (score * 100).round(1)
    df = df.sort_values(["score", "aum_idr"], ascending=False)

    def reason(row: pd.Series) -> str:
        strong = [
            CRITERIA_LABEL[c] for c, _ in sorted(weights.items(), key=lambda kv: -kv[1])
            if df[c].rank(pct=True).loc[row.name] >= 0.7
        ]
        return ", ".join(strong[:3]) if strong else "skor seimbang"

    df["alasan"] = df.apply(reason, axis=1)
    return df


@dataclass
class Recommendation:
    profile_key: str
    level: float
    allocation: dict[str, float]
    picks: dict[str, pd.DataFrame]
    monthly_amounts: dict[str, float]
    stress_loss: float
    within_limit: bool
    shocks: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # Filled by portfolio_plan.apply: the risk level's own mix, and how this month's deposit closes the gap to it.
    target_allocation: dict[str, float] = field(default_factory=dict)
    plan: object | None = None
    checks: list = field(default_factory=list)      # metrics.stress_checks of the chosen level (strict rule)
    strict: bool = False
    crisis: dict = field(default_factory=dict)       # the crisis assumption the checks used
    gov_share: float | None = None                   # least government share among the bond picks (None = no bond picks)


STALE_DAYS = 30   # product data older than this is called out: prices and fact sheets may have moved


def conservative_gov_share(rankings: dict[str, pd.DataFrame]) -> float | None:
    """Least government share (0-1) among the top bond picks; an unreadable fact sheet counts as 0, never as safe."""
    bonds = rankings.get("pendapatan_tetap")
    if bonds is None or bonds.empty or "gov_top10_pct" not in bonds:
        return None
    return float(bonds.head(TOP_N)["gov_top10_pct"].fillna(0.0).min()) / 100


def quality_notes(products: pd.DataFrame, rankings: dict[str, pd.DataFrame], today: date | None = None) -> list[str]:
    """Warnings about the data the recommendation stands on. Missing data is never silently treated as fine."""
    notes = []
    if "as_of" in products and products["as_of"].notna().any():
        age = ((today or date.today()) - pd.to_datetime(products["as_of"].iloc[0]).date()).days
        if age > STALE_DAYS:
            notes.append(f"Data produk berumur {age} hari (lebih dari {STALE_DAYS}). Harga dan fund fact sheet mungkin sudah "
                         "berubah; perbarui data sebelum membeli.")
    bonds = rankings.get("pendapatan_tetap")
    if bonds is not None and not bonds.empty:
        top = bonds.head(TOP_N)
        if "factsheet_date" in top and "as_of" in products and products["as_of"].notna().any():
            ref = pd.to_datetime(products["as_of"].iloc[0])
            dates = pd.to_datetime(top["factsheet_date"], errors="coerce")
            old = [n for n, d in zip(top["name"], dates) if pd.notna(d) and (ref - d).days > FACTSHEET_STALE_DAYS]
            if old:
                notes.append(f"Fund fact sheet berumur lebih dari {FACTSHEET_STALE_DAYS} hari untuk: " + ", ".join(old)
                             + ". Isi dana mungkin sudah berubah.")
        gov = top["gov_top10_pct"] if "gov_top10_pct" in top else pd.Series(np.nan, index=top.index)
        unread = [n for n, g in zip(top["name"], gov) if pd.isna(g)]
        if unread:
            notes.append("Komposisi belum terverifikasi untuk dana obligasi pilihan: " + ", ".join(unread)
                         + ". Risiko kredit dana ini tidak diketahui; stress test menganggapnya tanpa obligasi negara.")
        elif (gov < 30).any():
            notes.append("Sebagian dana obligasi pilihan mayoritas berisi obligasi korporasi: harganya bisa tampak stabil, "
                         "tetapi risiko gagal bayar penerbit tidak terlihat di grafik harga.")
    return notes


FACTSHEET_STALE_DAYS = 60


def level_notes(level: float, allocation: dict[str, float]) -> list[str]:
    """What the user must know about the level itself: where its mix comes from, and what is never verified."""
    notes = []
    if level not in VERIFIED_LEVELS:
        notes.append(f"Komposisi profil risiko {level:g} berasal dari catatan Anda dan belum dicocokkan dengan aplikasi Bibit. "
                     "Cocokkan pembagiannya di aplikasi Bibit sebelum membeli.")
    if allocation.get("pendapatan_tetap", 0) > 0:
        notes.append("Rating kredit dan durasi dana obligasi tidak tersedia di data ini dan tidak pernah diverifikasi; "
                     "stress test memakai asumsi untuk keduanya.")
    return notes


def _skipped_note(level: float, checks: list[dict]) -> str:
    bad = next(c for c in checks if not c["passed"])
    why = ("melewati batas" if bad["crossed"]
           else f"ruangnya hanya {bad['margin_points']:+.2f} poin (kurang dari {metrics.MARGIN_THIN * 100:g})")
    return (f"Profil risiko {level:g} tidak dipilih otomatis: {bad['name'].lower()} {bad['loss'] * 100:.1f}%, {why} "
            "terhadap batas Anda. Ini simulasi, bukan batas kerugian aktual.")


def recommend(products: pd.DataFrame, profiles: dict[str, dict[str, float]], max_drop: float,
              horizon_years: float, monthly_budget: float, syariah_only: bool = False,
              crisis: dict[str, float] | None = None, strict: bool = True, today: date | None = None) -> Recommendation:
    """Pick the highest Bibit level that fits `max_drop`.

    strict=True (default): a level fits only if EVERY check in `metrics.stress_checks` passes with room to spare: the bad
    year estimated from fund prices, the user's crisis assumption, and the worst separate scenario. One scenario or a margin
    under 1 percentage point is not enough. strict=False keeps the older rule (bad-year estimate only, no margin).
    """
    rankings, shocks = _rank_and_shock(products, syariah_only)
    crisis = metrics.crisis_shocks() if crisis is None else crisis
    gov = conservative_gov_share(rankings)

    cap = horizon_level_cap(horizon_years)
    levels = sorted(((level_of(k), k) for k in profiles if level_of(k) is not None), reverse=True)
    levels = [(lv, k) for lv, k in levels if lv <= cap]
    notes: list[str] = []
    if cap < 10:
        notes.append(f"Tujuan {horizon_years:g} tahun: level dibatasi maksimal {cap:g} (aturan umum, makin pendek makin aman).")

    chosen, skipped = None, []
    for lv, key in levels:
        if strict:
            checks = metrics.stress_checks(profiles[key], shocks, crisis, gov, max_drop)
            ok = all(c["passed"] for c in checks)
            if not ok:
                skipped.append((lv, checks))
        else:
            ok = -metrics.stress_loss(profiles[key], shocks) <= max_drop
        if ok:
            chosen = (lv, key)
            break
    within = chosen is not None
    if chosen is None:
        chosen = levels[-1]
        notes.append("Tidak ada level yang memenuhi semua pemeriksaan risiko Anda; ditampilkan level paling konservatif. "
                     "Pertimbangkan menaikkan batas atau memperpanjang horizon.")
    lv, key = chosen
    checks = metrics.stress_checks(profiles[key], shocks, crisis, gov, max_drop) if strict else []
    if strict and skipped and within:
        notes.append(_skipped_note(*skipped[-1]))       # the level just above the one chosen
    notes += quality_notes(products, rankings, today) + level_notes(lv, profiles[key])
    rec = _assemble(rankings, shocks, profiles[key], key, lv, monthly_budget, within, notes)
    rec.checks, rec.strict, rec.crisis, rec.gov_share = checks, strict, crisis, gov
    return rec


VERIFIED_LEVELS = (4.5, 5.0)   # compositions checked against the Bibit app; the rest come from the user's own notes


def compare_levels(products: pd.DataFrame, profiles: dict[str, dict[str, float]], levels: list[float], max_drop: float,
                   crisis: dict[str, float], rates: dict[str, dict[str, float]], monthly_budget: float, horizon_years: float,
                   syariah_only: bool = False) -> list[dict]:
    """Risk levels side by side under IDENTICAL shocks, crisis, scenarios and return assumptions.

    Each row: allocation, the three stress checks (bad year from data, crisis assumption, worst separate scenario) with their
    room under the limit, the projection under every return scenario (assumptions, not predictions), and the weaknesses.
    """
    rankings, shocks = _rank_and_shock(products, syariah_only)
    gov = conservative_gov_share(rankings)
    by_level = {level_of(k): k for k in profiles if level_of(k) is not None}
    rows = []
    for lv in sorted(set(levels)):
        if lv not in by_level:
            continue
        a = profiles[by_level[lv]]
        checks = metrics.stress_checks(a, shocks, crisis, gov, max_drop)
        weak = []
        if lv not in VERIFIED_LEVELS:
            weak.append("komposisi belum dicocokkan dengan aplikasi Bibit (dari catatan Anda)")
        if gov is None or gov == 0:
            weak.append("risiko kredit obligasi belum terverifikasi atau didominasi korporasi")
        rows.append({
            "level": lv, "allocation": {c: v for c, v in a.items() if v > 0}, "checks": checks,
            "meets_all": all(c["passed"] for c in checks),
            "projection": {name: metrics.future_value_dca(monthly_budget, metrics.blended_rate(a, r), horizon_years)
                           for name, r in rates.items()},
            "weaknesses": weak,
        })
    return rows


def for_level(products: pd.DataFrame, profiles: dict[str, dict[str, float]], profile_key: str,
              monthly_budget: float, syariah_only: bool = False, max_drop: float | None = None,
              crisis: dict[str, float] | None = None) -> Recommendation:
    """Recommendation for one specific Bibit level, regardless of the user's own tolerance.

    `max_drop` only sets the `within_limit` flag; it never changes the chosen level.
    """
    rankings, shocks = _rank_and_shock(products, syariah_only)
    lv = level_of(profile_key)
    rec = _assemble(rankings, shocks, profiles[profile_key], profile_key, lv if lv is not None else 0.0,
                    monthly_budget, True, [])
    rec.crisis = metrics.crisis_shocks() if crisis is None else crisis
    rec.gov_share = conservative_gov_share(rankings)
    if max_drop is not None:
        rec.checks = metrics.stress_checks(profiles[profile_key], shocks, rec.crisis, rec.gov_share, max_drop)
        rec.within_limit = all(c["passed"] for c in rec.checks)
        rec.strict = True
    rec.notes += quality_notes(products, rankings) + level_notes(rec.level, rec.allocation)
    return rec


def _rank_and_shock(products: pd.DataFrame, syariah_only: bool) -> tuple[dict[str, pd.DataFrame], dict[str, float]]:
    rankings = {c: rank_category(products, c, syariah_only) for c in ("pasar_uang", "pendapatan_tetap", "saham", "campuran")}
    # Stress test deliberately uses a bad-but-plausible shock per category: the worse of (a) the deepest
    # drawdown among the top picks and (b) the median drawdown of all eligible funds in the category.
    # Using only the #1 pick would be flattering (e.g. a bond fund that happened to drop 0%).
    shocks = dict(metrics.DEFAULT_SHOCKS)
    for cat, ranked in rankings.items():
        if not ranked.empty:
            worst_top = float(ranked.head(TOP_N)["drawdown_1y_pct"].min())
            median_all = float(ranked["drawdown_1y_pct"].median())
            shocks[cat] = min(worst_top, median_all) / 100.0
    return rankings, shocks


def _assemble(rankings: dict[str, pd.DataFrame], shocks: dict[str, float], profile: dict[str, float],
              key: str, level: float, monthly_budget: float, within: bool, notes: list[str]) -> Recommendation:
    alloc = {c: s for c, s in profile.items() if s > 0}
    picks, amounts = {}, {}
    for cat, share in alloc.items():
        ranked = rankings.get(cat, pd.DataFrame())
        if ranked.empty:
            notes.append(f"Tidak ada produk {cat} yang lolos saringan (AUM, riwayat 3 tahun, rupiah).")
            continue
        picks[cat] = ranked.head(TOP_N)
        amounts[cat] = monthly_budget * share
    loss = metrics.stress_loss(alloc, shocks)
    return Recommendation(key, level, alloc, picks, amounts, loss, within, shocks, notes)


# Annual return ASSUMPTIONS per category for the what-if projection (editable in the UI). Not forecasts.
# Rough anchors: money-market funds on Bibit returned ~4%/yr over the last year; Obligasi FR yields were
# ~5-7% in the snapshot; equities have no safe anchor (the last 1-5 years were negative), so the range is wide.
DEFAULT_SCENARIOS = {
    "Pesimis": {"pasar_uang": 0.03, "pendapatan_tetap": 0.04, "saham": 0.00, "campuran": 0.02},
    "Dasar": {"pasar_uang": 0.04, "pendapatan_tetap": 0.06, "saham": 0.08, "campuran": 0.06},
    "Optimis": {"pasar_uang": 0.05, "pendapatan_tetap": 0.08, "saham": 0.12, "campuran": 0.09},
}


def history_compare(allocation: dict[str, float], picks: dict[str, pd.Series]) -> dict[str, float | None]:
    """Allocation-weighted past returns/drawdown of one fund per category (rough: ignores rebalancing).

    Drawdowns are summed as if every fund hit its worst point together, which overstates the real loss a bit.
    """
    out: dict[str, float | None] = {}
    for key in ("return_1y_pct", "return_3y_pct", "return_5y_pct", "drawdown_1y_pct"):
        total = 0.0
        for cat, share in allocation.items():
            if share <= 0:
                continue  # unused category (e.g. 0% campuran) needs no fund
            val = picks.get(cat, pd.Series(dtype=float)).get(key)
            if val is None or pd.isna(val):
                total = float("nan")
                break
            total += share * float(val)
        out[key] = None if math.isnan(total) else round(total, 2)
    return out


def start_plan(monthly_budget: float, steps: tuple[float, ...] = (0.4, 0.7, 1.0)) -> list[tuple[str, float]]:
    """Gradual ramp-up so a beginner experiences ups and downs before committing the full amount."""
    labels = ("Bulan 1-3", "Bulan 4-6", "Bulan 7 dst")
    return [(label, monthly_budget * frac) for label, frac in zip(labels, steps)]
