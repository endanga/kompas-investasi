"""Deterministic portfolio metrics. All numbers shown to the user come from here, never from an LLM."""
from __future__ import annotations

from datetime import date

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
    """Projected value of an initial sum plus monthly deposits (end of month), compounded monthly.

    This is a what-if on an *assumed* rate, not a forecast.
    """
    n = int(round(years * 12))
    r = annual_rate / 12
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


def stress_loss(allocation: dict[str, float], shocks: dict[str, float] | None = None) -> float:
    """Portfolio fall (negative fraction) if every category hits its shock at once."""
    shocks = DEFAULT_SHOCKS if shocks is None else shocks
    return float(sum(share * shocks.get(cat, 0.0) for cat, share in allocation.items()))


def months_with_buys(transactions: pd.DataFrame, as_of: date, window: int = 6) -> int:
    """How many of the last `window` calendar months contain at least one BUY."""
    buys = transactions[transactions["type"] == "BUY"]
    if buys.empty:
        return 0
    periods = pd.to_datetime(buys["date"]).dt.to_period("M").unique()
    end = pd.Period(as_of, freq="M")
    recent = {end - i for i in range(window)}
    return len(recent.intersection(set(periods)))
