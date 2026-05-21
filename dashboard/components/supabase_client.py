"""Supabase client — persistent activity store.

Returns a configured client if SUPABASE_URL + SUPABASE_SERVICE_KEY are
present in Streamlit secrets (Cloud or local .streamlit/secrets.toml).
Returns None otherwise — callers fall back to the local JSONL file.

Why SERVICE_KEY (not ANON):
  • The dashboard runs server-side on Streamlit Cloud — secrets never
    reach the user's browser. SERVICE_KEY can bypass Row Level Security,
    which lets us insert/select without writing RLS policies for a
    private admin-only table.
  • If you wanted the public to read this table, switch to anon + add
    a policy. For now everything's admin-only.

Table schema lives in scripts/supabase_schema.sql.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

try:
    from supabase import create_client, Client
except ImportError:    # supabase package not installed (offline / fresh venv)
    create_client = None
    Client = None


def _secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, default)
    except (FileNotFoundError, AttributeError):
        return default


@st.cache_resource(show_spinner=False)
def get_client() -> Optional["Client"]:
    """Cached Supabase client. None if not configured / package missing."""
    if create_client is None:
        return None
    url = _secret("SUPABASE_URL", "")
    key = _secret("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


def supabase_configured() -> bool:
    """Cheap check used by admin pages to decide which storage backend to
    surface in the UI ('Supabase' vs 'local JSONL fallback')."""
    return get_client() is not None
