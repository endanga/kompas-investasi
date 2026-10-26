from datetime import date

import pandas as pd
import pytest

from tracker import metrics, rules


def test_xirr_simple_one_year_ten_percent():
    r = metrics.xirr([(date(2025, 1, 1), -1000.0), (date(2026, 1, 1), 1100.0)])
    assert r == pytest.approx(0.10, abs=1e-4)


def test_xirr_none_when_all_same_sign():
    assert metrics.xirr([(date(2025, 1, 1), -1000.0), (date(2026, 1, 1), -50.0)]) is None


def test_xirr_none_when_same_day():
    assert metrics.xirr([(date(2025, 1, 1), -1000.0), (date(2025, 1, 1), 1100.0)]) is None


def test_max_drawdown():
    s = pd.Series([100, 120, 90, 110])
    assert metrics.max_drawdown(s) == pytest.approx(-0.25)


def test_future_value_dca_zero_rate():
    assert metrics.future_value_dca(500_000, 0.0, 1) == 6_000_000


def test_future_value_dca_known_value():
    # 1000/month, 12% p.a. (1% monthly), 12 months -> 1000 * ((1.01^12 - 1) / 0.01) = 12682.50
    assert metrics.future_value_dca(1000, 0.12, 1) == pytest.approx(12682.50, abs=0.01)


def test_total_invested_and_allocation():
    tx = pd.DataFrame({"type": ["BUY", "BUY", "SELL"], "amount": [100.0, 50.0, 30.0]})
    assert metrics.total_invested(tx) == 120.0
    h = pd.DataFrame({"product": ["a", "b"], "category": ["saham", "pasar_uang"], "current_value": [75.0, 25.0]})
    alloc = metrics.allocation_by(h, "category")
    assert alloc["saham"] == pytest.approx(0.75)


def test_stress_loss_bibit_level_5():
    alloc = {"pasar_uang": 0.10, "pendapatan_tetap": 0.65, "saham": 0.25}
    # 0.65 * -5% + 0.25 * -30% = -10.75%
    assert metrics.stress_loss(alloc) == pytest.approx(-0.1075)


def test_stress_loss_custom_shocks():
    assert metrics.stress_loss({"saham": 0.5, "pasar_uang": 0.5}, {"saham": -0.2}) == pytest.approx(-0.10)


def test_products_snapshot_loads_and_robo_funds_exist():
    from tracker import products

    df = products.load_products()
    assert df["product_id"].is_unique
    assert set(products.ROBO_FUNDS.values()) <= set(df["name"])
    shocks = products.robo_shocks(df)
    assert set(shocks) == set(products.ROBO_FUNDS)
    assert all(v <= 0 for v in shocks.values())


def test_sbn_and_fr_snapshots_load():
    from tracker import products

    sbn, fr, inst = products.load_sbn(), products.load_fr(), products.load_instruments()
    assert len(sbn) > 0 and sbn["kode"].is_unique
    assert len(fr) > 0 and fr["seri"].is_unique
    assert (fr["harga_beli_pct"] > 0).all() and (fr["yield_pct"] > 0).all()
    assert {"SBR", "ST", "ORI", "SR", "FR"} == set(inst["kode"])


def _fund(name, cat, r1, r3, dd, aum, syariah="tidak"):
    return {"name": name, "category": cat, "return_1y_pct": r1, "return_3y_pct": r3, "drawdown_1y_pct": dd,
            "aum_idr": aum, "syariah_dari_nama": syariah}


def test_recommend_filters_usd_small_and_ranks():
    from tracker import recommend

    df = pd.DataFrame([
        _fund("Alpha Kas", "pasar_uang", 4.0, 12.0, 0.0, 5e12),
        _fund("Beta Kas USD", "pasar_uang", 9.0, 20.0, 0.0, 9e12),  # excluded: foreign currency
        _fund("Gamma Kas", "pasar_uang", 5.0, 14.0, 0.0, 1e9),  # excluded: too small
    ])
    ranked = recommend.rank_category(df, "pasar_uang")
    assert list(ranked["name"]) == ["Alpha Kas"]


def test_recommend_needs_three_year_history_outside_money_market():
    from tracker import recommend

    df = pd.DataFrame([
        _fund("Baru Obligasi", "pendapatan_tetap", 6.0, None, -1.0, 5e11),
        _fund("Lama Obligasi", "pendapatan_tetap", 3.0, 15.0, -2.0, 5e11),
    ])
    assert list(recommend.rank_category(df, "pendapatan_tetap")["name"]) == ["Lama Obligasi"]


def test_recommend_syariah_only_filter():
    from tracker import recommend

    df = pd.DataFrame([
        _fund("Konvensional", "pasar_uang", 4.0, 12.0, 0.0, 5e12),
        _fund("Syariah Kas", "pasar_uang", 3.5, 11.0, 0.0, 5e12, syariah="ya"),
    ])
    assert list(recommend.rank_category(df, "pasar_uang", syariah_only=True)["name"]) == ["Syariah Kas"]


def test_recommend_picks_highest_level_within_limit_and_respects_horizon_cap():
    from tracker import recommend

    funds = []
    for cat, dd in (("pasar_uang", 0.0), ("pendapatan_tetap", -5.0), ("saham", -30.0)):
        for i in range(3):
            funds.append(_fund(f"{cat}{i}", cat, 4.0, 15.0, dd, 5e11))
    df = pd.DataFrame(funds)
    profiles = {
        "bibit_2_konservatif": {"pasar_uang": 0.58, "pendapatan_tetap": 0.32, "saham": 0.10},
        "bibit_5_moderat": {"pasar_uang": 0.10, "pendapatan_tetap": 0.65, "saham": 0.25},
        "bibit_9_agresif": {"pasar_uang": 0.10, "pendapatan_tetap": 0.24, "saham": 0.66},
    }
    # stress: level 2 = -4.6%, level 5 = -10.75%, level 9 = -21%
    r = recommend.recommend(df, profiles, max_drop=0.12, horizon_years=25, monthly_budget=1_000_000)
    assert r.profile_key == "bibit_5_moderat" and r.within_limit
    assert r.stress_loss == pytest.approx(-0.1075)
    assert sum(r.monthly_amounts.values()) == pytest.approx(1_000_000)

    short = recommend.recommend(df, profiles, max_drop=0.50, horizon_years=2, monthly_budget=1_000_000)
    assert short.profile_key == "bibit_2_konservatif"  # horizon cap 3 excludes levels 5 and 9

    tight = recommend.recommend(df, profiles, max_drop=0.01, horizon_years=25, monthly_budget=1_000_000)
    assert tight.profile_key == "bibit_2_konservatif" and not tight.within_limit


def test_recommend_real_data_smoke():
    from tracker import products, recommend

    r = recommend.recommend(products.load_products(), rules.load_profiles(), 0.10, 25, 5_000_000)
    assert r.within_limit and -r.stress_loss <= 0.10
    assert set(r.picks) == set(r.monthly_amounts)
    for df in r.picks.values():
        assert not df["name"].str.contains(r"\busd\b|dolar|dollar", case=False).any()


def test_annualize_blend_deflate():
    assert metrics.annualize_total_return(21.0, 2) == pytest.approx(0.10)
    assert metrics.annualize_total_return(-100, 3) is None
    assert metrics.blended_rate({"a": 0.5, "b": 0.5}, {"a": 0.04, "b": 0.08}) == pytest.approx(0.06)
    assert metrics.deflate(1_100_000, 0.10, 1) == pytest.approx(1_000_000)


def test_history_compare_weighted_and_missing():
    from tracker import recommend

    picks = {
        "a": pd.Series({"return_1y_pct": 10.0, "return_3y_pct": 30.0, "return_5y_pct": 50.0, "drawdown_1y_pct": -2.0}),
        "b": pd.Series({"return_1y_pct": 0.0, "return_3y_pct": 10.0, "return_5y_pct": None, "drawdown_1y_pct": -10.0}),
    }
    out = recommend.history_compare({"a": 0.5, "b": 0.5}, picks)
    assert out["return_1y_pct"] == pytest.approx(5.0)
    assert out["drawdown_1y_pct"] == pytest.approx(-6.0)
    assert out["return_5y_pct"] is None  # one fund lacks 5y history -> unknown, not guessed


def test_history_compare_ignores_zero_share_categories():
    from tracker import recommend

    picks = {"a": pd.Series({"return_1y_pct": 8.0, "return_3y_pct": 24.0, "return_5y_pct": 40.0, "drawdown_1y_pct": -4.0})}
    out = recommend.history_compare({"a": 1.0, "campuran": 0.0, "sbn": 0.0}, picks)
    assert out["return_1y_pct"] == pytest.approx(8.0)


def test_robo_level_4_5_matches_screenshot():
    assert rules.load_profiles()["bibit_4.5_moderat"] == {
        "pasar_uang": 0.12, "pendapatan_tetap": 0.70, "saham": 0.18, "campuran": 0.0, "sbn": 0.0,
    }


def test_for_level_returns_requested_level_whatever_the_limit():
    from tracker import products, recommend

    prof = rules.load_profiles()
    cat = products.load_products()
    r = recommend.for_level(cat, prof, "bibit_9_agresif", 5_000_000, max_drop=0.10)
    assert r.profile_key == "bibit_9_agresif" and r.level == 9.0
    assert r.within_limit is False  # a 66% stock level cannot fit a 10% limit
    assert sum(r.monthly_amounts.values()) == pytest.approx(5_000_000)
    low = recommend.for_level(cat, prof, "bibit_1_konservatif", 5_000_000, max_drop=0.10)
    assert low.within_limit is True


def test_start_plan_ramps_up():
    from tracker import recommend

    plan = recommend.start_plan(5_000_000)
    assert [amt for _, amt in plan] == [2_000_000, 3_500_000, 5_000_000]


def test_months_with_buys():
    tx = pd.DataFrame({"date": pd.to_datetime(["2026-08-10", "2026-09-05", "2026-09-20"]), "type": ["BUY"] * 3})
    assert metrics.months_with_buys(tx, date(2026, 10, 26), window=6) == 2


def test_rules_flag_short_horizon_with_stocks():
    profile = rules.Profile(level_key="bibit_9_agresif", horizon_years=2, monthly_expense=0)
    tx = pd.DataFrame({"date": pd.to_datetime(["2026-09-01"]), "type": ["BUY"], "amount": [100.0]})
    h = pd.DataFrame({
        "product": ["a", "b"], "category": ["saham", "pasar_uang"], "current_value": [60.0, 40.0],
    })
    titles = [f.title for f in rules.evaluate(profile, tx, h, date(2026, 10, 26))]
    assert "Aset saham besar untuk tujuan jangka pendek" in titles


def test_load_profiles_sum_to_one_and_no_emas():
    profiles = rules.load_profiles()
    levels = [rules.level_of(k) for k in profiles]
    assert None not in levels  # every profile is a Bibit level; no home-made duplicates
    assert (min(levels), max(levels)) == (1.0, 10.0)
    for alloc in profiles.values():
        assert sum(alloc.values()) == pytest.approx(1.0)
        assert "emas" not in alloc


def test_short_horizon_uses_conservative_target():
    p = rules.Profile(level_key="bibit_9_agresif", horizon_years=2, monthly_expense=0)
    assert rules.target_allocation(p) == rules.load_profiles()["bibit_3_konservatif"]  # highest level within cap 3


def test_target_allocation_keeps_level_when_horizon_is_long():
    p = rules.Profile(level_key="bibit_4.5_moderat", horizon_years=25, monthly_expense=0)
    assert rules.target_allocation(p) == rules.load_profiles()["bibit_4.5_moderat"]


def test_rules_flag_emergency_fund():
    profile = rules.Profile(level_key="bibit_5_moderat", horizon_years=10, monthly_expense=5_000_000)
    tx = pd.DataFrame({"date": pd.to_datetime(["2026-09-01"]), "type": ["BUY"], "amount": [100.0]})
    h = pd.DataFrame({"product": ["a"], "category": ["saham"], "current_value": [1_000_000.0]})
    titles = [f.title for f in rules.evaluate(profile, tx, h, date(2026, 10, 26))]
    assert "Dana darurat belum penuh" in titles
