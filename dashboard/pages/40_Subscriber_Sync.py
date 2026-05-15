"""Page 40 — Substack subscriber sync (admin).

Stops you hand-editing data/page_email_access.json every time you publish
a paid Substack issue.

Workflow:
  1. In Substack:  Subscribers → Export → "Active subscribers (CSV)"
  2. Upload the CSV here (or paste content)
  3. Pick which premium pages they get access to
  4. Click "Sync" — the JSON is updated in place; new emails are added,
     missing ones can optionally be removed (off by default)

The CSV format Substack exports is:
    email,active_subscription,expiry,created_at,name
"""

from __future__ import annotations

import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import init_session_state, password_gate, is_admin

st.set_page_config(page_title="Subscriber Sync", page_icon="🔄", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Subscriber Sync")

st.title("🔄 Substack subscriber sync")
st.caption(
    "Auto-merge a Substack subscriber export into your premium email allowlist. "
    "Stops you maintaining `data/page_email_access.json` by hand."
)
st.divider()

if not is_admin():
    st.warning("Admin only.")
    st.stop()


ACCESS_FILE = Path(__file__).parent.parent.parent / "data" / "page_email_access.json"


def _load_access() -> dict:
    if ACCESS_FILE.exists():
        try: return json.loads(ACCESS_FILE.read_text())
        except Exception: return {}
    return {}


def _save_access(data: dict) -> None:
    ACCESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACCESS_FILE.write_text(json.dumps(data, indent=2))


def _extract_emails_from_csv(text: str) -> list[str]:
    """Pull the email column out of a Substack export CSV.
    Tolerant of column ordering — looks for any column literally named 'email'."""
    emails: list[str] = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        # Case-insensitive header lookup
        email_col = None
        for col in (reader.fieldnames or []):
            if col and col.strip().lower() in ("email", "email address", "email_address"):
                email_col = col; break
        if not email_col:
            # Fallback: try first column
            email_col = (reader.fieldnames or [""])[0]
        for row in reader:
            v = (row.get(email_col, "") or "").strip().lower()
            if "@" in v and "." in v.split("@")[-1]:
                emails.append(v)
    except Exception:
        # Plain-text "one email per line" fallback
        for line in text.splitlines():
            v = line.strip().lower()
            if "@" in v and "." in v.split("@")[-1]:
                emails.append(v)
    # De-dupe preserving order
    seen, out = set(), []
    for e in emails:
        if e not in seen:
            seen.add(e); out.append(e)
    return out


access = _load_access()
all_pages = sorted(access.keys())
if not all_pages:
    st.info("No pages defined in `data/page_email_access.json` yet — "
            "use the Admin page to set up email-gated pages first.")
    st.stop()


# ── Input: upload OR paste ───────────────────────────────────────────────
st.subheader("📥 Source")
src_col1, src_col2 = st.columns(2)
with src_col1:
    uploaded = st.file_uploader("Upload Substack export (CSV)", type=["csv", "txt"])
with src_col2:
    pasted = st.text_area(
        "…or paste the CSV / one-email-per-line",
        height=160,
        placeholder="email,name\nalice@example.com,Alice\nbob@example.com,Bob",
    )

text = ""
if uploaded:
    text = uploaded.read().decode("utf-8", errors="ignore")
elif pasted.strip():
    text = pasted

if not text:
    st.info("Provide a CSV (upload) or paste emails above to preview.")
    st.stop()

new_emails = _extract_emails_from_csv(text)
st.success(f"Parsed **{len(new_emails)}** distinct emails from the input.")
with st.expander(f"Preview ({min(20, len(new_emails))} of {len(new_emails)})"):
    st.code("\n".join(new_emails[:20]), language=None)


# ── Pick which pages to sync ─────────────────────────────────────────────
st.subheader("🎯 Sync target")
sync_pages = st.multiselect(
    "Sync these subscribers into these gated pages",
    options=all_pages,
    default=[p for p in all_pages if access[p].get("enabled")],
    format_func=lambda p: f"{p} ({len(access[p].get('emails', []))} current)",
)

remove_missing = st.checkbox(
    "⚠️ Also REMOVE emails from these pages that aren't in the upload "
    "(use when Substack export is a fresh full list, not an addition)",
    value=False,
)


# ── Diff preview ─────────────────────────────────────────────────────────
if sync_pages:
    st.subheader("🔍 Preview the diff")
    rows = []
    for page in sync_pages:
        current = set(e.lower() for e in access[page].get("emails", []))
        incoming = set(new_emails)
        to_add = sorted(incoming - current)
        to_keep = current & incoming
        to_remove = sorted(current - incoming) if remove_missing else []
        rows.append({
            "Page":         page,
            "Currently":    len(current),
            "Will add":     len(to_add),
            "Will keep":    len(to_keep),
            "Will remove":  len(to_remove) if remove_missing else "(skip)",
            "After sync":   len(current | incoming) - (len(to_remove) if remove_missing else 0),
        })
    st.dataframe(pd.DataFrame(rows).set_index("Page"), use_container_width=True)


# ── Commit the sync ──────────────────────────────────────────────────────
if st.button("✅ Sync now", type="primary", use_container_width=True,
              disabled=not sync_pages):
    for page in sync_pages:
        current = set(e.lower() for e in access[page].get("emails", []))
        incoming = set(new_emails)
        if remove_missing:
            new_list = sorted(incoming)
        else:
            new_list = sorted(current | incoming)
        access[page]["emails"] = new_list
    _save_access(access)
    st.success(
        f"Synced {len(new_emails)} emails into {len(sync_pages)} page(s). "
        f"`data/page_email_access.json` updated at {datetime.now().strftime('%H:%M:%S')}."
    )
    st.balloons()


# ── Tier assignment (separate flow — for the tier-gate model) ─────────────
st.divider()
st.subheader("🎫 Assign subscriber tier")
st.caption(
    "The premium gate (Substack vs Pro vs Founding) reads "
    "`data/subscriber_tiers.json`. Use the same parsed emails above to "
    "bulk-assign a tier here. This is independent of the page allowlist sync above."
)

from dashboard.components.tiers import set_tier_bulk, list_all_subscribers

tc1, tc2 = st.columns([2, 1])
with tc1:
    chosen_tier = st.selectbox(
        "Assign tier",
        ["substack", "pro", "founding"],
        help=("substack = newsletter + free dashboard pages.  "
              "pro = adds 6 Pro analytical pages.  "
              "founding = same access as pro, price-locked."),
    )
with tc2:
    st.write("")
    st.write("")
    if st.button(f"🎫 Assign {chosen_tier} to all {len(new_emails)} emails",
                  use_container_width=True,
                  disabled=not new_emails):
        n = set_tier_bulk(new_emails, chosen_tier)
        st.success(f"Updated tier on {n} email(s) → **{chosen_tier}**.")
        st.rerun()

with st.expander("👥 Current tier roster"):
    roster = list_all_subscribers()
    if roster:
        import pandas as pd
        st.dataframe(pd.DataFrame(roster), use_container_width=True,
                      hide_index=True)
    else:
        st.caption("_No subscribers assigned a tier yet._")


# ── Audit log ────────────────────────────────────────────────────────────
st.divider()
with st.expander("📜 Current page → email-count overview"):
    rows = [{"Page": p, "Emails": len(d.get("emails", [])),
             "Enabled": d.get("enabled", False)}
            for p, d in sorted(access.items())]
    st.dataframe(pd.DataFrame(rows).set_index("Page"), use_container_width=True)
