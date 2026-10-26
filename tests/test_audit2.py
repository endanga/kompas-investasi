"""Second audit: scenario sensitivity, unknown data, heavier stress, and an independent DCA check."""
from decimal import Decimal, getcontext
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tracker import metrics, products, recommend, rules, ui

ROOT = Path(__file__).parent.parent
PROFILE = {"pasar_uang": 0.12, "pendapatan_tetap": 0.70, "saham": 0.18}
BONDS_ONLY = {"pendapatan_tetap": 1.0}
YIELD = "Yield obligasi negara naik 2 poin"


def loss(name, alloc=PROFILE, gov=0.5, **kw):
    return next(s["loss"] for s in metrics.scenario_losses(alloc, gov, **kw) if s["name"] == name)


# ---- 1. scenario assumptions
def test_yield_scenario_is_duration_times_rise():
    assert loss(YIELD, BONDS_ONLY, gov=1.0) == pytest.approx(-4.0 * 0.02)               # all government, duration 4
    assert loss(YIELD, BONDS_ONLY, gov=0.0) == pytest.approx(-3.0 * 0.02)               # all corporate, duration 3


@pytest.mark.parametrize("shorter, longer", [(1.0, 3.0), (3.0, 4.0), (4.0, 7.0)])
def test_longer_duration_means_bigger_loss(shorter, longer):
    assert loss(YIELD, BONDS_ONLY, 1.0, dur_negara=longer) < loss(YIELD, BONDS_ONLY, 1.0, dur_negara=shorter)
    assert loss(YIELD, BONDS_ONLY, 0.0, dur_korporasi=longer) < loss(YIELD, BONDS_ONLY, 0.0, dur_korporasi=shorter)


def test_duration_only_moves_the_yield_scenario():
    base = {s["name"]: s["loss"] for s in metrics.scenario_losses(PROFILE, 0.5)}
    moved = {s["name"]: s["loss"] for s in metrics.scenario_losses(PROFILE, 0.5, dur_negara=7.0, dur_korporasi=6.0)}
    assert [n for n in base if base[n] != moved[n]] == [YIELD]


@pytest.mark.parametrize("scale", [0.5, 1.5, 2.0])
def test_scaling_the_shocks_scales_every_loss_linearly(scale):
    for b, s in zip(metrics.scenario_losses(PROFILE, 0.3), metrics.scenario_losses(PROFILE, 0.3, scale=scale)):
        assert s["loss"] == pytest.approx(b["loss"] * scale)


def test_the_note_states_the_durations_actually_used():
    note = next(s["note"] for s in metrics.scenario_losses(PROFILE, 0.5, dur_negara=6, dur_korporasi=2) if s["name"] == YIELD)
    assert "6 tahun" in note and "2 tahun" in note


# ---- 2. unknown holdings: a range, never one number presented as fact
def test_scenario_range_has_one_loss_per_assumed_corporate_exposure():
    rows = metrics.scenario_range(PROFILE)
    assert len(rows) == len(metrics.SCENARIOS)
    assert set(rows[0]["losses"]) == {0.25, 0.5, 1.0}


def test_corporate_default_scenario_gets_worse_as_corporate_exposure_rises():
    row = next(r for r in metrics.scenario_range(PROFILE) if r["name"].startswith("Gagal bayar"))
    values = [row["losses"][e] for e in (0.25, 0.5, 1.0)]
    assert values == sorted(values, reverse=True) and values[2] == pytest.approx(0.70 * -0.10)


def test_range_matches_the_single_scenario_at_the_same_exposure():
    row = metrics.scenario_range(PROFILE)[0]
    assert row["losses"][0.25] == pytest.approx(metrics.scenario_losses(PROFILE, 0.75)[0]["loss"])


def test_unverified_table_says_so_and_shows_every_exposure_in_percent_and_rupiah():
    out = ui.scenario_table(metrics.scenario_range(PROFILE), 100e6, "nilai portofolio", 0.10, verified=False,
                            exposures=metrics.CORPORATE_EXPOSURES)
    assert "Belum terverifikasi" in out and "bukan data" in out
    assert all(f"Jika {e}% korporasi" in out for e in (25, 50, 100)) and "Rp" in out


def test_verified_table_separates_data_from_assumption():
    out = ui.scenario_table(metrics.scenario_losses(PROFILE, 0.2), 100e6, "nilai portofolio", 0.10)
    assert "data fact sheet" in out and "asumsi" in out and "Belum terverifikasi" not in out


# ---- 3. ranking and unknown data
CATALOG = products.load_products()


def test_missing_values_are_never_ranked_best():
    s = pd.DataFrame({"x": [1.0, 2.0, np.nan, 3.0]})
    assert recommend._percentiles(s, "x").iloc[2] == 0.0                              # required criterion: worst
    g = pd.DataFrame({"gov_top10_pct": [10.0, 50.0, np.nan]})
    pct = recommend._percentiles(g, "gov_top10_pct")
    assert pct.iloc[2] == pct.min()


def test_blanking_a_known_fund_never_raises_its_score():
    before = recommend.rank_category(CATALOG, "pendapatan_tetap").set_index("name")["score"]
    known = CATALOG[(CATALOG["category"] == "pendapatan_tetap") & CATALOG["gov_top10_pct"].notna()]
    for idx in known.index:
        trial = CATALOG.copy()
        trial.loc[idx, "gov_top10_pct"] = np.nan
        after = recommend.rank_category(trial, "pendapatan_tetap").set_index("name")["score"]
        name = CATALOG.loc[idx, "name"]
        if name in before.index:
            assert after[name] <= before[name] + 1e-9, name


def test_with_no_fact_sheet_data_at_all_ranking_works_and_drops_the_credit_criterion():
    ranked = recommend.rank_category(CATALOG.assign(gov_top10_pct=np.nan), "pendapatan_tetap")
    assert len(ranked) > 0 and ranked["score"].between(0, 100).all()
    assert "gov_top10_pct" not in recommend._weights(ranked, "pendapatan_tetap")


def test_app_caption_says_stable_ranking_is_not_proof_of_safety():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception
    assert "bukan bukti bahwa produknya aman" in " ".join(c.value for c in at.caption)


# ---- heavier stress and the chosen level
def _highest_passing_level(scale):
    shocks = metrics.crisis_shocks(40 * scale, 8 * scale)
    passing = [recommend.level_of(k) for k, a in rules.load_profiles().items()
               if recommend.level_of(k) is not None and -metrics.stress_loss(a, shocks) <= 0.10]
    return max(passing) if passing else 0.0


def test_a_heavier_stress_never_allows_a_riskier_level():
    levels = [_highest_passing_level(s) for s in (0.5, 1.0, 1.5, 2.0)]
    assert levels == sorted(levels, reverse=True)


def test_heavier_scenarios_never_reduce_a_reported_loss():
    mild = metrics.scenario_losses(PROFILE, 0.3, scale=1.0)
    harsh = metrics.scenario_losses(PROFILE, 0.3, scale=1.5)
    assert all(h["loss"] <= m["loss"] for m, h in zip(mild, harsh))


# ---- 4. DCA against an independent calculation
getcontext().prec = 60


def decimal_dca(monthly, annual, years, initial=0):
    r = (Decimal(1) + Decimal(str(annual))) ** (Decimal(1) / Decimal(12)) - 1
    value = Decimal(str(initial))
    for _ in range(int(years * 12)):
        value = value * (1 + r) + Decimal(str(monthly))
    return float(value)


@pytest.mark.parametrize("monthly, annual, years, initial", [
    (5_000_000, 0.06, 25, 0), (5_000_000, 0.08, 25, 20_000_000), (1_000_000, 0.0, 10, 0),
    (750_000, 0.035, 7.5, 1_000_000), (2_000_000, 0.12, 30, 0), (0, 0.06, 10, 50_000_000)])
def test_dca_matches_an_independent_decimal_calculation(monthly, annual, years, initial):
    got = metrics.future_value_dca(monthly, annual, years, initial)
    assert got == pytest.approx(decimal_dca(monthly, annual, years, initial), rel=1e-9)


def test_nominal_rate_over_twelve_overstates_the_effective_yearly_return():
    old = 1_000_000 * (1 + 0.06 / 12) ** 12
    assert old > 1_060_000 and metrics.future_value_dca(0, 0.06, 1, 1_000_000) == pytest.approx(1_060_000)


def test_inflation_deflates_with_the_same_effective_yearly_convention():
    assert metrics.deflate(1_000_000, 0.0, 20) == 1_000_000
    assert metrics.deflate(1_060_000, 0.06, 1) == pytest.approx(1_000_000)
    assert metrics.deflate(1_000_000, 0.05, 10) == pytest.approx(1_000_000 / 1.05 ** 10)
