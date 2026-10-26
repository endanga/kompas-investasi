from datetime import datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tracker import history, metrics, products, recommend, report, rules, ui

ROOT = Path(__file__).parent.parent
PROFILE_4_5 = {"pasar_uang": 0.12, "pendapatan_tetap": 0.70, "saham": 0.18}


def test_crisis_shocks_follow_the_three_inputs():
    s = metrics.crisis_shocks(40, 8, 0)
    assert s["saham"] == pytest.approx(-0.40) and s["pendapatan_tetap"] == pytest.approx(-0.08) and s["pasar_uang"] == 0
    assert s["sbn"] == s["pendapatan_tetap"]                                    # SBN moves like bonds
    assert s["campuran"] == pytest.approx(0.6 * -0.40 + 0.4 * -0.08)            # mixed fund = 60% stocks, 40% bonds


def test_profile_4_5_breaks_a_10_percent_limit_in_the_default_crisis():
    loss = metrics.stress_loss(PROFILE_4_5, metrics.crisis_shocks())
    assert loss == pytest.approx(-0.128) and -loss > 0.10


def test_risk_meter_with_crisis_shows_two_rows_each_with_icon_and_words():
    out = ui.risk_meter(-0.088, 0.10, "light", crisis_loss=-0.128)
    assert "Tahun buruk (data 1 tahun)" in out and "Krisis berat (asumsi)" in out
    assert "✓ Dalam batas Anda" in out and "✕ Melewati batas Anda" in out          # one passes, one fails
    assert "-8,8%" in out and "-12,8%" in out and out.count("batas -10%") == 1       # the limit is labelled once
    single = ui.risk_meter(-0.088, 0.10, "light")
    assert "Krisis" not in single and "Perkiraan turun di tahun buruk" in single


@pytest.fixture(scope="module")
def rec():
    return recommend.recommend(products.load_products(), rules.load_profiles(), 0.10, 25, 5_000_000)


INPUTS = {"horizon_years": 25.0, "monthly_budget": 5_000_000.0, "max_drop_pct": 10, "syariah_only": False, "auto": True}


def test_saved_record_keeps_crisis_numbers_and_pdf_shows_them(rec):
    crisis = {"loss": -0.128, "shocks": metrics.crisis_shocks()}
    snap = history.snapshot(rec, INPUTS, "2026-10-26", now=datetime(2026, 10, 26, 9, 0), crisis=crisis)
    assert snap["crisis"]["loss"] == -0.128 and snap["crisis"]["shocks"]["saham"] == -0.40
    assert report.build_pdf(snap).startswith(b"%PDF")
    legacy = history.snapshot(rec, INPUTS, "2026-10-26", now=datetime(2026, 10, 26, 9, 0))
    assert "crisis" not in legacy and report.build_pdf(legacy).startswith(b"%PDF")      # older saved records still render


def test_app_warns_when_the_crisis_scenario_breaks_the_limit():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception
    assert any("Krisis berat (asumsi)" in m.value for m in at.markdown)
    assert any("krisis berat terjadi" in w.value for w in at.warning)
    # a mild crisis keeps profile 4.5 inside the limit, so the warning goes away
    sliders = {s.label: s for s in at.sidebar.slider}
    sliders["Saham turun (%)"].set_value(25)
    sliders["Obligasi turun (%)"].set_value(3)
    at = at.run()
    assert not at.exception and not any("krisis berat terjadi" in w.value for w in at.warning)
