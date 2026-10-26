import pandas as pd
import pytest

from tracker import portfolio_plan as pp
from tracker import products, recommend, rules

TARGET = {"pasar_uang": 0.12, "pendapatan_tetap": 0.70, "saham": 0.18}
SHOCKS = {"pasar_uang": 0.0, "pendapatan_tetap": -0.05, "saham": -0.30, "sbn": -0.05}
BUDGET = 5_000_000.0


def _holdings(rows):
    return pd.DataFrame(rows, columns=["product", "category", "current_value"])


@pytest.fixture(scope="module")
def rec():
    return recommend.recommend(products.load_products(), rules.load_profiles(), 0.10, 25, BUDGET)


def test_empty_portfolio_keeps_the_target_split():
    out = pp.allocate({}, TARGET, BUDGET)
    assert out == {"pasar_uang": 600_000, "pendapatan_tetap": 3_500_000, "saham": 900_000}


def test_overweight_category_gets_nothing_and_deposit_still_sums_to_budget():
    current = {"saham": 20_000_000.0, "pendapatan_tetap": 5_000_000.0}  # saham is 80% of the portfolio
    out = pp.allocate(current, TARGET, BUDGET)
    assert "saham" not in out and sum(out.values()) == pytest.approx(BUDGET)
    assert out["pendapatan_tetap"] > out["pasar_uang"]


def test_spare_money_follows_the_target_mix_when_all_gaps_are_small():
    current = {"pasar_uang": 1_200_000.0, "pendapatan_tetap": 7_000_000.0, "saham": 1_800_000.0}  # exactly on target
    out = pp.allocate(current, TARGET, BUDGET)
    assert out["pendapatan_tetap"] == pytest.approx(3_500_000, abs=1_000)


def test_stress_on_whole_portfolio():
    assert pp.stress({"saham": 100.0}, SHOCKS) == pytest.approx(-0.30)
    assert pp.stress({"saham": 50.0, "pasar_uang": 50.0}, SHOCKS) == pytest.approx(-0.15)
    assert pp.stress({}, SHOCKS) == 0.0


def test_apply_without_holdings_returns_same_recommendation(rec):
    out = pp.apply(rec, _holdings([]), BUDGET, 0.10)
    assert out.allocation == rec.allocation and out.monthly_amounts == rec.monthly_amounts
    assert out.plan.has_portfolio is False


def test_apply_shifts_deposit_to_underweight_and_runs_stress_on_total(rec):
    held = _holdings([("Reksa A", "saham", 30_000_000), ("Reksa B", "pendapatan_tetap", 10_000_000)])
    out = pp.apply(rec, held, BUDGET, 0.10)
    assert "saham" not in out.monthly_amounts and sum(out.monthly_amounts.values()) == pytest.approx(BUDGET)
    assert out.target_allocation == rec.allocation
    assert out.stress_loss == out.plan.stress_after and out.stress_loss < -0.10 and out.within_limit is False
    assert any("masih di atas batas" in n for n in out.notes)
    assert out.plan.months_to_target and out.plan.months_to_target > 1


def test_held_fund_is_marked_and_concentrated_top_pick_is_replaced(rec):
    top = rec.picks["pendapatan_tetap"].iloc[0]["name"]
    second = rec.picks["pendapatan_tetap"].iloc[1]["name"]
    held = _holdings([(top, "pendapatan_tetap", 9_000_000), ("Lain", "pasar_uang", 1_000_000)])  # top = 90%
    out = pp.apply(rec, held, BUDGET, 0.10)
    assert out.picks["pendapatan_tetap"].iloc[0]["name"] == second
    assert any("terlalu terkonsentrasi" in n for n in out.notes)
    assert out.picks["pendapatan_tetap"]["held_idr"].notna().sum() == 1


def test_months_to_target_zero_when_already_on_target():
    on_target = {"pasar_uang": 1_200_000.0, "pendapatan_tetap": 7_000_000.0, "saham": 1_800_000.0}
    assert pp._months_to_target(on_target, TARGET, BUDGET) == 0


def test_snapshot_block_none_for_empty_portfolio(rec):
    assert pp.snapshot_block(pp.apply(rec, _holdings([]), BUDGET).plan) is None
    held = _holdings([("X", "saham", 1_000_000)])
    assert pp.snapshot_block(pp.apply(rec, held, BUDGET).plan)["total_now"] == 1_000_000
