"""Final audit: room under the loss limit, level comparison, and honesty of the wording."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tracker import metrics, recommend, rules, ui

ROOT = Path(__file__).parent.parent
PROFILES = rules.load_profiles()
LEVELS = sorted((recommend.level_of(k), k) for k in PROFILES if recommend.level_of(k) is not None)


# ---- margin
def test_margin_in_points_and_rupiah():
    m = metrics.margin_to_limit(-0.0992, 0.10, 100_000_000)
    assert m["points"] == pytest.approx(0.08) and m["rupiah"] == pytest.approx(80_000) and m["thin"] and not m["crossed"]


def test_margin_crossed_and_comfortable():
    over = metrics.margin_to_limit(-0.128, 0.10, 60_000_000)
    assert over["crossed"] and not over["thin"] and over["points"] == pytest.approx(-2.8) and over["rupiah"] == pytest.approx(-1_680_000)
    ok = metrics.margin_to_limit(-0.0809, 0.10, 100_000_000)
    assert not ok["thin"] and not ok["crossed"] and ok["points"] == pytest.approx(1.91)


def test_margin_exactly_at_the_limit_is_not_called_crossed():
    m = metrics.margin_to_limit(-0.10, 0.10, 1_000_000)
    assert not m["crossed"] and m["thin"] and m["points"] == pytest.approx(0.0, abs=1e-9)


def test_thin_margin_note_warns_shows_points_rupiah_and_the_lower_level():
    text, warn = ui.margin_note(-0.0992, 0.10, 60_000_000, "setoran 12 bulan", 4.5, (4.0, -0.0809))
    assert warn and "+0.08 poin" in text and "Rp" in text and "sangat tipis" in text
    assert "Level 4" in text and "+1.91 poin" in text


def test_comfortable_margin_note_is_not_a_warning_and_never_promises_safety():
    text, warn = ui.margin_note(-0.0809, 0.10, 60_000_000, "setoran 12 bulan", 4.0, (3.5, -0.0702))
    assert not warn
    assert not any(word in text.lower() for word in ("dijamin", "pasti aman", "tidak akan rugi", "maksimum"))


def test_crossed_margin_note_is_a_warning():
    text, warn = ui.margin_note(-0.128, 0.10, 60_000_000, "setoran 12 bulan", 4.5, None)
    assert warn and "melewati batas" in text


def test_app_shows_the_room_under_the_limit():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception
    notes = [w.value for w in at.warning] + [c.value for c in at.caption]
    assert any("Ruang terhadap batas 10%" in n and "poin" in n for n in notes)


# ---- comparing neighbouring levels on risk, not on ranking score
@pytest.mark.parametrize("shocks", [metrics.crisis_shocks(40, 8), metrics.crisis_shocks(30, 3), metrics.crisis_shocks(50, 12),
                                    metrics.DEFAULT_SHOCKS])
def test_higher_level_never_loses_less_under_the_same_shocks(shocks):
    losses = [metrics.stress_loss(PROFILES[k], shocks) for _, k in LEVELS]
    assert losses == sorted(losses, reverse=True)                      # level up, loss never smaller


def test_stock_scenario_follows_the_level_but_bond_scenarios_follow_the_bond_weight():
    """A riskier level has more stock, but not always more bonds: a bond-only scenario can hurt a 'safer' level more."""
    def loss(key, name, gov):
        return next(s["loss"] for s in metrics.scenario_losses(PROFILES[key], gov) if s["name"] == name)

    for gov in (0.0, 0.5, 1.0):
        for (_, a), (_, b) in zip(LEVELS, LEVELS[1:]):
            assert loss(b, "Saham jatuh", gov) <= loss(a, "Saham jatuh", gov) + 1e-12
    default = "Gagal bayar penerbit korporasi besar"
    by_bond_weight = sorted(LEVELS, key=lambda lk: -PROFILES[lk[1]].get("pendapatan_tetap", 0.0))
    losses = [loss(k, default, 0.0) for _, k in by_bond_weight]
    assert losses == sorted(losses)                                      # more bonds, bigger corporate-default loss


def test_level_4_5_breaks_the_default_crisis_while_level_4_stays_closer():
    shocks = metrics.crisis_shocks(40, 8)
    loss = {lv: metrics.stress_loss(PROFILES[k], shocks) for lv, k in LEVELS if lv in (3.5, 4.0, 4.5)}
    assert loss[4.5] == pytest.approx(-0.128) and -loss[4.5] > 0.10
    assert loss[3.5] > loss[4.0] > loss[4.5]


def test_heavier_scenarios_move_the_reported_loss_but_not_the_ordering_of_levels():
    for scale in (1.0, 1.5, 2.0):
        ordered = [min(s["loss"] for s in metrics.scenario_losses(PROFILES[k], 1.0, scale=scale)) for _, k in LEVELS]
        assert ordered == sorted(ordered, reverse=True)


# ---- the chosen level depends on small data differences: say so in code, not only in prose
def test_breakeven_shock_is_what_decides_the_level():
    a = PROFILES[next(k for lv, k in LEVELS if lv == 4.5)]
    bond_shock, stock_shock = 0.0499, 0.357
    stock_break = (0.10 - bond_shock * a["pendapatan_tetap"]) / a["saham"]
    bond_break = (0.10 - stock_shock * a["saham"]) / a["pendapatan_tetap"]
    assert stock_break - stock_shock < 0.005                               # under half a point of stock shock
    assert bond_break - bond_shock < 0.0015                                # about a tenth of a point of bond shock
