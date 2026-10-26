"""Fit a recommendation to what the user already holds.

The recommender chooses a target mix (a Bibit risk level) as if starting from zero. With an existing portfolio the
monthly deposit should instead close the gap to that target, without selling anything (no fees, no tax event):
categories that are under target get the money first, categories that are over target get none. The stress test is
then run on the whole portfolio after this month's deposit, and a product that already dominates the portfolio is
not topped up further.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import pandas as pd

from .recommend import Recommendation

MAX_PRODUCT_SHARE = 0.50   # same threshold as rules.CONCENTRATION_THRESHOLD
CLOSE_ENOUGH = 0.05        # a category within 5 points of target counts as "on target"
MAX_MONTHS = 240
ROUND_TO = 1_000
UNKNOWN_SHOCK = -0.15      # bad-year shock for a category the shock table does not know


@dataclass
class Plan:
    has_portfolio: bool
    total_now: float
    current: dict[str, float]        # rupiah per category today
    target: dict[str, float]         # share per category of the chosen risk level
    contribution: dict[str, float]   # this month's deposit per category (sums to the budget)
    after: dict[str, float]          # rupiah per category after the deposit
    stress_now: float | None         # bad-year loss of the portfolio today (None if empty)
    stress_after: float              # bad-year loss of the portfolio after the deposit
    months_to_target: int | None     # months of the same deposit until every category is near target
    held: dict[str, float] = field(default_factory=dict)  # product name (lower case) -> rupiah

    @property
    def total_after(self) -> float:
        return sum(self.after.values())

    def share_now(self, cat: str) -> float:
        return self.current.get(cat, 0.0) / self.total_now if self.total_now else 0.0

    def share_after(self, cat: str) -> float:
        return self.after.get(cat, 0.0) / self.total_after if self.total_after else 0.0


def _round_to_budget(amounts: dict[str, float], budget: float) -> dict[str, float]:
    """Round to whole thousands and put the rounding remainder on the largest category so the sum stays exact."""
    rounded = {c: round(a / ROUND_TO) * ROUND_TO for c, a in amounts.items()}
    if rounded:
        biggest = max(rounded, key=rounded.get)
        rounded[biggest] += budget - sum(rounded.values())
    return rounded


def allocate(current: dict[str, float], target: dict[str, float], budget: float) -> dict[str, float]:
    """Split one deposit so under-target categories are filled first. Never sells, never tops up an over-target one."""
    wanted = {c: s for c, s in target.items() if s > 0}
    total_after = sum(current.values()) + budget
    need = {c: max(0.0, s * total_after - current.get(c, 0.0)) for c, s in wanted.items()}
    need_sum = sum(need.values())
    if need_sum <= 0:
        raw = {c: budget * s for c, s in wanted.items()}
    elif need_sum >= budget:
        raw = {c: budget * n / need_sum for c, n in need.items()}
    else:  # every gap closes with money to spare; the spare follows the target mix
        spare = budget - need_sum
        raw = {c: need[c] + spare * wanted[c] for c in wanted}
    return _round_to_budget({c: a for c, a in raw.items() if a > 0}, budget)


def stress(values: dict[str, float], shocks: dict[str, float]) -> float:
    """Bad-year loss (negative fraction) of a portfolio given as rupiah per category."""
    total = sum(values.values())
    if total <= 0:
        return 0.0
    return sum(v * shocks.get(c, UNKNOWN_SHOCK) for c, v in values.items()) / total


def _months_to_target(current: dict[str, float], target: dict[str, float], budget: float) -> int | None:
    values = dict(current)
    for month in range(MAX_MONTHS + 1):
        total = sum(values.values())
        if all(abs(values.get(c, 0.0) / total - target.get(c, 0.0)) <= CLOSE_ENOUGH
               for c in set(values) | set(target)):
            return month
        for c, a in allocate(values, target, budget).items():
            values[c] = values.get(c, 0.0) + a
    return None


def holdings_by_product(holdings: pd.DataFrame) -> dict[str, float]:
    if holdings.empty:
        return {}
    named = holdings.assign(_k=holdings["product"].astype(str).str.strip().str.lower())
    return {k: float(v) for k, v in named.groupby("_k")["current_value"].sum().items()}


def build_plan(target: dict[str, float], shocks: dict[str, float], holdings: pd.DataFrame, budget: float) -> Plan:
    total = float(holdings["current_value"].sum()) if not holdings.empty else 0.0
    current = {c: float(v) for c, v in holdings.groupby("category")["current_value"].sum().items() if v > 0} \
        if total > 0 else {}
    contribution = allocate(current, target, budget)
    after = dict(current)
    for c, a in contribution.items():
        after[c] = after.get(c, 0.0) + a
    has = total > 0
    return Plan(
        has_portfolio=has, total_now=total, current=current, target=dict(target), contribution=contribution, after=after,
        stress_now=stress(current, shocks) if has else None, stress_after=stress(after, shocks),
        months_to_target=_months_to_target(current, target, budget) if has else 0,
        held=holdings_by_product(holdings) if has else {},
    )


def _adjust_picks(cat: str, picks: pd.DataFrame, plan: Plan) -> tuple[pd.DataFrame, str | None]:
    """Mark funds the user already holds; if the top fund already dominates the portfolio, promote the next one."""
    df = picks.copy()
    keys = df["name"].astype(str).str.strip().str.lower()
    df["held_idr"] = [plan.held.get(k) for k in keys]
    note = None
    shares = [0.0 if pd.isna(h) else h / plan.total_now for h in df["held_idr"]]
    if shares and shares[0] > MAX_PRODUCT_SHARE:
        for i, s in enumerate(shares):
            if s <= MAX_PRODUCT_SHARE:
                order = [i] + [j for j in range(len(df)) if j != i]
                note = (f"{df.iloc[0]['name']} sudah {shares[0]:.0%} dari portofolio Anda; setoran baru diarahkan ke "
                        f"{df.iloc[i]['name']} supaya tidak terlalu terkonsentrasi.")
                df = df.iloc[order]
                break
    df = df.copy()
    df["alasan"] = [
        f"{a}, sudah Anda miliki ({h / plan.total_now:.0%} portofolio)" if pd.notna(h) and h else a
        for a, h in zip(df["alasan"], df["held_idr"])
    ]
    return df, note


def apply(rec: Recommendation, holdings: pd.DataFrame, budget: float, max_drop: float | None = None) -> Recommendation:
    """Recommendation for the deposit that moves the user's real portfolio toward the target mix."""
    target = dict(rec.allocation)
    plan = build_plan(target, rec.shocks, holdings, budget)
    if not plan.has_portfolio:
        return replace(rec, target_allocation=target, plan=plan)

    picks, notes = {}, list(rec.notes)
    for cat, df in rec.picks.items():
        if plan.contribution.get(cat, 0) <= 0:
            continue
        picks[cat], note = _adjust_picks(cat, df, plan)
        if note:
            notes.append(note)
    held_off_target = [c for c in plan.current if target.get(c, 0) <= 0]
    if held_off_target:
        notes.append("Portofolio Anda punya jenis di luar komposisi profil ini (" + ", ".join(held_off_target)
                     + "). Tidak disarankan dijual; tidak ditambah lagi.")
    within = rec.within_limit if max_drop is None else -plan.stress_after <= max_drop
    if max_drop is not None and not within and rec.within_limit:
        notes.append(
            f"Dengan isi portofolio sekarang, perkiraan turun total {-plan.stress_after:.1%}".replace(".", ",") + f" masih di atas batas "
            f"{max_drop:.0%}. Setoran diarahkan ke jenis yang kurang"
            + (f"; sekitar {plan.months_to_target} bulan setoran sampai komposisi mendekati target." if plan.months_to_target else ".")
        )
    amounts = dict(plan.contribution)
    shares = {c: a / budget for c, a in amounts.items()}
    return replace(rec, allocation=shares, picks=picks, monthly_amounts=amounts, stress_loss=plan.stress_after,
                   within_limit=within, notes=notes, target_allocation=target, plan=plan)


def snapshot_block(plan: Plan) -> dict | None:
    """JSON-safe summary of the plan for saved recommendations and the PDF report."""
    if not plan.has_portfolio:
        return None
    return {
        "total_now": plan.total_now, "current": plan.current, "target": plan.target, "contribution": plan.contribution,
        "after": plan.after, "stress_now": plan.stress_now, "stress_after": plan.stress_after,
        "months_to_target": plan.months_to_target,
    }

