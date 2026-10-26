from datetime import datetime

import pandas as pd

from tracker import robo

CATALOG = pd.DataFrame({"name": ["A", "B", "C"], "category": ["pasar_uang", "pendapatan_tetap", "saham"]})


def test_save_and_latest_entry_wins_and_skips_dropped_categories(tmp_path):
    f = tmp_path / "robo.json"
    robo.save_entry(4.5, {"pasar_uang": "A", "saham": robo.SKIP}, "2026-10-26", f, datetime(2026, 10, 26, 9, 0))
    robo.save_entry(4.5, {"pasar_uang": "B"}, "2026-11-02", f, datetime(2026, 11, 2, 9, 0))
    robo.save_entry(7.0, {"saham": "C"}, "2026-11-02", f, datetime(2026, 11, 2, 9, 5))
    entries = robo.load(f)
    assert len(entries) == 3 and robo.latest(4.5, entries)["picks"] == {"pasar_uang": "B"}
    assert robo.latest(7.0, entries)["picks"] == {"saham": "C"} and robo.latest(1.0, entries) is None


def test_load_survives_missing_or_corrupt_file(tmp_path):
    assert robo.load(tmp_path / "nope.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{bukan json", encoding="utf-8")
    assert robo.load(bad) == []


def test_resolve_prefers_input_then_screenshot_defaults_then_unverified():
    entries = [{"level": 4.5, "saved_at": "2026-10-26T09:00:00", "data_as_of": "2026-10-26", "picks": {"pasar_uang": "A"}}]
    picks, meta = robo.resolve(4.5, entries)
    assert picks == {"pasar_uang": "A"} and meta["source"] == "input"
    assert robo.resolve(5.0, entries)[1]["source"] == "screenshot"
    assert robo.resolve(8.0, entries)[1]["source"] == "unverified"


def test_stale_and_missing_checks():
    meta = {"source": "input", "data_as_of": "2026-10-26"}
    assert robo.is_stale(meta, "2026-11-02") and not robo.is_stale(meta, "2026-10-26")
    assert not robo.is_stale({"source": "screenshot", "data_as_of": None}, "2026-11-02")
    assert robo.missing_from({"x": "A", "y": "Hilang"}, CATALOG) == ["Hilang"]
    assert list(robo.fund_rows({"pasar_uang": "A", "saham": "Hilang"}, CATALOG)) == ["pasar_uang"]
