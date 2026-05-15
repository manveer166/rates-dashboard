"""Subscriber-tier model.

Hierarchy (low → high access):

    free (0)  <  substack (1)  <  pro (2)  =  founding (3)  <  admin (99)

Founding has the same gate access as Pro — the difference is pricing /
lock-in / perks, not capability.

Storage: data/subscriber_tiers.json — {email_lowercase: tier_string}.
Admin status is derived from ADMIN_PASSWORD elsewhere; admins always
pass any gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

TIER_ORDER = {"free": 0, "substack": 1, "pro": 2, "founding": 3, "admin": 99}
TIER_LABELS = {0: "Free", 1: "Substack", 2: "Pro",
                3: "Founding", 99: "Admin"}

STORE = Path(__file__).parent.parent.parent / "data" / "subscriber_tiers.json"


def _load() -> dict:
    if STORE.exists():
        try:
            data = json.loads(STORE.read_text())
            # Strip the _format_note / _examples keys
            return {k.lower(): v for k, v in data.items()
                    if not k.startswith("_")}
        except Exception:
            return {}
    return {}


def _save(rows: dict) -> None:
    # Preserve the format note + examples block at top
    out = {
        "_format_note": "email (lowercase) -> tier. "
                         "Tiers: substack | pro | founding. "
                         "Admin is set via ADMIN_PASSWORD, not here. "
                         "Free users aren't listed.",
        **{k.lower(): v for k, v in rows.items() if not k.startswith("_")},
    }
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(out, indent=2))


def set_tier(email: str, tier: str) -> None:
    """Assign or update a subscriber's tier."""
    rows = _load()
    rows[email.lower().strip()] = tier
    _save(rows)


def set_tier_bulk(emails: list[str], tier: str) -> int:
    """Bulk-set a tier for many emails. Returns count actually changed."""
    rows = _load()
    changed = 0
    for e in emails:
        e_l = e.lower().strip()
        if rows.get(e_l) != tier:
            rows[e_l] = tier
            changed += 1
    _save(rows)
    return changed


def get_tier_for_email(email: str) -> str:
    """Resolve an email to its tier. Defaults to 'free'."""
    if not email:
        return "free"
    rows = _load()
    return rows.get(email.lower().strip(), "free")


def current_user_tier() -> str:
    """Resolve the currently-logged-in user's tier."""
    if st.session_state.get("site_admin"):
        return "admin"
    email = (st.session_state.get("site_user") or
             st.session_state.get("user_email") or "")
    if "@" in email:
        return get_tier_for_email(email)
    # Logged in via password (no email) — falls back to free
    if st.session_state.get("site_authenticated"):
        return "free"   # viewer-password users are equivalent to free for gating
    return "free"


def tier_at_or_above(required: str) -> bool:
    """True if current user's tier >= required tier."""
    user_t = TIER_ORDER.get(current_user_tier(), 0)
    need_t = TIER_ORDER.get(required, 0)
    return user_t >= need_t


def list_all_subscribers() -> list[dict]:
    """Admin view: every email + their tier, sorted by tier-rank desc."""
    rows = _load()
    out = [{"email": e, "tier": t} for e, t in rows.items()]
    out.sort(key=lambda r: (-TIER_ORDER.get(r["tier"], 0), r["email"]))
    return out
