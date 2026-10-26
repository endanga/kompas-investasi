"""Fact sheet parser on the real layouts of two funds that used to be unreadable (text excerpts, 30 Sep 2026)."""
from pathlib import Path

import pytest

from tracker import factsheet as f

FIX = Path(__file__).parent / "fixtures"


def read(name):
    return (FIX / name).read_text(encoding="utf-8")


# ---- Manulife Obligasi Unggulan: holdings are INDOGB tickers, percentage on the next line
def test_manulife_reads_all_ten_indogb_holdings():
    holdings = f.top_holdings(read("manulife_obligasi_unggulan_2026-09.txt"))
    assert [p for _, p in holdings] == [8.77, 6.96, 5.59, 5.53, 5.02, 4.37, 3.44, 3.43, 3.39, 3.37]   # as printed in the PDF
    assert holdings[0][0] == "INDOGB 8 3/4 05/15/31"


def test_manulife_summary_matches_the_figures_in_the_pdf():
    out = f.summarize(read("manulife_obligasi_unggulan_2026-09.txt"))
    assert out["gov_top10_pct"] == 100.0 and out["unknown_top10_pct"] == 0.0
    assert out["top1_pct"] == 8.77 and out["top10_sum_pct"] == pytest.approx(49.9, abs=0.05) and out["top10_n"] == 10


def test_the_policy_range_lines_are_not_read_as_holdings():
    names = [n for n, _ in f.top_holdings(read("manulife_obligasi_unggulan_2026-09.txt"))]
    assert not any("Obligasi" in n or "Pasar Uang" in n for n in names)          # "Obligasi Pemerintah : 40 - 100%" is a policy


# ---- ABF Indonesia Bond Index: names and percentages sit in separate columns of one table
def test_abf_plain_text_is_unreadable_and_says_so_instead_of_guessing():
    out = f.summarize(read("abf_indonesia_bond_plain_2026-09.txt"))
    assert out["gov_top10_pct"] is None and out["top1_pct"] is None and out["top10_sum_pct"] is None


def test_abf_layout_text_recovers_every_holding_with_its_own_percentage():
    holdings = f.top_holdings(read("abf_indonesia_bond_layout_2026-09.txt"))
    assert [p for _, p in holdings] == [3.83, 3.62, 3.45, 3.33, 3.25, 3.24, 3.23, 3.20, 2.98, 2.95]
    assert holdings[0][0].endswith("FR0103") and holdings[-1][0].endswith("FR0100")


def test_abf_summary_matches_the_figures_in_the_pdf():
    out = f.summarize(read("abf_indonesia_bond_layout_2026-09.txt"))
    assert out["gov_top10_pct"] == 100.0 and out["top1_pct"] == 3.83 and out["top10_sum_pct"] == pytest.approx(33.1, abs=0.05)


def test_custodian_bank_and_fee_lines_are_not_holdings():
    names = " ".join(n for n, _ in f.top_holdings(read("abf_indonesia_bond_layout_2026-09.txt")))
    assert "HSBC" not in names and "Maks" not in names


# ---- classification, groups, sanity checks
def test_only_positive_evidence_makes_a_holding_corporate():
    assert f.classify("INDOGB 7 02/15/33") == "pemerintah"
    assert f.classify("Obligasi Berkelanjutan III Astra Sedaya Finance Tahap II") == "korporasi"
    assert f.classify("Bank Pan Indonesia") == "tidak diketahui"                    # bond or deposit: the text cannot say
    assert f.classify("Bank Negara Indonesia") == "tidak diketahui"                 # a bank, not the state


def _text(rows):
    return "\n".join(f"{n}\n{p}%" for n, p in rows)


def test_unidentified_holdings_stay_in_the_denominator_and_are_reported():
    rows = [("FR0101", 10), ("FR0102", 10), ("FR0103", 10), ("Bank Pan Indonesia", 10), ("Bank Mega", 10)]
    out = f.summarize(_text(rows))
    assert out["gov_top10_pct"] == 60.0 and out["unknown_top10_pct"] == 40.0          # unknown never counts as government


def test_a_group_heading_is_not_a_single_issuer():
    assert f.is_group("Obligasi Pemerintah") and f.is_group("Obligasi Korporasi")
    assert not f.is_group("Obligasi Negara Republik Indonesia Seri FR0101")
    rows = [("Obligasi Pemerintah", 55.0), ("Astra Sedaya Finance Tahap I", 5.0), ("Adira Finance Tahap II", 4.0),
            ("Bank Pan Indonesia Tbk, PT", 3.0), ("Sinar Mas Multifinance", 3.0)]
    out = f.summarize(_text(rows))
    assert out["top1_pct"] == 5.0 and out["gov_top10_pct"] == pytest.approx(100 * 55 / 70, abs=0.1)     # 55% group is not an issuer


def test_a_total_above_100_percent_means_misread_and_reports_nothing():
    rows = [(f"FR010{i}", 30.0) for i in range(5)]
    out = f.summarize(_text(rows))
    assert out["gov_top10_pct"] is None and out["top1_pct"] is None


def test_a_repeated_holding_is_counted_once():
    rows = [("FR0101", 5.0)] * 3 + [("FR0102", 5.0), ("FR0103", 5.0), ("FR0104", 5.0), ("FR0105", 5.0), ("FR0106", 5.0)]
    holdings = f.top_holdings(_text(rows))
    assert len(holdings) == 6 and sum(p for _, p in holdings) == 30.0


def test_too_few_holdings_is_unknown_not_zero():
    out = f.summarize(_text([("FR0101", 5.0), ("PT Foo Tbk", 5.0)]))
    assert out["gov_top10_pct"] is None and out["top10_n"] == 2


def test_empty_and_garbage_text_do_not_crash():
    assert f.summarize("")["gov_top10_pct"] is None
    assert f.summarize("\x00\n%%%\n12345")["gov_top10_pct"] is None
