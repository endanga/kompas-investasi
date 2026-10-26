import pandas as pd
import pytest

from tracker import portfolio_io as pio


@pytest.mark.parametrize("raw, expected", [
    ("Rp1.500.000", 1_500_000), ("1.500.000", 1_500_000), ("1,500,000", 1_500_000), ("1.500.000,50", 1_500_000.5),
    ("1,500,000.5", 1_500_000.5), (" 2500000 ", 2_500_000), (1_000, 1_000), ("abc", None), ("", None), (None, None),
])
def test_parse_amount(raw, expected):
    assert pio.parse_amount(raw) == expected


def test_read_csv_accepts_semicolons_bom_and_indonesian_headers():
    raw = "﻿produk;jenis;nilai\nDanamas Stabil;Obligasi;Rp3.000.000\n".encode("utf-8")
    df = pio.read_csv_bytes(raw)
    assert pio.detect_kind(df) == "holdings"
    clean, errors = pio.clean_holdings(df)
    assert errors == [] and clean.iloc[0].tolist() == ["Danamas Stabil", "pendapatan_tetap", 3_000_000]


def test_clean_holdings_reports_row_numbers_and_sums_duplicates():
    df = pd.DataFrame({"product": ["A", "A", "", "B", "C"], "category": ["saham", "saham", "saham", "xx", "sbn"],
                       "current_value": ["100", "50", "10", "10", "-5"]})
    clean, errors = pio.clean_holdings(df)
    assert clean.to_dict("records") == [{"product": "A", "category": "saham", "current_value": 150.0}]
    assert len(errors) == 3 and errors[0].startswith("Baris 4") and "tidak dikenal" in errors[1]


def test_clean_transactions_validates_and_normalises():
    df = pd.DataFrame({"date": ["2026-09-05", "bukan tanggal", "2026-09-01", "2026-09-02"],
                       "product": ["A", "A", "B", "C"], "category": ["saham", "saham", "obligasi", "saham"],
                       "type": ["buy", "BUY", "Jual", "HOLD"], "amount": ["500.000", "1", "200000", "5"]})
    clean, errors = pio.clean_transactions(df)
    assert clean[["date", "type", "category", "amount"]].values.tolist() == [
        ["2026-09-01", "SELL", "pendapatan_tetap", 200000.0], ["2026-09-05", "BUY", "saham", 500000.0]]
    assert len(errors) == 2 and "tanggal" in errors[0] and "BUY atau SELL" in errors[1]


def test_missing_columns_are_reported_not_raised():
    _, errors = pio.clean_holdings(pd.DataFrame({"product": ["A"]}))
    assert "Kolom tidak ada" in errors[0]
    assert pio.detect_kind(pd.DataFrame({"x": [1]})) is None


def test_merge_replaces_holding_value_and_dedupes_transactions():
    old = pd.DataFrame([("A", "saham", 10.0), ("B", "sbn", 5.0)], columns=pio.HOLDINGS_COLS)
    new = pd.DataFrame([("a ", "saham", 99.0)], columns=pio.HOLDINGS_COLS)
    merged = pio.merge(old, new, "holdings")
    assert merged.set_index("product")["current_value"].to_dict() == {"B": 5.0, "a ": 99.0}
    t = pd.DataFrame([("2026-09-05", "A", "saham", "BUY", 100.0)], columns=pio.TX_COLS)
    assert len(pio.merge(t, t, "transactions")) == 1


def test_buy_adds_and_sell_reduces_and_drops_empty_position():
    h = pd.DataFrame([("A", "saham", 100.0)], columns=pio.HOLDINGS_COLS)
    h = pio.apply_transaction_to_holdings(h, "A", "saham", "BUY", 50.0)
    assert h.iloc[0]["current_value"] == 150.0
    h = pio.apply_transaction_to_holdings(h, "a", "saham", "SELL", 500.0)
    assert h.empty
    new = pio.apply_transaction_to_holdings(h, "Baru", "sbn", "BUY", 10.0)
    assert new.iloc[0].tolist() == ["Baru", "sbn", 10.0]


def test_save_roundtrip_archives_previous_file(tmp_path):
    (tmp_path / "holdings.csv").write_text("product,category,current_value\nA,saham,100\n", encoding="utf-8")
    (tmp_path / "transactions.csv").write_text("date,product,category,type,amount\n", encoding="utf-8")
    h = pd.DataFrame([("B", "sbn", 2_500_000.4)], columns=pio.HOLDINGS_COLS)
    pio.save(h, None, tmp_path)
    assert (tmp_path / "holdings.csv").read_text(encoding="utf-8") == "product,category,current_value\nB,sbn,2500000\n"
    archived = list((tmp_path / "archive").glob("holdings_*.csv"))
    assert len(archived) == 1 and "A,saham,100" in archived[0].read_text(encoding="utf-8")
    assert list((tmp_path / "archive").glob("transactions_*")) == []  # empty file is not worth archiving
    holdings, tx = pio.read_current(tmp_path)
    assert holdings.iloc[0]["current_value"] == 2_500_000 and tx.empty and tx["amount"].dtype.kind in "fi"


def test_infer_category_from_catalog():
    catalog = pd.DataFrame({"name": ["Danamas Stabil"], "category": ["pendapatan_tetap"]})
    assert pio.infer_category(" danamas stabil ", catalog) == "pendapatan_tetap"
    assert pio.infer_category("Tidak ada", catalog) is None
