"""Keep every test away from the developer's real settings: no secrets file, no database URL, no cloud flag, no password.

Without this, a local .streamlit/secrets.toml (which points the app at the real database) would make tests read, and
potentially write, the user's own data. Tests that need a database set their own URL explicitly (see test_storage.py).
"""
import pytest

from tracker import settings, storage


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch):
    monkeypatch.setattr(settings, "_secret", lambda *path: None)
    for name in (settings.ENV_DB, settings.ENV_CLOUD, settings.ENV_PASSWORD):
        monkeypatch.delenv(name, raising=False)
    storage._store_for.cache_clear()
    yield
    storage._store_for.cache_clear()
