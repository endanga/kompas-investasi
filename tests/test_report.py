from datetime import datetime

import pytest

from tracker import history, products, recommend, report, rules

INPUTS = {"horizon_years": 25.0, "monthly_budget": 5_000_000.0, "max_drop_pct": 10, "syariah_only": False, "auto": True}
PROJECTION = {"inflation": 0.04, "rates": {"Pesimis": 0.045, "Dasar": 0.07, "Optimis": 0.09}}


@pytest.fixture(scope="module")
def rec():
    return recommend.recommend(products.load_products(), rules.load_profiles(), 0.10, 25, 5_000_000)



def test_build_pdf_returns_a_pdf_for_current_and_saved_snapshots(rec):
    snap = history.snapshot(rec, INPUTS, "2026-10-26", "catatan <b>uji</b> & lain", now=datetime(2026, 10, 26, 9, 0),
                            projection=PROJECTION)
    for current in (True, False):
        data = report.build_pdf(snap, current=current)
        assert data.startswith(b"%PDF") and len(data) > 5_000


def test_build_pdf_handles_legacy_snapshot_without_projection(rec):
    legacy = history.snapshot(rec, INPUTS, "2026-10-26", now=datetime(2026, 10, 26, 9, 0))
    assert "projection" not in legacy
    assert report.build_pdf(legacy).startswith(b"%PDF")


def test_build_pdf_survives_missing_numbers_and_over_limit(rec):
    snap = history.snapshot(rec, INPUTS, "2026-10-26", now=datetime(2026, 10, 26, 9, 0), projection=PROJECTION)
    first = next(iter(snap["picks"].values()))[0]
    first.update(return_1y_pct=None, drawdown_1y_pct=None, aum_idr=None, alasan=None, url=None)
    snap["within_limit"], snap["stress_loss"] = False, -0.15
    assert report.build_pdf(snap).startswith(b"%PDF")


def test_snapshot_keeps_projection_assumptions_only_when_given(rec):
    snap = history.snapshot(rec, INPUTS, "2026-10-26", projection=PROJECTION)
    assert snap["projection"]["rates"]["Dasar"] == 0.07 and snap["projection"]["inflation"] == 0.04


def test_filename_marks_current_report():
    snap = {"saved_at": "2026-10-26T20:48:56"}
    assert report.filename(snap) == "laporan-rekomendasi_2026-10-26_2048.pdf"
    assert report.filename(snap, current=True) == "laporan-rekomendasi_saat-ini_2026-10-26_2048.pdf"


def test_build_pdf_with_portfolio_block_and_held_product(rec):
    import pandas as pd

    from tracker import portfolio_plan as pp

    top = rec.picks["pendapatan_tetap"].iloc[0]["name"]
    held = pd.DataFrame([(top, "pendapatan_tetap", 4_000_000), ("X", "saham", 6_000_000)],
                        columns=["product", "category", "current_value"])
    fitted = pp.apply(rec, held, 5_000_000.0, 0.10)
    snap = history.snapshot(fitted, INPUTS, "2026-10-26", projection=PROJECTION, portfolio=pp.snapshot_block(fitted.plan))
    assert snap["portfolio"]["total_now"] == 10_000_000 and "held_idr" in next(iter(snap["picks"].values()))[0]
    assert report.build_pdf(snap, current=True).startswith(b"%PDF")
