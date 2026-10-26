from datetime import datetime

import pandas as pd
import pytest

from tracker import history, products, recommend, rules


@pytest.fixture(scope="module")
def rec():
    return recommend.recommend(products.load_products(), rules.load_profiles(), 0.10, 25, 5_000_000)


INPUTS = {"horizon_years": 25.0, "monthly_budget": 5_000_000.0, "max_drop_pct": 10, "syariah_only": False, "auto": True}


def test_snapshot_is_json_safe_and_complete(rec):
    import json

    snap = history.snapshot(rec, INPUTS, "2026-10-26", note="  mulai bulan depan ", now=datetime(2026, 10, 26, 9, 0, 0))
    json.dumps(snap)  # raises if a NumPy/NaN value slipped through
    assert snap["note"] == "mulai bulan depan"
    assert snap["profile"] == {"key": rec.profile_key, "level": rec.level, "name": rec.profile_key.rsplit("_", 1)[-1]}
    assert set(snap["picks"]) == set(rec.picks) and all(len(v) == 3 for v in snap["picks"].values())
    assert sum(snap["monthly_amounts"].values()) == pytest.approx(5_000_000)


def test_save_and_list_roundtrip_newest_first(rec, tmp_path):
    a = history.snapshot(rec, INPUTS, "2026-10-26", now=datetime(2026, 10, 26, 9, 0, 0))
    b = history.snapshot(rec, INPUTS, "2026-11-02", now=datetime(2026, 11, 2, 9, 0, 0))
    history.save(a, tmp_path)
    p = history.save(b, tmp_path)
    (tmp_path / "rusak.json").write_text("{bukan json", encoding="utf-8")
    saved = history.list_saved(tmp_path)
    assert p.name == "2026-11-02_090000.json"
    assert [s["data_as_of"] for s in saved] == ["2026-11-02", "2026-10-26"]  # corrupt file skipped
    assert history.list_saved(tmp_path / "belum_ada") == []


def _snap(top_ids, level_key="bibit_4.5_moderat", as_of="2026-10-26"):
    return {
        "saved_at": "2026-10-26T09:00:00", "data_as_of": as_of, "note": "", "inputs": {},
        "profile": {"key": level_key, "level": 4.5, "name": "moderat"},
        "allocation": {"saham": 1.0}, "monthly_amounts": {}, "stress_loss": -0.08, "within_limit": True,
        "picks": {"saham": [{"product_id": i, "name": f"Dana {i}"} for i in top_ids]},
    }


def test_compare_same_changed_and_missing_products():
    catalog = pd.DataFrame({"product_id": ["B", "C", "D"]})
    old, new = _snap(["A", "B", "C"]), _snap(["B", "C", "D"], as_of="2026-11-02")
    [row] = history.compare(old, new, catalog)
    assert row["status"] == "berubah"
    assert row["produk_utama_lama"] == "Dana A" and row["produk_utama_sekarang"] == "Dana B"
    assert row["masih_dijual"] is False and row["peringkat_lama_sekarang"] is None
    notes = history.describe_changes(old, new, [row])
    assert any("tidak dijual" in n for n in notes) and any("Data produk berbeda" in n for n in notes)


def test_compare_old_top_still_ranked_and_unchanged():
    catalog = pd.DataFrame({"product_id": ["A", "B"]})
    [row] = history.compare(_snap(["A", "B"]), _snap(["B", "A"]), catalog)
    assert row["status"] == "berubah" and row["peringkat_lama_sekarang"] == 2 and row["masih_dijual"] is True
    [same] = history.compare(_snap(["A", "B"]), _snap(["A", "B"]), catalog)
    assert same["status"] == "sama"
    assert history.describe_changes(_snap(["A"]), _snap(["A"]), [same]) == [
        "Tidak ada perubahan pada produk utama maupun profil risiko."]


def test_describe_changes_flags_profile_shift():
    old, new = _snap(["A"]), _snap(["A"], level_key="bibit_4_konservatif")
    new["profile"]["level"] = 4.0
    notes = history.describe_changes(old, new, history.compare(old, new))
    assert notes[0] == "Profil risiko berubah dari 4.5 ke 4."
