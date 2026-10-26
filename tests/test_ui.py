import pandas as pd
import pytest

from tracker import ui


def test_fmt_idr_uses_dot_thousands():
    assert ui.fmt_idr(5_000_000) == "Rp5.000.000"
    assert ui.fmt_idr(600_000.4) == "Rp600.000"


@pytest.mark.parametrize("value, expected", [
    (5_000_000, "Rp5 juta"),
    (1_500_000_000, "Rp1,5 miliar"),
    (3_529_661_665, "Rp3,53 miliar"),
    (441_210_000_000, "Rp441 miliar"),
    (7_760_000_000_000, "Rp7,76 triliun"),
    (-2_500_000_000, "-Rp2,5 miliar"),
    (850_000, "Rp850.000"),
    (200_000_000, "Rp200 juta"),
    (100_000_000_000, "Rp100 miliar"),
])
def test_fmt_idr_short(value, expected):
    assert ui.fmt_idr_short(value) == expected


def test_fmt_pct_and_level_use_decimal_comma():
    assert ui.fmt_pct(-8.84) == "-8,8%"
    assert ui.fmt_pct(4.4, 1, signed=True) == "+4,4%"
    assert ui.fmt_pct(None) == "n/a" and ui.fmt_pct(float("nan")) == "n/a"
    assert ui.fmt_level(4.5) == "4,5" and ui.fmt_level(5.0) == "5"


def test_sequential_ramp_goes_light_to_dark_and_is_valid_hex():
    first, last = ui.sequential(0, 19), ui.sequential(18, 19)
    assert (first, last) == ("#86b6ef", "#184f95")
    assert all(len(ui.sequential(i, 19)) == 7 for i in range(19))
    assert ui.sequential(0, 1) == "#86b6ef"


def test_category_colors_fixed_per_entity_and_differ_by_mode():
    assert ui.category_color("saham", "light") != ui.category_color("pendapatan_tetap", "light")
    assert ui.category_color("saham", "dark") == "#d95926"
    assert ui.category_color("tidak_dikenal", "light") == ui.CATEGORY_COLORS["light"]["other"]


def test_kpi_and_section_escape_html():
    out = ui.kpi("<script>x</script>", "Rp1", "a & b")
    assert "<script>" not in out and "&lt;script&gt;" in out and "a &amp; b" in out
    assert "<small>" not in out
    assert "<small>Moderat</small>" in ui.kpi("Profil", "4,5", unit="Moderat")


PICK = {"product_id": "RD1", "name": "Dana <b>Uji</b>", "return_1y_pct": 4.4, "return_3y_pct": -2.0,
        "drawdown_1y_pct": -33.02, "aum_idr": 9.48e12, "alasan": "dana kelolaan besar", "url": "https://bibit.id/reksadana/RD1"}


def test_product_card_shows_direction_with_arrows_and_escapes_names():
    out = ui.product_card("saham", 0.18, 900_000, [PICK, {**PICK, "name": "Alternatif"}], "light")
    assert "▲ 4,4%" in out and "▼ 2,0%" in out  # direction never relies on colour alone
    assert "&lt;b&gt;Uji" in out and "<b>Uji</b>" not in out
    assert "Rp900.000<small>per bulan</small>" in out and '<span class="pct">18%</span>' in out and "1 alternatif" in out
    assert "33,0%" in out and "Rp9,48 triliun" in out
    assert 'href="https://bibit.id/reksadana/RD1"' in out


def test_product_card_without_alternatives_or_missing_values():
    lone = {**PICK, "drawdown_1y_pct": float("nan"), "alasan": None}
    out = ui.product_card("pasar_uang", 0.12, 600_000, [lone], "dark")
    assert "alternatif" not in out and "skor seimbang" in out and "n/a" in out


def test_risk_meter_status_has_icon_and_label():
    ok = ui.risk_meter(-0.088, 0.10, "light")
    assert "✓ Dalam batas Anda" in ok and "-8,8%" in ok and ui.GOOD in ok
    over = ui.risk_meter(-0.125, 0.10, "light")
    assert "✕ Melewati batas Anda" in over and ui.CRITICAL in over


def test_profile_scale_marks_selected_and_hatches_levels_over_limit():
    levels = [1.0, 1.5, 2.0, 4.5, 5.0, 10.0]
    losses = [-0.04, -0.045, -0.05, -0.088, -0.11, -0.25]
    out = ui.profile_scale(levels, losses, 0.10, 4.5)
    assert "<b>4,5</b><i>▼</i>" in out and out.count("seg off") == 2 and out.count("sel") >= 1
    assert "--n:6" in out and "Konservatif" in out and "Agresif" in out


def test_legend_rows_skip_zero_shares():
    out = ui.legend_rows({"pasar_uang": 0.12, "saham": 0.0}, {"pasar_uang": 600_000}, "light")
    assert "Pasar uang" in out and "Rp600.000" in out and "Saham" not in out


def test_donut_has_one_slice_per_nonzero_category():
    fig = ui.donut({"pasar_uang": 0.12, "pendapatan_tetap": 0.7, "saham": 0.18, "campuran": 0.0}, "Rp5 juta", "per bulan", "light")
    assert list(fig.data[0].labels) == ["Pasar uang", "Obligasi", "Saham"]
    assert sum(fig.data[0].values) == pytest.approx(1.0)


def test_level_chart_keeps_half_step_labels_as_categories():
    levels = [1.0, 1.5, 4.5, 5.0]
    fig = ui.level_chart(levels, [-0.04, -0.045, -0.088, -0.11], 0.10, 4.5, "light")
    assert fig.layout.xaxis.type == "category"  # "4,5" must not be parsed as the number 45
    assert list(fig.data[0].x) == ["1", "1,5", "4,5", "5"]
    colors = list(fig.data[0].marker.color)
    assert colors[0] == ui.BLUE["light"] and colors[3] != ui.BLUE["light"]  # over the limit -> grey


def test_projection_chart_traces_and_selected_emphasis():
    years = list(range(0, 4))
    series = {"Pesimis": [0, 1, 2, 3], "Dasar": [0, 2, 4, 6], "Optimis": [0, 3, 6, 9]}
    fig = ui.projection_chart(years, series, [0, 1, 2, 3], [0, 1, 3, 5], "Dasar", "dark")
    widths = {t.name: t.line.width for t in fig.data if t.name in series}
    assert widths["Dasar"] > widths["Pesimis"] and widths["Dasar"] > widths["Optimis"]
    assert "Total setoran" in [t.name for t in fig.data] and "Dasar (daya beli sekarang)" in [t.name for t in fig.data]


def test_compare_chart_has_two_portfolios_and_four_measures():
    row = {"return_1y_pct": 0.2, "return_3y_pct": 10.9, "return_5y_pct": 23.1, "drawdown_1y_pct": -5.9}
    fig = ui.compare_chart({"Pilihan sistem": row, "Robo Bibit": {**row, "return_1y_pct": -5.3}}, "light")
    assert [t.name for t in fig.data] == ["Pilihan sistem", "Robo Bibit"]
    assert all(len(t.x) == 4 for t in fig.data)


def test_product_scatter_colours_three_categories_and_marks_picks():
    df = pd.DataFrame({
        "name": ["A", "B", "C", "D", "E"], "category": ["pasar_uang", "pendapatan_tetap", "saham", "campuran", "saham"],
        "return_3y_pct": [15, 19, -24, 5, None], "drawdown_1y_pct": [0, 0, -33, -10, -30],
    })
    fig = ui.product_scatter(df, ["A", "C"], "light")
    names = [t.name for t in fig.data]
    assert names == ["Pasar uang", "Obligasi", "Saham", "Lainnya", "Pilihan sistem"]
    assert len(fig.data[2].x) == 1  # the row with a missing 3-year return is dropped, not plotted at 0
    assert list(fig.data[-1].text) == ["A", "C"]


def test_empty_state_and_step_cards():
    out = ui.empty_state("Kosong", "isi data", ["data/a.csv", "data/b.csv"])
    assert "Kosong" in out and out.count("<code>") == 2
    cards = ui.step_cards([("Bulan 1-3", 2_000_000), ("Bulan 4-6", 3_500_000)])
    assert len(cards) == 2 and "Rp2.000.000" in cards[0] and "Rp3.500.000" in cards[1]


def test_projection_chart_with_single_user_line_has_no_scenario_band():
    fig = ui.projection_chart([0, 1, 2], {"Atur sendiri": [0, 1, 2]}, [0, 1, 2], [0, 1, 2], "Atur sendiri", "light")
    assert "Rentang pesimis-optimis" not in [t.name for t in fig.data] and "Atur sendiri" in [t.name for t in fig.data]
