"""Beta user store — profile signup, admin approval, activity logging.

Single source of truth for the beta-tester user system. Used by:
  • dashboard/pages/50_Beta_Signup.py        — public signup form
  • dashboard/pages/51_Beta_Admin.py         — admin approve/deny + dashboard
  • dashboard/state.py::password_gate        — auth lookup
  • dashboard/components/header.py           — activity tracker hook

Data files (all under data/, gitignored for privacy):
  • data/beta_signups.json     — list of profile records + auth credentials
  • data/beta_activity.jsonl   — one JSON event per line, append-only

User passwords are stored as a salted SHA-256 hash plus a random salt.
Plaintext passwords are never written to disk. The plaintext is emailed
to the user once at approval time and is otherwise unrecoverable — if
they lose it, the admin issues a new one.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


# ── File locations ───────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent.parent
SIGNUPS_PATH  = _ROOT / "data" / "beta_signups.json"
ACTIVITY_PATH = _ROOT / "data" / "beta_activity.jsonl"


# ── Password hashing ─────────────────────────────────────────────────────
def _hash_password(password: str, salt: str) -> str:
    """SHA-256 of (salt || password). Sufficient for low-stakes beta access.
    For higher-stakes deployment switch to bcrypt or argon2 later."""
    h = hashlib.sha256()
    h.update((salt + password).encode("utf-8"))
    return h.hexdigest()


def _gen_password(n_bytes: int = 9) -> str:
    """Generate a user-friendly random password. ~18 hex chars."""
    return secrets.token_hex(n_bytes)


def _gen_salt() -> str:
    return secrets.token_hex(16)


# ── Signups store I/O ────────────────────────────────────────────────────
def _load_signups() -> list[dict]:
    if SIGNUPS_PATH.exists():
        try:
            return json.loads(SIGNUPS_PATH.read_text())
        except Exception:
            return []
    return []


def _save_signups(rows: list[dict]) -> None:
    SIGNUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIGNUPS_PATH.write_text(json.dumps(rows, indent=2, default=str))


def list_signups(status: Optional[str] = None) -> list[dict]:
    """All signups, optionally filtered by status (pending/approved/denied)."""
    rows = _load_signups()
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return sorted(rows, key=lambda r: r.get("requested_at", ""), reverse=True)


def get_signup(user_id: str) -> Optional[dict]:
    return next((r for r in _load_signups() if r.get("id") == user_id), None)


def get_signup_by_email(email: str) -> Optional[dict]:
    email = (email or "").strip().lower()
    return next((r for r in _load_signups()
                 if r.get("email", "").lower() == email), None)


# ── Profile creation ─────────────────────────────────────────────────────
def submit_signup(profile: dict) -> str:
    """Create a new pending signup. Returns the new user_id.

    `profile` should include: name, email, organisation, role,
    linkedin, substack_email, experience, why_beta, agreed_terms.
    """
    email = (profile.get("email") or "").strip().lower()
    if not email:
        raise ValueError("Email is required")
    if get_signup_by_email(email):
        raise ValueError(f"A signup already exists for {email}")

    rows = _load_signups()
    record = {
        "id":              str(uuid.uuid4()),
        "email":           email,
        "name":            (profile.get("name") or "").strip(),
        "organisation":    (profile.get("organisation") or "").strip(),
        "role":            (profile.get("role") or "").strip(),
        "linkedin":        (profile.get("linkedin") or "").strip(),
        "substack_email":  (profile.get("substack_email") or "").strip().lower(),
        "experience":      (profile.get("experience") or "").strip(),
        "why_beta":        (profile.get("why_beta") or "").strip(),
        "agreed_terms":    bool(profile.get("agreed_terms")),
        "requested_at":    datetime.utcnow().isoformat() + "Z",
        "status":          "pending",
        "approved_at":     None,
        "approved_by":     None,
        "denied_reason":   None,
        "password_hash":   None,
        "password_salt":   None,
        "credentials_sent_at": None,
        "last_login_at":   None,
    }
    rows.append(record)
    _save_signups(rows)
    return record["id"]


# ── Admin actions ────────────────────────────────────────────────────────
def approve_signup(user_id: str, approved_by: str = "admin") -> Optional[str]:
    """Approve a pending signup, issue a one-time plaintext password,
    store its hash, and return the plaintext password (so the admin
    can email it to the user). Subsequent calls return None.
    """
    rows = _load_signups()
    for r in rows:
        if r["id"] == user_id and r.get("status") == "pending":
            pw   = _gen_password()
            salt = _gen_salt()
            r["status"]              = "approved"
            r["approved_at"]         = datetime.utcnow().isoformat() + "Z"
            r["approved_by"]         = approved_by
            r["password_salt"]       = salt
            r["password_hash"]       = _hash_password(pw, salt)
            r["credentials_sent_at"] = None    # admin marks after sending
            _save_signups(rows)
            return pw
    return None


def deny_signup(user_id: str, reason: str = "") -> bool:
    """Mark a signup denied. Returns True on success."""
    rows = _load_signups()
    for r in rows:
        if r["id"] == user_id and r.get("status") == "pending":
            r["status"]        = "denied"
            r["denied_reason"] = reason
            r["approved_at"]   = datetime.utcnow().isoformat() + "Z"
            _save_signups(rows)
            return True
    return False


def revoke_access(user_id: str) -> bool:
    """Revoke an approved user's access without deleting their record."""
    rows = _load_signups()
    for r in rows:
        if r["id"] == user_id and r.get("status") == "approved":
            r["status"]        = "revoked"
            r["password_hash"] = None      # invalidate password
            r["password_salt"] = None
            _save_signups(rows)
            return True
    return False


def mark_credentials_sent(user_id: str) -> bool:
    rows = _load_signups()
    for r in rows:
        if r["id"] == user_id:
            r["credentials_sent_at"] = datetime.utcnow().isoformat() + "Z"
            _save_signups(rows)
            return True
    return False


def reissue_password(user_id: str) -> Optional[str]:
    """Issue a fresh password for an approved user (forgot password)."""
    rows = _load_signups()
    for r in rows:
        if r["id"] == user_id and r.get("status") == "approved":
            pw   = _gen_password()
            salt = _gen_salt()
            r["password_salt"] = salt
            r["password_hash"] = _hash_password(pw, salt)
            r["credentials_sent_at"] = None
            _save_signups(rows)
            return pw
    return None


# ── Authentication lookup ────────────────────────────────────────────────
def authenticate(email: str, password: str) -> Optional[dict]:
    """Return the signup record if email + password match an approved user."""
    r = get_signup_by_email(email)
    if not r:
        return None
    if r.get("status") != "approved":
        return None
    if not r.get("password_hash") or not r.get("password_salt"):
        return None
    if _hash_password(password, r["password_salt"]) != r["password_hash"]:
        return None
    # Update last_login_at silently
    try:
        rows = _load_signups()
        for row in rows:
            if row["id"] == r["id"]:
                row["last_login_at"] = datetime.utcnow().isoformat() + "Z"
                break
        _save_signups(rows)
    except Exception:
        pass
    return r


# ── Activity logging (append-only JSONL) ────────────────────────────────
def log_activity(user_email: str, page: str,
                  action: str = "view",
                  extra: Optional[dict] = None) -> None:
    """Append an event to data/beta_activity.jsonl.

    Cheap: a single file.write of one JSON line. Safe under concurrent
    Streamlit reruns because we open in append mode.
    """
    if not user_email:
        return
    rec = {
        "ts":         datetime.utcnow().isoformat() + "Z",
        "user_email": user_email.lower(),
        "page":       page,
        "action":     action,
    }
    if extra:
        rec["extra"] = extra
    try:
        ACTIVITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ACTIVITY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        # Tracking must never break the page render.
        pass


def load_activity_df() -> pd.DataFrame:
    """All activity events as a DataFrame (date-sorted desc)."""
    if not ACTIVITY_PATH.exists():
        return pd.DataFrame(columns=["ts", "user_email", "page", "action"])
    rows = []
    try:
        for line in ACTIVITY_PATH.read_text().splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame(columns=["ts", "user_email", "page", "action"])
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True)
    return df.sort_values("ts", ascending=False).reset_index(drop=True)


# ── Per-user usage stats (for the admin dashboard) ──────────────────────
def user_usage_stats() -> pd.DataFrame:
    """One row per user: total views, distinct pages, last seen, top page."""
    df = load_activity_df()
    if df.empty:
        return pd.DataFrame()
    rows = []
    for email, g in df.groupby("user_email"):
        top_page = (g["page"].value_counts().idxmax()
                    if not g.empty else "—")
        rows.append({
            "email":          email,
            "total_views":    int(len(g)),
            "distinct_pages": int(g["page"].nunique()),
            "last_seen":      g["ts"].max(),
            "first_seen":     g["ts"].min(),
            "top_page":       top_page,
        })
    out = pd.DataFrame(rows).sort_values("last_seen", ascending=False)
    return out.reset_index(drop=True)


# ── Excel export ─────────────────────────────────────────────────────────
def export_to_excel(out_path: Path | str) -> Path:
    """Write a single .xlsx with three sheets: Signups · Activity · Usage."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    signups = _load_signups()
    signups_df = (pd.DataFrame(signups) if signups else pd.DataFrame())
    # Drop sensitive columns from the export
    for col in ("password_hash", "password_salt"):
        if col in signups_df.columns:
            signups_df = signups_df.drop(columns=[col])

    activity_df = load_activity_df()
    if not activity_df.empty and hasattr(activity_df["ts"], "dt"):
        activity_df = activity_df.copy()
        activity_df["ts"] = activity_df["ts"].dt.tz_localize(None)

    usage_df = user_usage_stats()
    if not usage_df.empty:
        for col in ("first_seen", "last_seen"):
            if col in usage_df.columns and hasattr(usage_df[col], "dt"):
                usage_df[col] = usage_df[col].dt.tz_localize(None)

    with pd.ExcelWriter(out_path, engine="openpyxl") as xl:
        (signups_df  if not signups_df.empty  else
         pd.DataFrame({"_": ["No signups yet."]})).to_excel(
            xl, sheet_name="Signups", index=False)
        (activity_df if not activity_df.empty else
         pd.DataFrame({"_": ["No activity yet."]})).to_excel(
            xl, sheet_name="Activity", index=False)
        (usage_df    if not usage_df.empty    else
         pd.DataFrame({"_": ["No usage data yet."]})).to_excel(
            xl, sheet_name="Usage", index=False)
    return out_path
