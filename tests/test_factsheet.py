import pandas as pd
import pytest

from tracker import factsheet, recommend

CORPORATE = """Top 10 Kepemilikan Efek
Armadian Tritunggal, PT
Obligasi
2.55%
Bank Kb Indonesia Tbk, PT
Obligasi
2.96%
Energi Mitra Investama, PT
Obligasi
2.82%
Merdeka Copper Gold Tbk, PT
Obligasi
2.80%
Oki Pulp & Paper Mills, PT
Obligasi
2.63%
Bank Kustodian
PT Bank CIMB Niaga TBK
"""
ONE_LINE = "\n".join(f"FR{100 + i} 6.5% 15 Feb 2030 {w}%" for i, w in enumerate([10, 10, 10, 10, 10, 10]))


def test_corporate_fund_has_zero_government_share():
    assert factsheet.government_share(CORPORATE) == (0.0, 5)


def test_government_series_on_one_line_count_as_government():
    share, n = factsheet.government_share(ONE_LINE)
    assert share == 100.0 and n == 6


def test_bank_negara_is_a_bank_not_the_state():
    text = "\n".join(f"Bank Negara Indonesia Tahap {i}\nObligasi\n{3 + i}.0%" for i in range(6))
    assert factsheet.government_share(text)[0] == 0.0


def test_too_few_readable_holdings_means_unknown_not_zero():
    assert factsheet.government_share("Armadian, PT\n2.5%\nBank X Tbk\n3.0%")[0] is None
    assert factsheet.government_share("no holdings here")[0] is None


def _bonds(**gov) -> pd.DataFrame:
    rows = []
    for name, g in gov.items():
        rows.append({"product_id": name, "name": name, "category": "pendapatan_tetap", "syariah_dari_nama": "tidak",
                     "return_1y_pct": 4.0, "return_3y_pct": 18.0, "drawdown_1y_pct": -1.0, "aum_idr": 5e11, "gov_top10_pct": g})
    return pd.DataFrame(rows)


def test_more_government_bonds_ranks_higher_when_everything_else_is_equal():
    out = recommend.rank_category(_bonds(Corp=0.0, Mixed=50.0, Gov=100.0), "pendapatan_tetap")
    assert list(out["name"]) == ["Gov", "Mixed", "Corp"]


def test_unknown_share_is_ranked_between_not_punished():
    out = recommend.rank_category(_bonds(Corp=0.0, Unknown=float("nan"), Gov=100.0), "pendapatan_tetap")
    assert list(out["name"]) == ["Gov", "Unknown", "Corp"]


def test_old_products_file_without_the_column_still_ranks():
    old = _bonds(A=0.0, B=0.0).drop(columns="gov_top10_pct")
    assert len(recommend.rank_category(old, "pendapatan_tetap")) == 2
