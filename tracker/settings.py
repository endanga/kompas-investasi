"""Deployment settings, read from environment variables first and Streamlit secrets second.

Nothing here is required locally: with no settings the app keeps using the CSV/JSON files in data/ exactly as before.
"""
from __future__ import annotations

import os

ENV_DB = "KOMPAS_DATABASE_URL"
ENV_CLOUD = "KOMPAS_CLOUD"
ENV_PASSWORD = "KOMPAS_PASSWORD"
TRUE_WORDS = {"1", "true", "yes", "ya"}


def _secret(*path: str):
    """Nested value from .streamlit/secrets.toml, or None when there is no secrets file or the key is absent."""
    try:
        import streamlit as st

        node = st.secrets
        for part in path:
            node = node[part]
        return node
    except Exception:  # no secrets file, missing key, or Streamlit not running (tests)
        return None


def normalise_url(url: str) -> str:
    """Accept the plain 'postgresql://' / 'postgres://' strings that Supabase and Neon show, and pick the psycopg 3 driver."""
    url = url.strip()
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def database_url() -> str | None:
    """SQLAlchemy URL of the database holding the user's own data, or None to use local files."""
    url = os.environ.get(ENV_DB) or _secret("database", "url")
    return normalise_url(str(url)) if url else None


def cloud_mode() -> bool:
    """True on a hosted deployment: the product refresh needs a local browser, so it is switched off there."""
    flag = os.environ.get(ENV_CLOUD) or _secret("app", "cloud")
    return flag is not None and str(flag).strip().lower() in TRUE_WORDS


def app_password() -> str | None:
    pw = os.environ.get(ENV_PASSWORD) or _secret("app", "password")
    return str(pw) if pw else None
