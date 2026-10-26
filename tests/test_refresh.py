from datetime import datetime

import pandas as pd
import pytest

from tracker import refresh

ABF = {"name": "ABF Indonesia Bond Index Fund", "path": "/reksadana/RD13",
       "cells": ["Obligasi", "-0.11%", "-1.29%", "1.05%", "-2.23%", "-1.88%", "17.46%", "25.15%", "83.09%",
                 "58,590.3199", "-4.99%", "7.76T"]}
NEW_FUND = {"name": "Syariah Baru Kelas A", "path": "/reksadana/RD9999",
            "cells": ["Pasar Uang", "0.01%", "0.40%", "1.20%", "N/A", "4.10%", "N/A", "N/A", "N/A",
                      "1,010.5000", "0.00%", "441.21B"]}

SBN_TEXT = """Produk SBN yang Telah Terbit
SBR015-T4

Savings Bond Ritel (SBR)

Kupon Imbal Hasil
6.85% / Tahun
Periode Pembelian
28 Sep 2026 - 22 Oct 2026
Jatuh Tempo
10 Oct 2030
Lihat Memo
ORI030-T3

Obligasi Negara Ritel (ORI)

Kupon Imbal Hasil
6.9% / Tahun
Periode Pembelian
6 Jul 2026 - 30 Jul 2026
Jatuh Tempo
15 Jul 2029
Lihat Memo
ST017
Syariah
Sukuk Tabungan
Floating With Floor
Tipe Kupon
"""
FR_ROWS = [
    ["Seri Obligasi", "Yield", "Kupon / Tahun", "Harga Beli", "Harga Jual", "Jatuh Tempo"],
    ["PBS030 | Top Short Term | FR Syariah", "6.56%", "5.875%", "98.90%", "98.05%", "15 Jul 2028"],
    ["FR0090 | Obligasi FR", "5.89%", "5.125%", "99.65%", "98.55%", "15 Apr 2027"],
]
FR_TEXT = "Obligasi Negara\nPBS038\nFR Syariah\nYield\n7.27%\nKupon\n6.875%\nHarga Beli\n95.6%\nJatuh Tempo:\n15 Des 2049\n"


def test_parse_funds_handles_units_missing_values_and_duplicates():
    df = refresh.parse_funds([ABF, NEW_FUND, ABF], "2026-10-26")
    assert list(df["product_id"]) == ["RD13", "RD9999"]  # duplicate row dropped
    abf = df.iloc[0]
    assert (abf["category"], abf["drawdown_1y_pct"], abf["aum_idr"]) == ("pendapatan_tetap", -4.99, 7_760_000_000_000)
    assert abf["last_nav"] == pytest.approx(58590.3199)
    new = df.iloc[1]
    assert pd.isna(new["return_ytd_pct"]) and pd.isna(new["return_3y_pct"])
    assert new["syariah_dari_nama"] == "ya" and new["aum_idr"] == 441_210_000_000


def test_parse_funds_skips_malformed_rows():
    bad = {"name": "x", "path": "/reksadana/RD1", "cells": ["Obligasi", "1%"]}
    assert refresh.parse_funds([bad], "2026-10-26").empty


def test_parse_sbn_series():
    df = refresh.parse_sbn(SBN_TEXT, "2026-10-26")
    assert list(df["kode"]) == ["SBR015-T4", "ORI030-T3"]
    assert list(df["kupon_pct"]) == [6.85, 6.9]
    assert df.iloc[0]["periode_pembelian"] == "28 Sep 2026 - 22 Oct 2026"


def test_parse_next_sbn_from_title():
    nxt = refresh.parse_next_sbn("Investasi SBN Syariah ST017 di Bibit Mulai 6 November 2026", SBN_TEXT, "2026-10-26")
    assert nxt["kode"] == "ST017" and nxt["mulai"] == "6 November 2026"
    assert refresh.parse_next_sbn("Investasi SBN di Bibit", SBN_TEXT, "2026-10-26") is None


def test_parse_fr_table_and_featured_series():
    df = refresh.parse_fr(FR_ROWS, FR_TEXT, "2026-10-26")
    assert list(df["seri"]) == ["PBS030", "FR0090", "PBS038"]
    top = df.iloc[0]
    assert (top["tipe"], top["label"], top["yield_pct"]) == ("FR Syariah", "Top Short Term", 6.56)
    assert list(df["kupon_pct"][:2]) == [5.875, 5.125]  # 3-decimal coupons must not be rounded to 2
    assert pd.isna(df.iloc[2]["harga_jual_pct"]) and df.iloc[2]["harga_beli_pct"] == 95.6


def test_format_markdown_drops_progress_and_bullets_the_rest():
    raw = ("Reksa dana halaman 1...\nReksa dana halaman 2...\nObligasi FR...\nSBN Ritel...\n"
           "Data produk diperbarui (2026-10-26): 147 reksa dana.\n"
           "Berubah: products.csv, obligasi_fr.csv\nTidak berubah: sbn_ritel.csv\n"
           "Data lama diarsipkan di data\\archive\\2026-10-26_204530")
    assert refresh.format_markdown(raw).splitlines() == [
        "**Data produk diperbarui** (2026-10-26): 147 reksa dana",
        "- Berubah: `products.csv`, `obligasi_fr.csv`",
        "- Tidak berubah: `sbn_ritel.csv`",
        "- Data lama diarsipkan di `data\\archive\\2026-10-26_204530`",
    ]


def test_format_markdown_failure_and_empty_output():
    out = refresh.format_markdown("Reksa dana halaman 1...\nGAGAL memperbarui data: bibit.id memblokir akses.")
    assert out == "**GAGAL memperbarui data: bibit.id memblokir akses.**"
    assert refresh.format_markdown("  \n") == "Tidak ada keluaran dari pembaruan."


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(refresh, "DATA", tmp_path)
    monkeypatch.setattr(refresh, "ARCHIVE", tmp_path / "archive")
    monkeypatch.setattr(refresh, "FILES", {k: tmp_path / p.name for k, p in refresh.FILES.items()})
    monkeypatch.setattr(refresh, "MIN_FUNDS", 2)
    return tmp_path


def _datasets(as_of, funds):
    return {
        "funds": refresh.parse_funds(funds, as_of),
        "fr": refresh.parse_fr(FR_ROWS, FR_TEXT, as_of),
        "sbn": refresh.parse_sbn(SBN_TEXT, as_of),
        "next_sbn": refresh.parse_next_sbn("Investasi SBN Syariah ST017 di Bibit Mulai 6 November 2026", SBN_TEXT, as_of),
    }


def test_write_first_time_creates_files_without_archive(sandbox):
    rep = refresh.write(_datasets("2026-10-26", [ABF, NEW_FUND]), "2026-10-26", datetime(2026, 10, 26, 9, 0, 0))
    assert rep.ok and rep.funds == 2 and rep.archived_to is None
    assert (sandbox / "products.csv").exists() and (sandbox / "sbn_berikutnya.json").exists()


def test_write_archives_old_snapshot_when_data_changed(sandbox):
    refresh.write(_datasets("2026-10-26", [ABF, NEW_FUND]), "2026-10-26", datetime(2026, 10, 26, 9, 0, 0))
    changed_abf = {**ABF, "cells": [ABF["cells"][0], *ABF["cells"][1:9], "58,700.0000", "-6.00%", "7.76T"]}
    gone = {**NEW_FUND, "path": "/reksadana/RD7777", "name": "Dana Lain"}
    rep = refresh.write(_datasets("2026-11-02", [changed_abf, gone]), "2026-11-02", datetime(2026, 11, 2, 10, 30, 0))
    assert "products.csv" in rep.changed_datasets
    assert rep.added == ["Dana Lain"] and rep.removed == ["Syariah Baru Kelas A"]
    archived = sandbox / "archive" / "2026-10-26_103000"
    assert (archived / "products.csv").exists()
    assert pd.read_csv(archived / "products.csv")["drawdown_1y_pct"].iloc[0] == -4.99  # the OLD value is kept
    assert pd.read_csv(sandbox / "products.csv")["drawdown_1y_pct"].iloc[0] == -6.0


def test_write_same_data_only_bumps_date_and_does_not_archive(sandbox):
    refresh.write(_datasets("2026-10-26", [ABF, NEW_FUND]), "2026-10-26", datetime(2026, 10, 26, 9, 0, 0))
    rep = refresh.write(_datasets("2026-10-27", [ABF, NEW_FUND]), "2026-10-27", datetime(2026, 10, 27, 9, 0, 0))
    assert rep.changed_datasets == [] and rep.archived_to is None
    assert not (sandbox / "archive").exists()
    assert pd.read_csv(sandbox / "products.csv")["as_of"].iloc[0] == "2026-10-27"


def test_write_keeps_old_data_when_too_few_funds_read(sandbox, monkeypatch):
    third = {**NEW_FUND, "path": "/reksadana/RD8888", "name": "Dana Ketiga"}
    refresh.write(_datasets("2026-10-26", [ABF, NEW_FUND, third]), "2026-10-26", datetime(2026, 10, 26, 9, 0, 0))
    monkeypatch.setattr(refresh, "MIN_FUNDS", 1)  # passes the absolute floor, but 1 < half of the previous 3
    rep = refresh.write(_datasets("2026-11-02", [ABF]), "2026-11-02", datetime(2026, 11, 2, 9, 0, 0))
    assert not rep.ok and "dipertahankan" in rep.warnings[0]
    assert len(pd.read_csv(sandbox / "products.csv")) == 3  # untouched
    assert not (sandbox / "archive").exists()


def test_dry_run_writes_nothing(sandbox):
    rep = refresh.write(_datasets("2026-10-26", [ABF, NEW_FUND]), "2026-10-26", dry_run=True)
    assert rep.funds == 2 and not (sandbox / "products.csv").exists()


def test_failed_write_never_leaves_a_truncated_products_csv(sandbox, monkeypatch):
    refresh.write(_datasets("2026-10-26", [ABF, NEW_FUND]), "2026-10-26", datetime(2026, 10, 26, 9, 0, 0))
    before = (sandbox / "products.csv").read_bytes()
    changed = {**ABF, "cells": [ABF["cells"][0], *ABF["cells"][1:9], "58,700.0000", "-6.00%", "7.76T"]}

    def boom(self, *a, **k):
        raise OSError("disk penuh")

    monkeypatch.setattr(pd.DataFrame, "to_csv", boom)
    with pytest.raises(OSError):
        refresh.write(_datasets("2026-11-02", [changed, NEW_FUND]), "2026-11-02", datetime(2026, 11, 2, 9, 0, 0))
    assert (sandbox / "products.csv").read_bytes() == before  # the good snapshot survives the crash
