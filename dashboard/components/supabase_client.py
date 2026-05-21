"""Lightweight Supabase REST client using httpx.

Why httpx instead of supabase-py: supabase-py 2.30 pulls in heavy
native-code dependencies (cryptography 48, pyroaring, pyiceberg) that
don't always build on Streamlit Cloud's Python 3.13 wheel cache —
broke the Cloud build the last time we tried. httpx is already a
core dependency for ~everything else, so this adds zero new packages.

Returns helpful sentinels:
  • supabase_configured() — True iff URL + key are both set
  • insert(table, row)     — True on success
  • select(table, ...)     — list of dicts, or [] on error/no rows

Callers should also call supabase_configured() to disambiguate
"no rows returned" from "Supabase isn't reachable".

Table schema lives in scripts/supabase_schema.sql.
"""

from __future__ import annotations

from typing import Optional

import httpx
import streamlit as st


def _secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, default)
    except (FileNotFoundError, AttributeError):
        return default


def _config() -> tuple[Optional[str], Optional[str]]:
    """Return (url, key) — both stripped/normalised. Either may be None
    if the secrets aren't set yet."""
    url = (_secret("SUPABASE_URL", "") or "").rstrip("/")
    key = (_secret("SUPABASE_SERVICE_KEY", "") or "").strip()
    return (url or None), (key or None)


def supabase_configured() -> bool:
    """Cheap check used by callers (and the admin UI) to decide whether
    to write to / read from Supabase or fall back to local JSONL."""
    url, key = _config()
    return bool(url and key)


def _headers(key: str, prefer: str = "") -> dict:
    h = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def insert(table: str, row: dict, timeout: float = 5.0) -> bool:
    """POST one row. Returns True iff Supabase accepted the write."""
    url, key = _config()
    if not url or not key:
        return False
    try:
        r = httpx.post(
            f"{url}/rest/v1/{table}",
            json=row,
            headers=_headers(key, prefer="return=minimal"),
            timeout=timeout,
        )
        return r.status_code in (200, 201, 204)
    except Exception:
        return False


def select(
    table:   str,
    columns: str = "*",
    order:   str = "ts.desc",
    limit:   int = 10000,
    timeout: float = 10.0,
) -> list[dict]:
    """SELECT rows. Returns [] on error or empty result. Use
    supabase_configured() upstream to disambiguate."""
    url, key = _config()
    if not url or not key:
        return []
    try:
        r = httpx.get(
            f"{url}/rest/v1/{table}",
            params={"select": columns, "order": order, "limit": limit},
            headers=_headers(key),
            timeout=timeout,
        )
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
        return []
    except Exception:
        return []
