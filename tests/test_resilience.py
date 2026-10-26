import shutil
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tracker import portfolio_io, products

ROOT = Path(__file__).parent.parent
APP = str(ROOT / "app.py")


@pytest.fixture()
def data(tmp_path, monkeypatch):
    """A private copy of data/ that products.PRODUCTS_FILE points to, so tests can break it freely."""
    for f in (ROOT / "data").glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    shutil.copy(ROOT / "data" / "sbn_berikutnya.json", tmp_path)
    monkeypatch.setattr(products, "PRODUCTS_FILE", tmp_path / "products.csv")
    return tmp_path


def _header(path: Path) -> None:
    path.write_text(path.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")


def _run() -> AppTest:
    return AppTest.from_file(APP, default_timeout=120).run()


def test_check_catalog_explains_each_problem():
    good = pd.read_csv(ROOT / "data" / "products.csv")
    assert products.check_catalog(good) is None
    assert "hanya baris judul" in products.check_catalog(good.head(0))
    assert "terlalu sedikit" in products.check_catalog(good.head(3))
    assert "Kolom wajib" in products.check_catalog(good.drop(columns=["name"]))
    assert "tidak valid" in products.check_catalog(good.assign(as_of="bukan-tanggal"))


def test_try_load_products_never_raises(data):
    assert products.try_load_products()[1] is None
    _header(data / "products.csv")
    assert "hanya baris judul" in products.try_load_products()[1]
    (data / "products.csv").write_text("", encoding="utf-8")
    assert "tidak bisa dibaca" in products.try_load_products()[1]
    (data / "products.csv").unlink()
    assert "tidak ditemukan" in products.try_load_products()[1]


@pytest.mark.parametrize("break_it", ["header_only", "missing"])
def test_app_shows_recovery_screen_instead_of_crashing(data, break_it):
    if break_it == "header_only":
        _header(data / "products.csv")
    else:
        (data / "products.csv").unlink()
    at = _run()
    assert not at.exception
    assert any("Data produk belum tersedia" in m.value for m in at.markdown)
    assert any(b.label == "Perbarui data produk" for b in at.button)  # the way out must be reachable
    assert not at.tabs  # the normal app did not render


def test_app_runs_when_sbn_and_fr_tables_are_empty(data):
    for name in ("obligasi_fr.csv", "sbn_ritel.csv", "instrumen_sbn_fr.csv"):
        _header(data / name)
    at = _run()
    assert not at.exception
    assert any("belum tersedia" in w.value for w in at.warning)


def test_app_survives_a_tiny_catalog_with_no_eligible_funds(data):
    pd.read_csv(data / "products.csv").head(6).to_csv(data / "products.csv", index=False)
    assert not _run().exception


def test_archive_listing_and_restore_roundtrip(tmp_path):
    good = ROOT / "data" / "products.csv"
    old, bad = tmp_path / "archive" / "2026-10-20_090000", tmp_path / "archive" / "2026-10-25_090000"
    old.mkdir(parents=True)
    bad.mkdir(parents=True)
    shutil.copy(good, old / "products.csv")
    _header_file = bad / "products.csv"
    _header_file.write_text(good.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")  # unusable snapshot
    found = products.list_archives(tmp_path / "archive")
    assert [a["name"] for a in found] == ["2026-10-20_090000"] and found[0]["funds"] == 147
    target = tmp_path / "live"
    target.mkdir()
    (target / "products.csv").write_text("rusak", encoding="utf-8")
    assert products.restore_archive(old, target) == ["products.csv"]
    assert len(pd.read_csv(target / "products.csv")) == 147 and not list(target.glob("*.tmp"))


def test_ensure_files_creates_missing_portfolio_csvs(tmp_path):
    portfolio_io.ensure_files(tmp_path)
    assert (tmp_path / "holdings.csv").read_text(encoding="utf-8") == "product,category,current_value\n"
    (tmp_path / "holdings.csv").write_text("product,category,current_value\nA,saham,5\n", encoding="utf-8")
    portfolio_io.ensure_files(tmp_path)  # an existing file is never overwritten
    assert "A,saham,5" in (tmp_path / "holdings.csv").read_text(encoding="utf-8")
