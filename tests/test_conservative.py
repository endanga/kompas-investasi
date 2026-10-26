"""Conservative rule: a level fits the limit only if every check passes with room; missing data is never safe."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tracker import metrics, products, recommend, rules, ui

ROOT = Path(__file__).parent.parent
PROFILES = rules.load_profiles()
CATALOG = products.load_products()
BUDGET = 5_000_000
LIMIT = 0.10


def rec_for(df=CATALOG, **kw):
    return recommend.recommend(df, PROFILES, kw.pop("limit", LIMIT), 25, BUDGET, **kw)


def key_of(level):
    return next(k for k in PROFILES if recommend.level_of(k) == level)


# ---- the rule itself
def test_strict_level_has_every_check_passing_with_room_and_every_higher_level_fails_one():
    r = rec_for()
    assert r.strict and r.within_limit and all(c["passed"] for c in r.checks)
    assert all(c["margin_points"] >= metrics.MARGIN_THIN * 100 for c in r.checks)
    rankings, shocks = recommend._rank_and_shock(CATALOG, False)
    gov = recommend.conservative_gov_share(rankings)
    for lv, k in sorted(((recommend.level_of(k), k) for k in PROFILES if recommend.level_of(k)), reverse=True):
        if lv <= recommend.horizon_level_cap(25) and lv > r.level:
            assert not all(c["passed"] for c in metrics.stress_checks(PROFILES[k], shocks, metrics.crisis_shocks(), gov, LIMIT)), lv


def test_strict_is_never_riskier_than_the_legacy_rule():
    assert rec_for().level <= rec_for(strict=False).level


def test_legacy_rule_still_picks_by_the_bad_year_estimate_only():
    legacy = rec_for(strict=False)
    assert legacy.level == 4.5 and not legacy.checks and not legacy.strict


def test_a_thin_margin_does_not_count_as_meeting_the_limit():
    # level 3.5 loses 9.36% in the default crisis: under 10%, but only 0.64 points of room
    checks = metrics.stress_checks(PROFILES[key_of(3.5)], {"saham": -0.30, "pendapatan_tetap": -0.03, "sbn": -0.03, "campuran": -0.1,
                                                          "pasar_uang": 0.0}, metrics.crisis_shocks(40, 8), 1.0, LIMIT)
    crisis = next(c for c in checks if c["name"].startswith("Krisis"))
    assert crisis["thin"] and not crisis["crossed"] and not crisis["passed"] and crisis["loss"] > -LIMIT


def test_one_passing_scenario_is_not_enough():
    shocks = recommend._rank_and_shock(CATALOG, False)[1]
    checks = metrics.stress_checks(PROFILES[key_of(4.5)], shocks, metrics.crisis_shocks(), 1.0, LIMIT)
    assert any(c["passed"] for c in checks) and not all(c["passed"] for c in checks)       # something passes, level still fails


def test_a_heavier_crisis_assumption_lowers_the_chosen_level():
    levels = [rec_for(crisis=metrics.crisis_shocks(s, o)).level for s, o in ((20, 3), (30, 5), (40, 8), (50, 12), (60, 15))]
    assert levels == sorted(levels, reverse=True) and levels[0] > levels[-1]


def test_when_no_level_fits_the_most_conservative_one_is_shown_with_a_warning():
    r = rec_for(limit=0.01)
    assert not r.within_limit and any("Tidak ada level" in n for n in r.notes)
    assert r.level == min(recommend.level_of(k) for k in PROFILES if recommend.level_of(k))


def test_the_skipped_level_is_explained_in_the_notes():
    notes = " ".join(rec_for().notes)
    assert "tidak dipilih otomatis" in notes and "bukan batas kerugian aktual" in notes


# ---- missing data is never safe
def _bond(name, **kw):
    row = {"product_id": name, "name": name, "category": "pendapatan_tetap", "syariah_dari_nama": "tidak", "return_1y_pct": 4.0,
           "return_3y_pct": 18.0, "drawdown_1y_pct": -2.0, "aum_idr": 5e11, "gov_top10_pct": 100.0, "as_of": "2026-10-26"}
    return {**row, **kw}


def test_unreadable_fact_sheet_is_scored_as_no_government_bonds_in_the_checks():
    ranked = {"pendapatan_tetap": pd.DataFrame([_bond("A", gov_top10_pct=np.nan), _bond("B"), _bond("C")])}
    assert recommend.conservative_gov_share(ranked) == 0.0
    assert recommend.conservative_gov_share({"pendapatan_tetap": pd.DataFrame([_bond("A"), _bond("B"), _bond("C")])}) == 1.0


def test_least_government_pick_among_the_top_three_decides_not_the_best_one():
    df = pd.DataFrame([_bond("A", gov_top10_pct=100.0), _bond("B", gov_top10_pct=60.0), _bond("C", gov_top10_pct=20.0)])
    assert recommend.conservative_gov_share({"pendapatan_tetap": df}) == pytest.approx(0.2)


def test_unverified_composition_is_named_in_the_notes():
    blank = CATALOG.assign(gov_top10_pct=np.nan)
    notes = " ".join(rec_for(blank).notes)
    assert "Komposisi belum terverifikasi" in notes and "tidak diketahui" in notes


def test_missing_fact_sheet_never_gives_a_higher_level_than_a_fully_read_one():
    assert rec_for(CATALOG.assign(gov_top10_pct=np.nan)).level <= rec_for().level


def test_without_the_fact_sheet_column_at_all_the_rule_still_works():
    old = CATALOG.drop(columns=[c for c in CATALOG.columns if c in ("gov_top10_pct", "top10_n", "top1_pct", "top10_sum_pct")])
    r = rec_for(old)
    assert r.level <= rec_for(strict=False).level and r.checks


def test_stale_data_is_called_out_and_fresh_data_is_not():
    assert any("berumur" in n for n in rec_for(today=date(2026, 12, 31)).notes)
    assert not any("berumur" in n for n in rec_for(today=date(2026, 10, 27)).notes)


def test_a_fund_with_no_aum_or_no_return_is_dropped_not_assumed_fine():
    base = [_bond(f"F{i}") for i in range(3)]
    bad = [_bond("NoAum", aum_idr=np.nan), _bond("NoDD", drawdown_1y_pct=np.nan), _bond("No3y", return_3y_pct=np.nan),
           _bond("NoRet", return_1y_pct=np.nan), _bond("Tiny", aum_idr=1e9)]
    out = recommend.rank_category(pd.DataFrame(base + bad), "pendapatan_tetap")
    assert set(out["name"]) == {"F0", "F1", "F2"}


def test_no_eligible_product_in_a_category_is_reported_not_hidden():
    df = CATALOG[CATALOG["category"] != "saham"]
    assert any("Tidak ada produk" in n for n in rec_for(df, strict=False).notes)


# ---- changing the level really changes the outcome
def _manual(level):
    return recommend.for_level(CATALOG, PROFILES, key_of(level), BUDGET, False, LIMIT)


def test_changing_the_level_changes_allocation_amounts_stress_checks_and_projection():
    lo, hi = _manual(3.5), _manual(4.5)
    assert lo.allocation != hi.allocation and lo.monthly_amounts != hi.monthly_amounts
    assert lo.stress_loss > hi.stress_loss                                  # higher level, deeper estimated loss
    assert [c["loss"] for c in lo.checks] != [c["loss"] for c in hi.checks]
    rates = recommend.DEFAULT_SCENARIOS["Dasar"]
    fv = lambda r: metrics.future_value_dca(BUDGET, metrics.blended_rate(r.allocation, rates), 25)  # noqa: E731
    assert fv(hi) > fv(lo)


def test_the_funds_picked_inside_a_category_do_not_depend_on_the_level():
    """Honest limit: the level sets HOW MUCH goes to each category; which funds are picked is decided per category."""
    lo, hi = _manual(3.5), _manual(4.5)
    for cat in set(lo.picks) & set(hi.picks):
        assert list(lo.picks[cat]["name"]) == list(hi.picks[cat]["name"])


def test_manual_level_gets_the_same_checks_as_the_automatic_one():
    auto = rec_for()
    manual = recommend.for_level(CATALOG, PROFILES, auto.profile_key, BUDGET, False, LIMIT)
    assert [c["loss"] for c in manual.checks] == pytest.approx([c["loss"] for c in auto.checks])


def test_compare_levels_uses_identical_assumptions_and_orders_losses():
    rates = recommend.DEFAULT_SCENARIOS
    rows = recommend.compare_levels(CATALOG, PROFILES, [4.5, 3.5, 4.0], LIMIT, metrics.crisis_shocks(), rates, BUDGET, 25)
    assert [r["level"] for r in rows] == [3.5, 4.0, 4.5]
    crisis = [r["checks"][1]["loss"] for r in rows]
    assert crisis == sorted(crisis, reverse=True) and rows[2]["checks"][1]["loss"] == pytest.approx(-0.128)
    assert not rows[2]["meets_all"] and set(rows[0]["projection"]) == {"Pesimis", "Dasar", "Optimis"}
    assert any("belum dicocokkan" in w for w in rows[0]["weaknesses"]) and not any("belum dicocokkan" in w for w in rows[2]["weaknesses"])


def test_level_comparison_table_marks_each_cell_with_icon_and_words():
    rows = recommend.compare_levels(CATALOG, PROFILES, [3.5, 4.5], LIMIT, metrics.crisis_shocks(), recommend.DEFAULT_SCENARIOS, BUDGET, 25)
    out = ui.level_compare(rows, 60_000_000, "setoran 12 bulan", LIMIT, chosen=3.5)
    assert "(dipilih)" in out and "✓" in out and "✕" in out and "Proyeksi bukan prediksi" in out


# ---- the app
def test_app_defaults_to_the_conservative_level_and_explains_why():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception
    assert any("tidak dipilih otomatis" in w.value for w in at.warning)
    assert any("Empat angka yang sering tertukar" in e.label for e in at.expander)
    assert any("Bandingkan level" in e.label for e in at.expander)


def test_turning_the_conservative_rule_off_restores_the_older_choice():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    strict_level = [s.value for s in at.sidebar.slider if s.label.startswith("Profil risiko")]
    at.toggle(key="strict_rule").set_value(False)
    at = at.run()
    legacy_level = [s.value for s in at.sidebar.slider if s.label.startswith("Profil risiko")]
    assert not at.exception and legacy_level[0] > strict_level[0]
