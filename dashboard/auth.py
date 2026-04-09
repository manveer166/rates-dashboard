"""
auth.py — Lightweight authentication for the Rates Dashboard.

Supports two backends for subscriber management:
  1. Google Sheets (set GOOGLE_SHEETS_CREDENTIALS env var to service account JSON path
     and SUBSCRIBERS_SHEET_ID to the spreadsheet ID)
  2. Local CSV fallback (data/subscribers.csv)

Admin access is controlled by ADMIN_PASSWORD env var.

Tiers:  "free"   — limited pages (Home, Yield Curve, Glossary)
        "premium" — all pages
        "admin"   — all pages + admin panel
"""

import csv
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st

# ── Tier definitions ──────────────────────────────────────────────────────
FREE_PAGES = {"Home", "Yield_Curve", "Glossary", "Feature_Request"}
PREMIUM_PAGES = None  # None = all pages

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "macromanv2024")


# ── Subscriber backend ────────────────────────────────────────────────────

def _csv_path() -> Path:
    return Path(__file__).parent.parent / "data" / "subscribers.csv"


def _ensure_csv():
    p = _csv_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        with open(p, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["email", "password_hash", "tier", "name", "created"])


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _load_subscribers_csv() -> List[Dict]:
    _ensure_csv()
    with open(_csv_path(), "r") as f:
        return list(csv.DictReader(f))


def _save_subscribers_csv(rows: List[Dict]):
    _ensure_csv()
    fields = ["email", "password_hash", "tier", "name", "created"]
    with open(_csv_path(), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _load_subscribers_gsheets() -> Optional[List[Dict]]:
    """Load subscribers from Google Sheets. Returns None if not configured."""
    creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "")
    sheet_id = os.getenv("SUBSCRIBERS_SHEET_ID", "")
    if not creds_path or not sheet_id:
        return None
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        service = build("sheets", "v4", credentials=creds)
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range="Subscribers!A:E"
        ).execute()
        values = result.get("values", [])
        if not values:
            return []
        headers = values[0]
        return [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in values[1:]]
    except Exception:
        return None


def _append_subscriber_gsheets(row: Dict) -> bool:
    """Append a subscriber row to Google Sheets. Returns True on success."""
    creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "")
    sheet_id = os.getenv("SUBSCRIBERS_SHEET_ID", "")
    if not creds_path or not sheet_id:
        return False
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        service = build("sheets", "v4", credentials=creds)
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="Subscribers!A:E",
            valueInputOption="RAW",
            body={"values": [[row["email"], row["password_hash"], row["tier"], row["name"], row["created"]]]},
        ).execute()
        return True
    except Exception:
        return False


def load_subscribers() -> List[Dict]:
    """Load subscribers from Google Sheets, falling back to CSV."""
    gs = _load_subscribers_gsheets()
    if gs is not None:
        return gs
    return _load_subscribers_csv()


def add_subscriber(email: str, password: str, name: str = "", tier: str = "free") -> bool:
    """Register a new subscriber. Returns False if email already exists."""
    subs = load_subscribers()
    if any(s["email"].lower() == email.lower() for s in subs):
        return False
    row = {
        "email": email.lower(),
        "password_hash": _hash_password(password),
        "tier": tier,
        "name": name,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    # Try Google Sheets first
    if not _append_subscriber_gsheets(row):
        # Fallback to CSV
        subs.append(row)
        _save_subscribers_csv(subs)
    return True


def authenticate(email: str, password: str) -> Optional[Dict]:
    """Check credentials. Returns subscriber dict or None."""
    pw_hash = _hash_password(password)
    for s in load_subscribers():
        if s["email"].lower() == email.lower() and s["password_hash"] == pw_hash:
            return s
    return None


# ── Session helpers ───────────────────────────────────────────────────────

def is_logged_in() -> bool:
    return st.session_state.get("auth_user") is not None


def current_user() -> Optional[Dict]:
    return st.session_state.get("auth_user")


def current_tier() -> str:
    user = current_user()
    if user is None:
        return "free"
    return user.get("tier", "free")


def is_admin() -> bool:
    return current_tier() == "admin"


def can_access_page(page_name: str) -> bool:
    """Check if the current user can access a given page."""
    tier = current_tier()
    if tier in ("premium", "admin"):
        return True
    # Free tier: restricted pages
    base = page_name.split("_", 1)[-1] if "_" in page_name else page_name
    return base in FREE_PAGES or page_name in FREE_PAGES


def require_auth(page_name: str = ""):
    """Call at the top of a page to enforce access control.
    Returns True if access is granted, False if blocked."""
    auth_enabled = os.getenv("AUTH_ENABLED", "false").lower() == "true"
    if not auth_enabled:
        return True
    if not is_logged_in():
        login_form()
        return False
    if page_name and not can_access_page(page_name):
        st.warning("This page requires a premium subscription.")
        st.link_button("Subscribe to Macro Manv", "https://manveersahota.substack.com/subscribe")
        return False
    return True


def login_form():
    """Render login / register tabs."""
    st.markdown("### Sign In")
    tab_login, tab_register = st.tabs(["Log In", "Register"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log In", use_container_width=True):
                user = authenticate(email, password)
                if user:
                    st.session_state["auth_user"] = user
                    st.rerun()
                else:
                    st.error("Invalid email or password.")

    with tab_register:
        with st.form("register_form"):
            reg_name = st.text_input("Name")
            reg_email = st.text_input("Email")
            reg_pw = st.text_input("Password", type="password")
            reg_pw2 = st.text_input("Confirm Password", type="password")
            if st.form_submit_button("Create Account", use_container_width=True):
                if not reg_email or not reg_pw:
                    st.error("Email and password are required.")
                elif reg_pw != reg_pw2:
                    st.error("Passwords do not match.")
                elif add_subscriber(reg_email, reg_pw, reg_name, "free"):
                    user = authenticate(reg_email, reg_pw)
                    st.session_state["auth_user"] = user
                    st.success("Account created! You are now logged in.")
                    st.rerun()
                else:
                    st.error("An account with this email already exists.")


def logout():
    st.session_state.pop("auth_user", None)
    st.rerun()
