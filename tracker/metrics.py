"""Deterministic portfolio metrics. All numbers shown to the user come from here, never from an LLM."""
from __future__ import annotations

from datetime import date

import math

import numpy as np
import pandas as pd


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    """Annualised internal rate of return for dated cashflows.

    Outflows (investments) are negative, inflows (current value, sells) positive.
    Returns None when there is no valid solution (needs both signs, and a span > 0 days).
    """
    if len(cashflows) < 2:
        return None
    amounts = np.array([cf for _, cf in cashflows], dtype=float)
    if not (amounts.min() < 0 < amounts.max()):
        return None
    t0 = min(d for d, _ in cashflows)
    years = np.array([(d - t0).days / 365.0 for d, _ in cashflows])
    if years.max() == 0:
        return None

    def npv(rate: float) -> float:
        return float(np.sum(amounts / (1.0 + rate) ** years))

    lo, hi = -0.999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def portfolio_xirr(transactions: pd.DataFrame, current_value: float, as_of: date) -> float | None:
    """XIRR of a whole portfolio. BUY = outflow, SELL = inflow, current value = final inflow."""
    flows = []
    for row in transactions.itertuples():
        sign = -1.0 if row.type == "BUY" else 1.0
        flows.append((row.date.date() if hasattr(row.date, "date") else row.date, sign * float(row.amount)))
    flows.append((as_of, float(current_value)))
    return xirr(flows)


def total_invested(transactions: pd.DataFrame) -> float:
    """Net money put in: buys minus sells."""
    buys = transactions.loc[transactions["type"] == "BUY", "amount"].sum()
    sells = transactions.loc[transactions["type"] == "SELL", "amount"].sum()
    return float(buys - sells)


def allocation_by(holdings: pd.DataFrame, column: str) -> pd.Series:
    """Share (0-1) of current value per `column` (e.g. 'category' or 'product')."""
    total = holdings["current_value"].sum()
    if total <= 0:
        return pd.Series(dtype=float)
    return (holdings.groupby(column)["current_value"].sum() / total).sort_values(ascending=False)


def max_drawdown(values: pd.Series) -> float:
    """Largest peak-to-trough fall of a value/NAV series, as a negative fraction (e.g. -0.12)."""
    if values.empty:
        return 0.0
    running_peak = values.cummax()
    return float(((values - running_peak) / running_peak).min())


def future_value_dca(monthly: float, annual_rate: float, years: float, initial: float = 0.0) -> float:
    """Projected value of an initial sum plus monthly deposits (end of month).

    `annual_rate` is an effective yearly return (what a fund's year-on-year return means), so the monthly rate is
    (1 + annual) ** (1/12) - 1 and twelve months compound back to exactly `annual_rate`. Fund returns are already net of
    the fund's own fees. This is a what-if on an *assumed* rate, not a forecast.
    """
    n = int(round(years * 12))
    r = (1 + annual_rate) ** (1 / 12) - 1
    if r == 0:
        return initial + monthly * n
    return initial * (1 + r) ** n + monthly * (((1 + r) ** n - 1) / r)


def annualize_total_return(total_pct: float, years: float) -> float | None:
    """Turn a cumulative return over `years` (in %) into a per-year fraction. None if it lost everything."""
    if years <= 0 or total_pct <= -100:
        return None
    return (1 + total_pct / 100.0) ** (1.0 / years) - 1


def blended_rate(allocation: dict[str, float], rates: dict[str, float]) -> float:
    """Allocation-weighted annual rate. Categories without a rate count as 0."""
    return float(sum(share * rates.get(cat, 0.0) for cat, share in allocation.items()))


def deflate(value: float, inflation: float, years: float) -> float:
    """Express a future rupiah amount in today's purchasing power."""
    return value / (1 + inflation) ** years


# Hypothetical bad-year price shocks per category, for stress-testing an allocation.
# These are ASSUMPTIONS for illustration, not measured history. Check real max drawdown on each product's page.
DEFAULT_SHOCKS = {
    "pasar_uang": 0.0,
    "pendapatan_tetap": -0.05,
    "sbn": -0.05,
    "campuran": -0.15,
    "saham": -0.30,
}


def crisis_shocks(saham_pct: float = 40.0, obligasi_pct: float = 8.0, pasar_uang_pct: float = 0.0) -> dict[str, float]:
    """Severe-crisis price shocks (negative fractions) from three percentages the user can set.

    These are ASSUMPTIONS, not measured history: the data only covers the last year. Mixed funds are taken as 60% stocks
    and 40% bonds, and SBN moves like bonds.
    """
    saham, obl, pu = -saham_pct / 100, -obligasi_pct / 100, -pasar_uang_pct / 100
    return {"saham": saham, "pendapatan_tetap": obl, "sbn": obl, "pasar_uang": pu, "campuran": 0.6 * saham + 0.4 * obl}


# Separate hypothetical scenarios (ASSUMPTIONS, not measured history). Each gives a price shock per holding type.
# Bonds are split into government and corporate because they do not fail the same way.
# Durations are scenario inputs, not facts about any product: the fact sheets do not state them. As a rough, general
# reference (not read from this data) Indonesian government-bond funds are often medium duration (about 3-7 years),
# corporate-bond funds shorter (about 1-3 years), and short-duration index funds around 1-2. The defaults below sit inside
# those ranges; the sensitivity tests move them.
YIELD_RISE = 0.02          # +2 percentage points
DUR_NEGARA = 4.0
DUR_KORPORASI = 3.0
UNKNOWN_GOV_SHARE = 0.5    # only for the single-number fallback; the app shows a range when holdings are unknown
CORPORATE_EXPOSURES = (0.25, 0.5, 1.0)


def scenarios(dur_negara: float = DUR_NEGARA, dur_korporasi: float = DUR_KORPORASI, yield_rise: float = YIELD_RISE,
              scale: float = 1.0) -> tuple:
    """The scenario list. Price fall in a yield scenario = duration x yield rise (first-order; ignores convexity and carry).
    `scale` multiplies every shock, to ask 'what if everything is worse than assumed'."""
    raw = (
        ("Saham jatuh", "Pasar saham turun 40%, obligasi korporasi ikut turun sedikit.",
         {"saham": -0.40, "obl_negara": 0.0, "obl_korporasi": -0.03, "pasar_uang": 0.0}),
        ("Yield obligasi negara naik 2 poin",
         f"Suku bunga naik {yield_rise * 100:g} poin; harga turun sebesar durasi x kenaikan (asumsi durasi {dur_negara:g} tahun "
         f"untuk obligasi negara dan {dur_korporasi:g} tahun untuk korporasi).",
         {"saham": -0.05, "obl_negara": -dur_negara * yield_rise, "obl_korporasi": -dur_korporasi * yield_rise, "pasar_uang": 0.0}),
        ("Spread kredit melebar", "Investor menuntut imbal lebih untuk risiko korporasi; obligasi negara relatif aman.",
         {"saham": -0.10, "obl_negara": 0.0, "obl_korporasi": -0.07, "pasar_uang": 0.0}),
        ("Gagal bayar penerbit korporasi besar",
         "Satu penerbit besar (sekitar 10% dari porsi korporasi) gagal bayar dan nilainya nol.",
         {"saham": 0.0, "obl_negara": 0.0, "obl_korporasi": -0.10, "pasar_uang": 0.0}),
        ("Tekanan likuiditas", "Banyak investor menjual bersamaan; aset dijual dengan diskon.",
         {"saham": -0.10, "obl_negara": -0.03, "obl_korporasi": -0.08, "pasar_uang": -0.005}),
    )
    return tuple((n, note, {k: v * scale for k, v in sh.items()}) for n, note, sh in raw)


SCENARIOS = scenarios()


KNOWN_CATEGORIES = ("pasar_uang", "pendapatan_tetap", "campuran", "saham", "sbn")


def _buckets(allocation: dict[str, float], gov_share: float) -> dict[str, float]:
    bond = allocation.get("pendapatan_tetap", 0.0) + 0.4 * allocation.get("campuran", 0.0)
    other = sum(v for c, v in allocation.items() if c not in KNOWN_CATEGORIES)     # unknown kinds count as stocks, never as safe
    return {
        "saham": allocation.get("saham", 0.0) + 0.6 * allocation.get("campuran", 0.0) + other,
        "obl_negara": allocation.get("sbn", 0.0) + gov_share * bond,
        "obl_korporasi": (1 - gov_share) * bond,
        "pasar_uang": allocation.get("pasar_uang", 0.0),
    }


def scenario_losses(allocation: dict[str, float], gov_share: float | None = None, **scenario_args) -> list[dict]:
    """Portfolio fall for each scenario (negative fractions).

    `gov_share` (0-1) is the share of bond funds in government bonds. None means UNKNOWN: a flagged 50/50 placeholder is
    used here, and `gov_share_known` is False so callers must not present the result as fact (see `scenario_range`).
    Mixed funds count as 60% stocks, 40% bonds; SBN counts as government bonds. `scenario_args` go to `scenarios`.
    """
    known = gov_share is not None
    g = UNKNOWN_GOV_SHARE if gov_share is None else min(max(gov_share, 0.0), 1.0)
    buckets = _buckets(allocation, g)
    no_bonds = buckets["obl_korporasi"] + buckets["obl_negara"] == 0
    return [{"name": name, "note": note, "loss": sum(share * shocks[b] for b, share in buckets.items()),
             "gov_share_known": known or no_bonds} for name, note, shocks in scenarios(**scenario_args)]


def scenario_range(allocation: dict[str, float], exposures=CORPORATE_EXPOSURES, **scenario_args) -> list[dict]:
    """Scenario losses for each assumed corporate share of the bond funds (use when the holdings are not verified).

    Returns one row per scenario: name, note and `losses` = {corporate exposure: loss}.
    """
    per_exposure = {e: scenario_losses(allocation, 1 - e, **scenario_args) for e in exposures}
    return [{"name": row["name"], "note": row["note"], "losses": {e: per_exposure[e][i]["loss"] for e in exposures}}
            for i, row in enumerate(per_exposure[exposures[0]])]


CRISIS_GRID_SAHAM = (30, 40, 50)
CRISIS_GRID_OBLIGASI = (3, 8, 12)


def crisis_grid(allocation: dict[str, float], saham=CRISIS_GRID_SAHAM, obligasi=CRISIS_GRID_OBLIGASI,
                pasar_uang_pct: float = 0.0) -> list[list[float]]:
    """Portfolio fall (negative fraction) for every stock x bond crisis pair: one row per stock fall, one column per bond fall."""
    return [[stress_loss(allocation, crisis_shocks(s, o, pasar_uang_pct)) for o in obligasi] for s in saham]


def stress_loss(allocation: dict[str, float], shocks: dict[str, float] | None = None, unknown_shock: float = 0.0) -> float:
    """Portfolio fall (negative fraction) if every category hits its shock at once.

    A category without a shock gets `unknown_shock`. The default 0.0 is the historical behaviour; the strict checks pass
    the worst known shock instead, because a category the table does not know must not count as risk-free.
    """
    shocks = DEFAULT_SHOCKS if shocks is None else shocks
    return float(sum(share * shocks.get(cat, unknown_shock) for cat, share in allocation.items()))


MARGIN_THIN = 0.01   # less than one percentage point of room counts as thin: the estimate itself is not that precise
MARGIN_TOL = 1e-9    # float noise: 0.12 - 0.11 is 0.00999999..., which is exactly one point of room, not "thin"


def margin_to_limit(loss: float, limit: float, base: float) -> dict:
    """Room left under the user's loss limit: percentage points, rupiah on `base`, and whether it is thin or already crossed.

    `loss` is a negative fraction, `limit` a positive fraction. A positive margin means the estimate sits inside the limit.
    The estimate is a simulation, so even a comfortable margin is not a cap on real losses.
    """
    if not (math.isfinite(loss) and math.isfinite(limit) and math.isfinite(base)):
        return {"points": float("nan"), "rupiah": float("nan"), "thin": False, "crossed": False, "invalid": True}
    margin = limit + loss
    return {"points": margin * 100, "rupiah": margin * base, "thin": -MARGIN_TOL <= margin < MARGIN_THIN - MARGIN_TOL,
            "crossed": margin < -MARGIN_TOL, "invalid": False}


def stress_checks(allocation: dict[str, float], bad_year_shocks: dict[str, float], crisis: dict[str, float],
                  gov_share: float | None, limit: float, **scenario_args) -> list[dict]:
    """The checks a risk level must pass before the system may say it fits the user's loss limit.

    Three different lenses, kept apart because they answer different questions:
      historis: estimated bad-year loss from the last year of fund prices (data);
      hipotetis: the user's severe-crisis assumption (stocks/bonds fall by chosen percentages);
      hipotetis: the worst of the separate scenarios (stocks, yield, spread, default, liquidity), computed with the LEAST
        government share among the picks, and 0% when a fact sheet is unreadable (unknown is never treated as safe).
    They are alternative views of the same risk and are never added together. A check passes only with at least
    MARGIN_THIN of room; a thinner margin is reported as thin and does not count as meeting the limit.
    """
    worst = min(scenario_losses(allocation, 0.0 if gov_share is None else gov_share, **scenario_args), key=lambda s: s["loss"])
    finite = [v for v in bad_year_shocks.values() if math.isfinite(v)]
    harsh = min(finite) if finite else -1.0                          # a category without a shock takes the worst known one
    rows = [("Tahun buruk dari data 1 tahun", "historis", stress_loss(allocation, bad_year_shocks, harsh)),
            ("Krisis berat (asumsi Anda)", "hipotetis", stress_loss(allocation, crisis, min(crisis.values(), default=-1.0))),
            (f"Skenario terpisah terburuk: {worst['name']}", "hipotetis", worst["loss"])]
    out = []
    for name, kind, loss in rows:
        m = margin_to_limit(loss, limit, 1.0)
        out.append({"name": name, "kind": kind, "loss": loss, "margin_points": m["points"], "thin": m["thin"],
                    "crossed": m["crossed"], "invalid": m["invalid"],
                    "passed": not m["invalid"] and not m["thin"] and not m["crossed"]})   # a calculation that failed never passes
    return out


def months_with_buys(transactions: pd.DataFrame, as_of: date, window: int = 6) -> int:
    """How many of the last `window` calendar months contain at least one BUY."""
    buys = transactions[transactions["type"] == "BUY"]
    if buys.empty:
        return 0
    periods = pd.to_datetime(buys["date"]).dt.to_period("M").unique()
    end = pd.Period(as_of, freq="M")
    recent = {end - i for i in range(window)}
    return len(recent.intersection(set(periods)))
