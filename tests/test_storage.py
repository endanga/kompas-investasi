import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tracker import history, migrate, portfolio_io, robo, settings, storage

ROOT = Path(__file__).parent.parent
H = pd.DataFrame([("Danamas Stabil", "pendapatan_tetap", 3_000_000.0), ("TRIM Kas 2 Kelas A", "pasar_uang", 1_000_000.0)],
                 columns=portfolio_io.HOLDINGS_COLS)
T = pd.DataFrame([("2026-09-05", "Danamas Stabil", "pendapatan_tetap", "BUY", 500_000.0)], columns=portfolio_io.TX_COLS)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Point the app at a throwaway SQLite database through the same setting a deployment uses."""
    url = f"sqlite:///{(tmp_path / 'kompas.db').as_posix()}"
    monkeypatch.setenv(settings.ENV_DB, url)
    storage._store_for.cache_clear()
    yield storage.current()
    storage._store_for.cache_clear()


def test_url_normalisation_accepts_supabase_style_strings():
    assert settings.normalise_url("postgresql://u:p@h:6543/postgres") == "postgresql+psycopg://u:p@h:6543/postgres"
    assert settings.normalise_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert settings.normalise_url("sqlite:///x.db") == "sqlite:///x.db"


def test_no_database_configured_means_local_files(monkeypatch):
    monkeypatch.delenv(settings.ENV_DB, raising=False)
    assert storage.current() is None and "File lokal" in storage.describe()


def test_holdings_and_transactions_roundtrip_and_replace(db):
    db.write_holdings(H)
    db.write_transactions(T)
    assert db.read_holdings().to_dict("records") == sorted(H.to_dict("records"), key=lambda r: r["product"])
    assert db.read_transactions().iloc[0].to_dict() == {**T.iloc[0].to_dict()}
    db.write_holdings(H.head(1))
    assert len(db.read_holdings()) == 1
    db.write_holdings(H.head(0))
    assert db.read_holdings().empty and db.read_transactions().shape[0] == 1


def test_portfolio_io_uses_the_database_when_configured(db):
    portfolio_io.save(H, T)
    holdings, tx = portfolio_io.read_current()
    assert len(holdings) == 2 and len(tx) == 1
    real = ROOT / "data" / "holdings.csv"
    assert not real.exists() or "Danamas" not in real.read_text(encoding="utf-8")  # real files untouched
    portfolio_io.ensure_files()  # must not create files when a database is in use


def test_saved_recommendations_roundtrip_newest_first(db):
    snap = {"saved_at": "2026-10-26T09:00:00", "data_as_of": "2026-10-26", "note": "", "profile": {"level": 4.5}}
    newer = {**snap, "saved_at": "2026-11-02T09:00:00"}
    p1 = history.save(snap)
    p2 = history.save(newer)
    assert p1.name == "2026-10-26_090000.json" and p2.name == "2026-11-02_090000.json"
    listed = history.list_saved()
    assert [s["_file"] for s in listed] == [p2.name, p1.name] and listed[0]["saved_at"] == newer["saved_at"]
    history.save(newer)  # same save time replaces, never duplicates
    assert len(history.list_saved()) == 2


def test_robo_entries_roundtrip(db):
    robo.save_entry(4.5, {"pasar_uang": "A", "saham": robo.SKIP}, "2026-10-26", now=datetime(2026, 10, 26, 9, 0))
    loaded = robo.load()
    assert loaded[0]["picks"] == {"pasar_uang": "A"} and robo.resolve(4.5, loaded)[1]["source"] == "input"


def test_migrate_copies_files_and_is_safe_to_repeat(tmp_path):
    src = tmp_path / "data"
    (src / "recommendations").mkdir(parents=True)
    H.to_csv(src / "holdings.csv", index=False)
    T.to_csv(src / "transactions.csv", index=False)
    (src / "recommendations" / "2026-10-26_090000.json").write_text(
        json.dumps({"saved_at": "2026-10-26T09:00:00", "data_as_of": "2026-10-26"}), encoding="utf-8")
    robo.save_entry(5.0, {"saham": "X"}, "2026-10-26", path=src / "robo_picks.json", now=datetime(2026, 10, 26, 9, 0))
    store = storage.SqlStore(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    assert migrate.migrate(store, src, dry_run=True)["holdings"] == 2 and store.read_holdings().empty
    counts = migrate.migrate(store, src)
    assert counts == {"holdings": 2, "transactions": 1, "recommendations": 1, "robo_picks": 1}
    with pytest.raises(RuntimeError, match="sudah berisi"):
        migrate.migrate(store, src)  # would overwrite the portfolio already there
    migrate.migrate(store, src, force=True)
    assert len(store.list_robo()) == 1 and len(store.list_recommendations()) == 1  # no duplicates after a repeat


def _app(monkeypatch, tmp_path, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()


def test_app_runs_on_a_database_and_shows_where_data_lives(db, monkeypatch, tmp_path):
    db.write_holdings(H)
    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    assert any("Database SQLite" in c.value for c in at.sidebar.caption)


def test_cloud_mode_replaces_refresh_button_with_instructions(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path, **{settings.ENV_CLOUD: "true"})
    assert not at.exception
    assert not [b for b in at.sidebar.button if b.label == "Perbarui data produk"]
    assert any("python -m tracker.refresh" in m.value for m in at.sidebar.markdown)


def test_password_gate_blocks_until_correct(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path, **{settings.ENV_PASSWORD: "rahasia"})
    assert not at.exception and not at.tabs  # the app itself is not rendered
    at.text_input(key="app_pw").set_value("salah").run()
    assert any("salah" in e.value for e in at.error) and not at.tabs
    at.text_input(key="app_pw").set_value("rahasia").run()
    assert at.tabs and not at.exception
