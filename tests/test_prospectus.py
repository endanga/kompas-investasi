"""Prospectus reader: checked against the real 2025 portfolio tables of three bond funds (text excerpts under tests/fixtures)."""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from tracker import factsheet, prospectus as P, products, refresh, ui

FIX = Path(__file__).parent / "fixtures"


def rows_of(slug):
    return (FIX / f"prospektus_{slug}_2025_rows.txt").read_text(encoding="utf-8").splitlines()


def policy_of(slug):
    return (FIX / f"prospektus_{slug}_policy.txt").read_text(encoding="utf-8")


# ---- the real tables, reconciled against each document's own 'Jumlah' line
@pytest.mark.parametrize("slug, reported, gov, corp, grade", [
    ("manulife_obligasi_unggulan", 81.86, 68.24, 13.44, 13.44),
    ("danamas_stabil", 66.88, 8.64, 58.24, 54.92),
    ("trimegah_dana_tetap_syariah", 95.50, 44.94, 50.56, 50.56),
])
def test_the_parsed_table_matches_the_total_printed_in_the_document(slug, reported, gov, corp, grade):
    out = P.summarize(rows_of(slug))
    assert out["reconciled"] and out["reported_total_pct"] == reported
    assert abs(out["parsed_pct"] - reported) <= P.RECONCILE_TOLERANCE
    assert out["position_date"] == date(2025, 12, 31)
    assert (out["gov_pct"], out["corp_pct"], out["investment_grade_pct"]) == (gov, corp, grade)


def test_exact_match_on_two_of_the_three_documents():
    assert P.summarize(rows_of("danamas_stabil"))["parsed_pct"] == 66.88
    assert P.summarize(rows_of("trimegah_dana_tetap_syariah"))["parsed_pct"] == 95.50      # needed 3-decimal and '-' coupons


def test_government_and_corporate_split_adds_up_to_what_was_read():
    for slug in ("manulife_obligasi_unggulan", "danamas_stabil", "trimegah_dana_tetap_syariah"):
        out = P.summarize(rows_of(slug))
        assert out["gov_pct"] + out["corp_pct"] == pytest.approx(out["covered_pct"], abs=0.02)
        assert sum(out["ratings"].values()) == pytest.approx(out["corp_pct"], abs=0.02)


def test_first_manulife_row_is_read_field_by_field():
    first = P.parse_rows(rows_of("manulife_obligasi_unggulan"))["bonds"][0]
    assert first["gov"] and first["rating"] is None and first["pct"] == 6.13
    assert first["nominal"] == 756_000_000_000 and first["maturity"] == date(2031, 5, 15) and first["year"] == "2025"


def test_the_prior_year_table_is_not_mixed_in():
    for slug in ("manulife_obligasi_unggulan", "danamas_stabil", "trimegah_dana_tetap_syariah"):
        assert {b["year"] for b in P.parse_rows(rows_of(slug))["bonds"]} == {"2025"}


def test_rating_spread_and_the_rating_that_could_not_be_read_are_kept_apart():
    danamas = P.summarize(rows_of("danamas_stabil"))
    assert danamas["ratings"]["A"] == 33.73 and danamas["ratings"]["AA"] == 16.8 and danamas["ratings"]["AAA"] == 4.39
    assert danamas["ratings"]["spekulatif"] == 2.63 and danamas["unrated_pct"] == 0.69        # not folded into 'investment grade'
    assert danamas["investment_grade_pct"] == pytest.approx(33.73 + 16.8 + 4.39, abs=0.02)


def test_weighted_time_to_maturity_is_a_plain_average_of_the_dates_not_a_duration():
    out = P.summarize(rows_of("trimegah_dana_tetap_syariah"))
    bonds = P.parse_rows(rows_of("trimegah_dana_tetap_syariah"))["bonds"]
    by_hand = sum(b["pct"] * (b["maturity"] - date(2025, 12, 31)).days / 365.25 for b in bonds) / sum(b["pct"] for b in bonds)
    assert out["wam_years"] == pytest.approx(by_hand, abs=0.01) and 2 < out["wam_years"] < 4


# ---- a parse that does not add up reports nothing
def test_missing_rows_make_the_whole_summary_unreported_instead_of_partial():
    rows = rows_of("danamas_stabil")
    kept, dropped = [], 0
    for r in rows:
        if P._ROW.search(r.replace(" | ", " ")) and dropped < 12:
            dropped += 1
            continue
        kept.append(r)
    out = P.summarize(kept)
    assert not out["reconciled"] and out["gov_pct"] is None and out["corp_pct"] is None and out["wam_years"] is None
    assert out["parsed_pct"] < out["reported_total_pct"] - P.RECONCILE_TOLERANCE


def test_without_the_documents_own_total_nothing_is_reported():
    rows = [r for r in rows_of("manulife_obligasi_unggulan") if not r.replace(" | ", " ").startswith("Jumlah")]
    out = P.summarize(rows)
    assert not out["reconciled"] and out["gov_pct"] is None and out["reported_total_pct"] is None


def test_text_without_a_portfolio_table_is_unreadable_not_empty_of_risk():
    out = P.summarize(["Kebijakan Investasi", "minimum 80% dan maksimum 100%", "4. Portofolio Efek adalah kumpulan Efek"])
    assert out["n_bonds"] == 0 and not out["reconciled"] and out["gov_pct"] is None


def test_a_glossary_sentence_is_not_mistaken_for_the_table_heading():
    assert not P._TABLE_START.match("Portofolio Efek adalah kumpulan Efek yang merupakan kekayaan")
    assert P._TABLE_START.match("4. Portofolio Efek")
    assert P._TABLE_START.match("4. Portofolio Efek 4. Investment Portfolios")


# ---- ratings
@pytest.mark.parametrize("token, grade", [("idAAA", "AAA"), ("AAA(idn)", "AAA"), ("irAA", "AA"), ("idA+", "A+"), ("idA+(sy)", "A+"),
                                          ("idAA(sy)", "AA"), ("idBBB-", "BBB-"), ("idB", "B"), ("A(idn)", "A")])
def test_rating_cells_are_read(token, grade):
    assert P.rating_token(token) == grade


@pytest.mark.parametrize("token", ["A", "B", "C", "D", "-", "Level", "2025", "Seri", "", None, "AAAA"])
def test_a_series_letter_or_other_text_is_never_taken_for_a_rating(token):
    assert P.rating_token(token) is None


def test_rating_buckets():
    assert [P.rating_bucket(t) for t in ("idAAA", "irAA", "idA+", "idBBB", "idBB+", "idB", None)] == [
        "AAA", "AA", "A", "BBB", "spekulatif", "spekulatif", "tanpa peringkat terbaca"]


# ---- policy quotes stay verbatim
def test_policy_limits_are_quoted_from_the_document():
    manulife = P.policy_quotes(policy_of("manulife_obligasi_unggulan"))
    assert any("maksimum 60%" in q and "badan hukum Indonesia" in q for q in manulife)
    assert any("peringkat investasi" in q and "minimum 40%" in q for q in manulife)
    danamas = P.policy_quotes(policy_of("danamas_stabil"))
    assert any("minimum sebesar 80%" in q for q in danamas)                      # 'sebesar' wording
    trimegah = P.policy_quotes(policy_of("trimegah_dana_tetap_syariah"))
    assert any("peringkat layak investasi paling rendah idAA" in q for q in trimegah)


def test_policy_quotes_do_not_exceed_the_limit_and_stay_inside_the_text():
    text = policy_of("manulife_obligasi_unggulan")
    flat = " ".join(text.split())
    quotes = P.policy_quotes(text, limit=2)
    assert len(quotes) <= 3 and all(q in flat for q in quotes)


# ---- choosing the newest document
@pytest.mark.parametrize("names, newest", [
    (["PR_Manulife Obligasi Unggulan_29_JANUARY_2018.pdf", "Manulife_Obligasi_Unggulan_Kelas_A_2020.pdf",
      "Prospektus_Manulife_Obligasi_Unggulan_Juli_2026.pdf"], "Prospektus_Manulife_Obligasi_Unggulan_Juli_2026.pdf"),
    (["pembaharuan_prospektus_trimegah_dana_tetap_syariah_030524_1.pdf", "Prospektus_Trimegah_Dana_Tetap_Syariah_Maret_2025.pdf",
      "Prospektus_Trimegah_Dana_Tetap_Syariah_Agustus_2025.pdf", "Prospektus_Trimegah_Dana_Tetap_Syariah_Februari_2026.pdf",
      "Prospektus_Trimegah_Dana_Tetap_Syariah_Maret_2026.pdf"], "Prospektus_Trimegah_Dana_Tetap_Syariah_Maret_2026.pdf"),
    (["Pembaharuan_Prospektus_RD_ABF_IBI_Fund.pdf", "ABF_Indonesia_Bond_Index_Fund_Maret_2026.pdf"], "ABF_Indonesia_Bond_Index_Fund_Maret_2026.pdf"),
    (["RD_DANAMAS_STABIL_Mei_2021.pdf", "Prospektus_DANAMAS_STABIL_Mei_2026.pdf", "Danamas_Stabil_2019.pdf"], "Prospektus_DANAMAS_STABIL_Mei_2026.pdf"),
])
def test_the_newest_prospectus_is_chosen_from_its_file_name(names, newest):
    assert P.pick_latest([{"name": n, "file": f"u/{n}"} for n in names])["name"] == newest


def test_name_dates_and_empty_lists():
    assert P._name_date("pembaharuan_prospektus_x_030524_1.pdf") == (2024, 5)
    assert P._name_date("Prospektus_X_Juli_2026.pdf") == (2026, 7)
    assert P._name_date("no date here.pdf") == (0, 0)
    assert P.pick_latest([]) is None


# ---- cache: a big PDF is fetched again only when the newest file changes
def test_the_cache_avoids_downloading_an_unchanged_prospectus(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, timeout=60):
        calls.append(url)
        if url.startswith("https://api.bibit.id"):
            return json.dumps({"data": [{"name": "P_Maret_2026.pdf", "file": "https://x/P_Maret_2026.pdf"}]}).encode()
        return b"%PDF-fake"

    monkeypatch.setattr(factsheet, "_get", fake_get)
    pdf, meta = P.fetch_latest("RD1", tmp_path, log=lambda *_: None)
    assert pdf == b"%PDF-fake" and not meta["cached"]
    downloads = [c for c in calls if c.endswith(".pdf")]
    pdf2, meta2 = P.fetch_latest("RD1", tmp_path, log=lambda *_: None)
    assert meta2["cached"] and [c for c in calls if c.endswith(".pdf")] == downloads        # no second download

    def newer(url, timeout=60):
        if url.startswith("https://api.bibit.id"):
            return json.dumps({"data": [{"name": "P_Juni_2026.pdf", "file": "https://x/P_Juni_2026.pdf"}]}).encode()
        calls.append(url)
        return b"%PDF-newer"

    monkeypatch.setattr(factsheet, "_get", newer)
    pdf3, meta3 = P.fetch_latest("RD1", tmp_path, log=lambda *_: None)
    assert pdf3 == b"%PDF-newer" and not meta3["cached"]


def test_a_fund_without_any_prospectus_is_an_error_not_an_empty_success(tmp_path, monkeypatch):
    monkeypatch.setattr(factsheet, "_get", lambda url, timeout=60: json.dumps({"data": []}).encode())
    with pytest.raises(ValueError, match="belum ada prospektus"):
        P.fetch_latest("RD9", tmp_path, log=lambda *_: None)


# ---- the refresh command
def _facts(**over):
    base = {"file": "P.pdf", "url": "u/P.pdf", "position_date": date(2025, 12, 31), "n_bonds": 50, "parsed_pct": 80.0,
            "reported_total_pct": 80.0, "reconciled": True, "covered_pct": 80.0, "gov_pct": 50.0, "corp_pct": 30.0,
            "investment_grade_pct": 28.0, "unrated_pct": 0.5, "wam_years": 4.0, "ratings": {"AAA": 28.0}, "policy": ["minimum 0% ..."],
            "fetched": "2026-10-27"}
    return {**base, **over}


@pytest.fixture
def bond_funds(tmp_path, monkeypatch):
    funds = pd.DataFrame({"product_id": ["RD1", "RD2", "RD3"], "name": ["A", "B", "C"],
                          "category": ["pendapatan_tetap", "pendapatan_tetap", "saham"]})
    monkeypatch.setitem(refresh.FILES, "funds", tmp_path / "products.csv")
    funds.to_csv(tmp_path / "products.csv", index=False)
    monkeypatch.setattr(refresh, "PROSPECTUS_FILE", tmp_path / "prospectus.csv")
    return tmp_path


def test_only_bond_funds_are_read_and_the_file_is_written(bond_funds, monkeypatch):
    seen = []
    monkeypatch.setattr(refresh.prospectus, "read_fund", lambda code, **kw: seen.append(code) or _facts())
    out, warnings = refresh.run_prospectus(log=lambda *_: None)
    assert seen == ["RD1", "RD2"] and not warnings and len(out) == 2
    saved = pd.read_csv(bond_funds / "prospectus.csv")
    assert list(saved.columns) == refresh.PROSPECTUS_COLUMNS and saved["position_date"].tolist() == ["2025-12-31"] * 2
    assert json.loads(saved["ratings"][0]) == {"AAA": 28.0}


def test_a_failing_fund_keeps_its_previous_row_and_is_named(bond_funds, monkeypatch):
    monkeypatch.setattr(refresh.prospectus, "read_fund", lambda code, **kw: _facts())
    refresh.run_prospectus(log=lambda *_: None)

    def flaky(code, **kw):
        if code == "RD2":
            raise RuntimeError("unduhan gagal")
        return _facts(gov_pct=60.0)

    monkeypatch.setattr(refresh.prospectus, "read_fund", flaky)
    out, warnings = refresh.run_prospectus(log=lambda *_: None)
    by_id = out.set_index("product_id")
    assert by_id.loc["RD1", "gov_pct"] == 60.0 and by_id.loc["RD2", "gov_pct"] == 50.0      # RD2 kept its old figures
    assert len(warnings) == 1 and "B" in warnings[0] and "unduhan gagal" in warnings[0]


def test_summary_says_which_funds_could_not_be_read_fully(bond_funds, monkeypatch):
    monkeypatch.setattr(refresh.prospectus, "read_fund",
                        lambda code, **kw: _facts() if code == "RD1" else _facts(reconciled=False, gov_pct=None, corp_pct=None))
    text = refresh.prospectus_summary(*refresh.run_prospectus(log=lambda *_: None))
    assert "cocok dengan total di dokumen untuk 1" in text and "belum terbaca utuh" in text and "B" in text
    assert "akhir tahun buku" in text


def test_the_command_needs_the_product_file(tmp_path, monkeypatch):
    monkeypatch.setitem(refresh.FILES, "funds", tmp_path / "missing.csv")
    with pytest.raises(RuntimeError, match="products.csv"):
        refresh.run_prospectus(log=lambda *_: None)


# ---- loading and showing it
def test_prospectus_facts_are_attached_to_the_product_table(tmp_path, monkeypatch):
    pros = pd.DataFrame([{"product_id": "RD3206", "gov_pct": 68.24, "corp_pct": 13.44, "reconciled": True, "position_date": "2025-12-31"}])
    pros.to_csv(tmp_path / "prospectus.csv", index=False)
    monkeypatch.setattr(products, "PROSPECTUS_FILE", tmp_path / "prospectus.csv")
    df = products.load_products()
    row = df[df["product_id"] == "RD3206"].iloc[0]
    assert row["pros_gov_pct"] == 68.24 and bool(row["pros_reconciled"])
    assert len(df) == len(pd.read_csv(products.PRODUCTS_FILE))                        # a join must never add or drop funds


@pytest.mark.parametrize("content", ["", "garbage,,,\n1,2", "other_column\n1\n"])
def test_a_missing_or_broken_prospectus_file_never_stops_the_app(tmp_path, monkeypatch, content):
    f = tmp_path / "prospectus.csv"
    f.write_text(content, encoding="utf-8")
    monkeypatch.setattr(products, "PROSPECTUS_FILE", f)
    assert products.load_prospectus() is None and len(products.load_products()) > 100
    monkeypatch.setattr(products, "PROSPECTUS_FILE", tmp_path / "not_there.csv")
    assert products.load_prospectus() is None


CARD = {"name": "X", "url": "", "aum_idr": 2e11, "return_1y_pct": 4.0, "return_3y_pct": 18.0, "drawdown_1y_pct": -1.0,
        "gov_top10_pct": 100.0, "top10_sum_pct": 50.0}


def test_card_shows_the_prospectus_mix_with_its_date_and_what_it_is_not():
    card = ui.product_card("pendapatan_tetap", 0.5, 1e6, [{**CARD, "pros_reconciled": True, "pros_gov_pct": 68.2, "pros_corp_pct": 13.4,
                                                          "pros_investment_grade_pct": 13.4, "pros_wam_years": 4.1,
                                                          "pros_position_date": "2025-12-31"}], "light")
    assert "Menurut prospektus" in card and "posisi 2025-12-31" in card and "negara 68%" in card and "korporasi 13%" in card
    assert "13% layak investasi" in card and "bukan durasi" in card and "seluruh portofolio efek" in card


def test_card_stays_silent_about_a_prospectus_that_did_not_reconcile():
    for extra in ({}, {"pros_reconciled": False, "pros_gov_pct": 10.0, "pros_corp_pct": 80.0, "pros_investment_grade_pct": 80.0},
                  {"pros_reconciled": float("nan")}):
        assert "Menurut prospektus" not in ui.product_card("pendapatan_tetap", 0.5, 1e6, [{**CARD, **extra}], "light")
