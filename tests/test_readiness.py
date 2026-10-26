"""Readiness review: the strict rule on every production path, and no silent 'safe' for missing or broken numbers."""
import inspect
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tracker import metrics, portfolio_plan, products, recommend, robo, rules

ROOT = Path(__file__).parent.parent
PROFILES = rules.load_profiles()
CATALOG = products.load_products()
BUDGET = 5_000_000
LIMIT = 0.10


def holdings(rows):
    return pd.DataFrame(rows, columns=["product", "category", "current_value"])


# ---- 1. production path
def test_the_default_of_recommend_is_the_strict_rule():
    assert inspect.signature(recommend.recommend).parameters["strict"].default is True


def test_the_app_starts_with_the_conservative_toggle_on_and_uses_the_strict_level():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception and at.toggle(key="strict_rule").value is True
    shown = [s.value for s in at.sidebar.slider if s.label.startswith("Profil risiko")][0]
    expected = recommend.recommend(CATALOG, PROFILES, LIMIT, 25, BUDGET)
    assert expected.strict and shown == expected.level


def test_the_strict_level_is_the_same_whichever_way_it_is_requested():
    auto = recommend.recommend(CATALOG, PROFILES, LIMIT, 25, BUDGET)
    manual = recommend.for_level(CATALOG, PROFILES, auto.profile_key, BUDGET, False, LIMIT)
    assert manual.strict and manual.within_limit == auto.within_limit
    assert [c["passed"] for c in manual.checks] == [c["passed"] for c in auto.checks]


def test_one_source_of_truth_for_which_levels_are_verified():
    assert robo.CONFIRMED_LEVELS is recommend.VERIFIED_LEVELS


def test_legacy_flag_is_explicit_and_leaves_no_checks_behind():
    legacy = recommend.recommend(CATALOG, PROFILES, LIMIT, 25, BUDGET, strict=False)
    assert not legacy.strict and legacy.checks == []


# ---- the portfolio path used to fall back to the old single-scenario rule
def test_a_portfolio_is_judged_by_all_three_checks_not_the_bad_year_alone():
    """A portfolio shaped like level 4.0: the bad-year estimate fits 10%, but its crisis loss (-10.7%) does not."""
    rec = recommend.recommend(CATALOG, PROFILES, LIMIT, 25, BUDGET)
    held = holdings([("a", "pasar_uang", 18e6 * 100), ("b", "pendapatan_tetap", 69e6 * 100), ("c", "saham", 13e6 * 100)])
    out = portfolio_plan.apply(rec, held, BUDGET, LIMIT)
    assert -out.stress_loss <= LIMIT                                  # the old rule would have said "within the limit"
    assert not out.within_limit                                       # the strict rule says no
    assert out.strict and len(out.checks) == 3 and any(c["crossed"] or c["thin"] for c in out.checks)


def test_portfolio_checks_describe_the_portfolio_not_the_recommended_mix():
    rec = recommend.recommend(CATALOG, PROFILES, LIMIT, 25, BUDGET)
    held = holdings([("a", "pasar_uang", 90e6), ("b", "saham", 10e6)])
    out = portfolio_plan.apply(rec, held, BUDGET, LIMIT)
    assert [c["loss"] for c in out.checks] != [c["loss"] for c in rec.checks]


def test_a_conservative_portfolio_passes_and_an_aggressive_one_does_not():
    rec = recommend.recommend(CATALOG, PROFILES, LIMIT, 25, BUDGET)
    safe = portfolio_plan.apply(rec, holdings([("a", "pasar_uang", 70e6), ("b", "pendapatan_tetap", 20e6), ("c", "saham", 10e6)]),
                                BUDGET, LIMIT)
    risky = portfolio_plan.apply(rec, holdings([("a", "pasar_uang", 10e6), ("b", "saham", 90e6)]), BUDGET, LIMIT)
    assert safe.within_limit and not risky.within_limit


def test_with_the_rule_switched_off_the_portfolio_path_uses_the_older_comparison():
    rec = recommend.recommend(CATALOG, PROFILES, LIMIT, 25, BUDGET, strict=False)
    held = holdings([("a", "pasar_uang", 18e6 * 100), ("b", "pendapatan_tetap", 69e6 * 100), ("c", "saham", 13e6 * 100)])
    out = portfolio_plan.apply(rec, held, BUDGET, LIMIT)
    assert out.within_limit and not out.strict                        # opt-out is explicit and visible, never a fallback


# ---- 3. no silent 'safe'
def test_a_failed_calculation_never_passes():
    nan = float("nan")
    checks = metrics.stress_checks({"saham": 1.0}, {"saham": nan}, metrics.crisis_shocks(), 1.0, LIMIT)
    assert checks[0]["invalid"] and not checks[0]["passed"] and not checks[0]["thin"] and not checks[0]["crossed"]
    assert math.isnan(metrics.margin_to_limit(nan, LIMIT, 1e6)["rupiah"])
    assert metrics.margin_to_limit(-0.05, nan, 1e6)["invalid"]


def test_the_recommender_does_not_choose_a_level_when_a_shock_cannot_be_computed(monkeypatch):
    real = recommend._rank_and_shock

    def broken(products_df, syariah_only):
        rankings, shocks = real(products_df, syariah_only)
        return rankings, {**shocks, "saham": float("nan")}

    monkeypatch.setattr(recommend, "_rank_and_shock", broken)
    out = recommend.recommend(CATALOG, PROFILES, LIMIT, 25, BUDGET)
    assert not out.within_limit and any("Tidak ada level" in n for n in out.notes)


def test_exactly_one_point_of_room_is_enough_and_a_hair_less_is_not():
    assert not metrics.margin_to_limit(-0.11, 0.12, 1)["thin"]                  # 0.12 - 0.11 = 0.0099999... in floats
    assert not metrics.margin_to_limit(-0.09, 0.10, 1)["thin"]
    assert metrics.margin_to_limit(-0.1101, 0.12, 1)["thin"]
    assert metrics.margin_to_limit(-0.10, 0.10, 1)["thin"] and not metrics.margin_to_limit(-0.10, 0.10, 1)["crossed"]
    assert metrics.margin_to_limit(-0.1001, 0.10, 1)["crossed"]


def test_a_category_the_table_does_not_know_is_never_counted_as_risk_free():
    mix = {"saham": 0.5, "global": 0.5}
    assert metrics.stress_loss(mix, {"saham": -0.30}) == pytest.approx(-0.15)             # historical behaviour, unchanged
    strict = metrics.stress_checks(mix, {"saham": -0.30, "pasar_uang": 0.0}, metrics.crisis_shocks(), 1.0, LIMIT)
    assert strict[0]["loss"] == pytest.approx(-0.30)                                      # the unknown half takes the worst known shock
    losses = {s["name"]: s["loss"] for s in metrics.scenario_losses(mix, 1.0)}
    assert losses["Saham jatuh"] == pytest.approx(-0.40)                                  # unknown kinds are treated like stocks


def test_an_empty_crisis_assumption_is_not_silently_replaced():
    out = recommend.recommend(CATALOG, PROFILES, LIMIT, 25, BUDGET, crisis={"saham": -0.9, "pendapatan_tetap": -0.3, "sbn": -0.3,
                                                                              "pasar_uang": 0.0, "campuran": -0.7})
    assert out.crisis["saham"] == -0.9 and out.level < recommend.recommend(CATALOG, PROFILES, LIMIT, 25, BUDGET).level


# ---- 2 & 3. level 3.0 and data quality are stated, not implied
def test_the_chosen_level_says_when_its_mix_is_not_verified_and_that_rating_and_duration_are_unknown():
    rec = recommend.recommend(CATALOG, PROFILES, LIMIT, 25, BUDGET)
    assert rec.level not in recommend.VERIFIED_LEVELS
    text = " ".join(rec.notes)
    assert "belum dicocokkan dengan aplikasi Bibit" in text and "Rating kredit dan durasi" in text and "tidak pernah diverifikasi" in text


def test_a_verified_level_does_not_get_the_unverified_mix_note():
    notes = " ".join(recommend.level_notes(4.5, PROFILES["bibit_4.5_moderat"]))
    assert "belum dicocokkan" not in notes and "Rating kredit dan durasi" in notes


def test_every_profile_sums_to_one_so_amounts_add_up_to_the_budget():
    for key, mix in PROFILES.items():
        assert sum(mix.values()) == pytest.approx(1.0), key
    rec = recommend.for_level(CATALOG, PROFILES, "bibit_3_konservatif", BUDGET)
    assert rec.monthly_amounts == {"pasar_uang": pytest.approx(1_800_000), "pendapatan_tetap": pytest.approx(2_700_000),
                                   "saham": pytest.approx(500_000)}
    assert sum(rec.monthly_amounts.values()) == pytest.approx(BUDGET)


def _bond(name, **kw):
    row = {"product_id": name, "name": name, "category": "pendapatan_tetap", "syariah_dari_nama": "tidak", "return_1y_pct": 4.0,
           "return_3y_pct": 18.0, "drawdown_1y_pct": -2.0, "aum_idr": 5e11, "gov_top10_pct": 100.0, "as_of": "2026-10-26",
           "factsheet_date": "2026-09-30"}
    return {**row, **kw}


def test_an_old_fact_sheet_is_called_out():
    old = pd.DataFrame([_bond("A", factsheet_date="2026-06-30"), _bond("B"), _bond("C")])
    rankings = {"pendapatan_tetap": recommend.rank_category(old, "pendapatan_tetap")}
    assert any("fact sheet berumur" in n.lower() and "A" in n for n in recommend.quality_notes(old, rankings))
    fresh = pd.DataFrame([_bond("A"), _bond("B"), _bond("C")])
    rankings = {"pendapatan_tetap": recommend.rank_category(fresh, "pendapatan_tetap")}
    assert not any("fact sheet berumur" in n.lower() for n in recommend.quality_notes(fresh, rankings))


def test_missing_fact_sheet_date_does_not_count_as_fresh():
    df = pd.DataFrame([_bond("A", gov_top10_pct=np.nan, factsheet_date=None), _bond("B"), _bond("C")])
    rankings = {"pendapatan_tetap": recommend.rank_category(df, "pendapatan_tetap")}
    assert any("belum terverifikasi" in n for n in recommend.quality_notes(df, rankings))


# ---- 4. wording: a simulation is never presented as a guarantee
def test_no_text_in_the_app_promises_safety_or_a_loss_cap():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception
    texts = [e.value for group in (at.markdown, at.caption, at.warning, at.info, at.success) for e in group]
    # glossary cards define terms (e.g. SBN is guaranteed by the state); they are not claims about the recommendation
    texts = [t.lower() for t in texts if isinstance(t, str) and 'it-term' not in t]
    never = ("pasti aman", "tidak akan rugi", "bebas risiko", "aman dari kerugian", "dijamin aman")
    assert not [t for t in texts if any(f in t for f in never)]
    # words that are fine only when negated right before them ("bukan jaminan", "bukan batas kerugian yang dijamin")
    negated = re.compile(r"(bukan|tidak|tanpa|belum)[^.]{0,40}$")
    for t in texts:
        for m in re.finditer(r"jaminan|dijamin|kerugian maksimum", t):
            assert negated.search(t[:m.start()]), f"claim without negation: ...{t[max(0, m.start() - 50):m.end() + 20]}"
    assert any("bukan jaminan" in t or "bukan batas kerugian yang dijamin" in t for t in texts)


def test_the_default_view_keeps_the_explanations_reachable_without_stacking_warnings():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    notes = next(e for e in at.expander if e.label.startswith("Catatan tentang data dan asumsi"))
    text = " ".join(m.value for m in notes.markdown)
    assert "tidak dipilih otomatis" in text and "belum dicocokkan dengan aplikasi Bibit" in text and "Rating kredit dan durasi" in text
    assert len(at.warning) <= 2                                       # background notes no longer pile up as yellow boxes


def test_only_urgent_notes_stay_as_warnings():
    assert recommend.note_is_critical("Tidak ada level yang memenuhi semua pemeriksaan risiko Anda; ...")
    assert recommend.note_is_critical("Data produk berumur 40 hari (lebih dari 30).")
    assert recommend.note_is_critical("Dengan isi portofolio sekarang, perkiraan turun total 12% masih di atas batas")
    assert not recommend.note_is_critical("Rating kredit dan durasi dana obligasi tidak tersedia di data ini")
    assert not recommend.note_is_critical("Komposisi profil risiko 3 berasal dari catatan Anda")
    assert not recommend.note_is_critical("Profil risiko 3.5 tidak dipilih otomatis: ...")


def test_a_heavy_failure_is_still_a_visible_warning_in_the_app():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    at.slider(key="rec_drop").set_value(3)                            # a 3% limit: no profile fits
    at = at.run()
    assert not at.exception and any("Tidak ada level" in w.value for w in at.warning)
