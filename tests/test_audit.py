"""Audit tests: scenarios, score transparency, weight sensitivity, input validation."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tracker import metrics, products, recommend, rules, ui

PROFILE = {"pasar_uang": 0.12, "pendapatan_tetap": 0.70, "saham": 0.18}


# ---- scenarios
def test_each_scenario_is_computed_by_hand():
    out = {s["name"]: s["loss"] for s in metrics.scenario_losses(PROFILE, gov_share=0.5)}
    assert out["Saham jatuh"] == pytest.approx(0.18 * -0.40 + 0.35 * 0 + 0.35 * -0.03)
    assert out["Yield obligasi negara naik 2 poin"] == pytest.approx(0.18 * -0.05 + 0.35 * -0.08 + 0.35 * -0.06)
    assert out["Spread kredit melebar"] == pytest.approx(0.18 * -0.10 + 0.35 * -0.07)
    assert out["Gagal bayar penerbit korporasi besar"] == pytest.approx(0.35 * -0.10)


def test_corporate_default_hurts_corporate_funds_not_government_funds():
    gov = {s["name"]: s["loss"] for s in metrics.scenario_losses(PROFILE, gov_share=1.0)}
    corp = {s["name"]: s["loss"] for s in metrics.scenario_losses(PROFILE, gov_share=0.0)}
    assert gov["Gagal bayar penerbit korporasi besar"] == 0
    assert corp["Gagal bayar penerbit korporasi besar"] == pytest.approx(0.70 * -0.10)
    assert gov["Yield obligasi negara naik 2 poin"] < corp["Yield obligasi negara naik 2 poin"]      # longer duration, bigger price fall


def test_unknown_government_share_is_not_treated_as_safe():
    unknown = metrics.scenario_losses(PROFILE, None)
    half = metrics.scenario_losses(PROFILE, 0.5)
    assert [s["loss"] for s in unknown] == [s["loss"] for s in half]
    assert not unknown[0]["gov_share_known"] and metrics.scenario_losses(PROFILE, 0.2)[0]["gov_share_known"]


def test_scenario_table_shows_percent_and_rupiah_with_icons():
    rows = metrics.scenario_losses(PROFILE, 0.2)
    out = ui.scenario_table(rows, 100_000_000, "nilai portofolio", 0.10)
    assert "Gagal bayar penerbit korporasi besar" in out and "Rp" in out and "%" in out and ("✓" in out or "✕" in out)


def test_scenarios_have_no_gain_and_cover_mixed_and_sbn():
    mix = {"campuran": 0.5, "sbn": 0.5}
    assert all(s["loss"] <= 0 for s in metrics.scenario_losses(mix, 0.5))
    assert metrics.scenario_losses({"sbn": 1.0}, None)[3]["loss"] == 0          # SBN has no corporate default exposure


# ---- profiles and allocations
def test_every_profile_sums_to_100_percent():
    for key, alloc in rules.load_profiles().items():
        assert sum(alloc.values()) == pytest.approx(1.0, abs=1e-6), key
        assert all(v >= 0 for v in alloc.values()), key


def test_recommended_allocation_sums_to_100_percent():
    rec = recommend.recommend(products.load_products(), rules.load_profiles(), 0.10, 25, 5_000_000)
    assert sum(rec.allocation.values()) == pytest.approx(1.0)
    assert sum(rec.monthly_amounts.values()) == pytest.approx(5_000_000)


# ---- score breakdown and sensitivity
@pytest.fixture(scope="module")
def catalog():
    return products.load_products()


def test_breakdown_weights_sum_to_one_and_name_a_source(catalog):
    ranked = recommend.rank_category(catalog, "pendapatan_tetap")
    br = recommend.score_breakdown(ranked, "pendapatan_tetap", ranked.iloc[0]["name"])
    assert br["bobot"].sum() == pytest.approx(1.0, abs=0.01)
    assert (br["sumber"].str.len() > 0).all() and br["persentil"].between(0, 1).all()


def test_breakdown_scores_unread_fact_sheet_like_the_worst_readable_fund(catalog):
    ranked = recommend.rank_category(catalog, "pendapatan_tetap")
    unread = ranked[ranked["gov_top10_pct"].isna()].iloc[0]["name"]
    br = recommend.score_breakdown(ranked, "pendapatan_tetap", unread)
    row = br[br["kriteria"].str.contains("negara")].iloc[0]
    worst_known = recommend._percentiles(ranked, "gov_top10_pct")[ranked["gov_top10_pct"].notna()].min()
    assert row["persentil"] == pytest.approx(worst_known, abs=0.01) and "terburuk" in row["sumber"]


@pytest.mark.parametrize("category", ["pasar_uang", "pendapatan_tetap", "saham", "campuran"])
def test_top3_is_stable_when_every_weight_moves_20_percent(catalog, category, monkeypatch):
    """Sensitivity: nudging each weight +/-20% (renormalised) must not replace the whole top 3."""
    base = list(recommend.rank_category(catalog, category).head(3)["name"])
    original = recommend.WEIGHTS[category]
    worst_overlap = 3
    for crit in original:
        for factor in (0.8, 1.2):
            changed = {**original, crit: original[crit] * factor}
            monkeypatch.setitem(recommend.WEIGHTS, category, changed)
            top = list(recommend.rank_category(catalog, category).head(3)["name"])
            worst_overlap = min(worst_overlap, len(set(base) & set(top)))
    assert worst_overlap >= 2, f"{category}: a 20% weight change replaced most of the top 3"


# ---- missing data must never help a product
def _bond(name, **kw):
    row = {"product_id": name, "name": name, "category": "pendapatan_tetap", "syariah_dari_nama": "tidak",
           "return_1y_pct": 4.0, "return_3y_pct": 18.0, "drawdown_1y_pct": -1.0, "aum_idr": 5e11, "gov_top10_pct": 50.0}
    return {**row, **kw}


def test_missing_return_history_is_dropped_not_rewarded(catalog):
    df = pd.DataFrame([_bond("A"), _bond("B", return_3y_pct=np.nan)])
    assert list(recommend.rank_category(df, "pendapatan_tetap")["name"]) == ["A"]        # no 3-year record: not eligible


def test_extreme_values_do_not_crash_the_ranking():
    df = pd.DataFrame([_bond("A", return_3y_pct=-99.9), _bond("B", return_3y_pct=5000.0), _bond("C", aum_idr=1e18)])
    out = recommend.rank_category(df, "pendapatan_tetap")
    assert len(out) == 3 and out["score"].between(0, 100).all()


def test_total_loss_return_has_no_annual_rate():
    assert metrics.annualize_total_return(-100.0, 3) is None
    assert recommend._ann(-100.0, 3) != recommend._ann(-100.0, 3)       # NaN, not a number


# ---- metrics on edge inputs
def test_max_drawdown_edges():
    assert metrics.max_drawdown(pd.Series(dtype=float)) == 0.0
    assert metrics.max_drawdown(pd.Series([1, 2, 3])) == 0.0
    assert metrics.max_drawdown(pd.Series([100, 50, 80])) == pytest.approx(-0.5)


def test_xirr_known_and_degenerate_cases():
    assert metrics.xirr([(date(2025, 1, 1), -100.0), (date(2026, 1, 1), 110.0)]) == pytest.approx(0.10, abs=1e-4)
    assert metrics.xirr([(date(2025, 1, 1), -100.0)]) is None
    assert metrics.xirr([(date(2025, 1, 1), -100.0), (date(2025, 1, 1), 110.0)]) is None


def test_stress_loss_of_empty_allocation_and_unknown_category():
    assert metrics.stress_loss({}) == 0.0
    assert metrics.stress_loss({"entah": 1.0}) == 0.0
