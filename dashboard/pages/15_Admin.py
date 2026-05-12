"""
15_Admin.py — Admin panel (admin password required).

Tabs:
  • Page Email Access  — per-page subscriber allow-lists, Substack CSV sync
  • Subscribers        — full dashboard subscribers (JSON from Alerts page)
  • Feature Requests   — viewer submissions
  • Settings           — env / secrets overview
"""

import csv
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from dashboard.state import (
    _secret, is_admin, password_gate,
    load_page_email_access, save_page_email_access,
)
from dashboard.components.header import render_page_header
from dashboard.components.controls import render_sidebar_controls

st.set_page_config(page_title="Admin · Rates Dashboard", page_icon="🔒", layout="wide")
password_gate()
render_sidebar_controls()
render_page_header(current="Admin")

# ── Guard: admin only ─────────────────────────────────────────────────────────
if not is_admin():
    st.error("🔒 Admin access required.")
    st.stop()

st.title("🔒 Admin Panel")
st.caption("Manage page email access, subscribers, and dashboard settings.")
st.divider()

DATA_DIR        = Path(__file__).parent.parent.parent / "data"
BRIEFS_DIR      = Path(__file__).parent.parent.parent / "briefs"
SUBSCRIBERS_FILE = DATA_DIR / "subscribers.json"
FEAT_REQ_FILE    = DATA_DIR / "feature_requests.csv"
SUBSTACK_VISITS_FILE = DATA_DIR / "substack_visits.json"

tab_labels = ["📧 Page Email Access", "👥 Subscribers", "🗞️ Substack Visitors", "📊 Weekly Briefs", "📬 Feature Requests", "⚙️ Settings"]
tabs = st.tabs(tab_labels)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — PAGE EMAIL ACCESS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    st.subheader("Page Email Access")
    st.markdown(
        "Enable a page below and add approved emails. Anyone on that list can log in "
        "with their email address and access **only that page** — no password needed. "
        "Perfect for sharing specific views with newsletter subscribers."
    )

    pea = load_page_email_access()

    # ── Substack CSV import ──────────────────────────────────────────────────
    with st.expander("📥 Import from Substack CSV", expanded=False):
        st.markdown("""
**How to export from Substack:**
1. Go to your Substack dashboard → **Settings** → **Subscribers**
2. Click **Export** → download the CSV
3. Upload it here and choose which page(s) to add those emails to
""")
        uploaded = st.file_uploader(
            "Upload Substack subscriber CSV",
            type=["csv"],
            key="substack_csv",
        )

        if uploaded is not None:
            try:
                raw = pd.read_csv(uploaded)
                raw.columns = [c.strip().lower() for c in raw.columns]

                # Find email column — Substack uses "email" but be flexible
                email_col = next(
                    (c for c in ["email", "email_address", "subscriber_email"] if c in raw.columns),
                    None,
                )
                if email_col is None:
                    st.error(f"No email column found. Columns: {list(raw.columns)}")
                else:
                    # Filter to free/active subscribers
                    type_col = next(
                        (c for c in ["type", "subscription_type", "tier", "plan"] if c in raw.columns),
                        None,
                    )
                    status_col = next(
                        (c for c in ["status", "active"] if c in raw.columns),
                        None,
                    )

                    df_subs = raw.copy()
                    if status_col:
                        df_subs = df_subs[df_subs[status_col].astype(str).str.lower().isin(
                            ["active", "true", "1", "subscribed"]
                        )]

                    all_emails = df_subs[email_col].dropna().str.strip().str.lower().unique().tolist()

                    if type_col:
                        free_mask = df_subs[type_col].astype(str).str.lower().isin(
                            ["free", "free_subscriber", "subscriber"]
                        )
                        free_emails = df_subs.loc[free_mask, email_col].dropna().str.strip().str.lower().unique().tolist()
                        paid_emails = df_subs.loc[~free_mask, email_col].dropna().str.strip().str.lower().unique().tolist()
                        st.success(
                            f"Found **{len(all_emails)}** subscribers "
                            f"({len(free_emails)} free · {len(paid_emails)} paid/other)"
                        )
                        _email_choice = st.radio(
                            "Which subscribers to import?",
                            ["All", "Free only", "Paid/other only"],
                            horizontal=True,
                            key="import_type",
                        )
                        emails_to_import = (
                            all_emails if _email_choice == "All"
                            else free_emails if _email_choice == "Free only"
                            else paid_emails
                        )
                    else:
                        st.success(f"Found **{len(all_emails)}** email addresses")
                        emails_to_import = all_emails

                    if emails_to_import:
                        st.dataframe(
                            pd.DataFrame({"email": emails_to_import[:20]}),
                            use_container_width=True,
                            hide_index=True,
                        )
                        if len(emails_to_import) > 20:
                            st.caption(f"… and {len(emails_to_import) - 20} more")

                        # Choose target pages
                        _page_opts = list(pea.keys())
                        _page_labels = {k: f"{pea[k].get('icon','')} {pea[k]['display_name']}" for k in _page_opts}
                        target_pages = st.multiselect(
                            "Add to which page(s)?",
                            options=_page_opts,
                            format_func=lambda k: _page_labels[k],
                            key="import_targets",
                        )

                        _mode = st.radio(
                            "Import mode",
                            ["Merge (add new, keep existing)", "Replace (overwrite entire list)"],
                            key="import_mode",
                        )

                        if st.button(
                            f"✅ Import {len(emails_to_import)} emails to {len(target_pages)} page(s)",
                            type="primary",
                            disabled=not target_pages,
                            key="do_import",
                        ):
                            for slug in target_pages:
                                if _mode.startswith("Replace"):
                                    pea[slug]["emails"] = emails_to_import
                                else:
                                    existing = set(e.lower() for e in pea[slug].get("emails", []))
                                    merged   = sorted(existing | set(emails_to_import))
                                    pea[slug]["emails"] = merged
                                pea[slug]["enabled"] = True
                            save_page_email_access(pea)
                            st.success(
                                f"Imported {len(emails_to_import)} emails to: "
                                + ", ".join(pea[s]["display_name"] for s in target_pages)
                            )
                            st.rerun()
            except Exception as e:
                st.error(f"Failed to parse CSV: {e}")

    st.divider()

    # ── Per-page management ──────────────────────────────────────────────────
    st.markdown("### Per-Page Access Control")

    for slug, info in pea.items():
        icon      = info.get("icon", "📄")
        name      = info["display_name"]
        enabled   = info.get("enabled", False)
        emails    = info.get("emails", [])
        n_emails  = len(emails)

        with st.expander(
            f"{icon} **{name}** — {'🟢 Enabled' if enabled else '⚫ Disabled'} · {n_emails} email(s)",
            expanded=False,
        ):
            _c1, _c2 = st.columns([3, 1])
            with _c1:
                st.markdown(
                    f"Slug: `{slug}` · URL: `pages/{slug}.py`"
                )
            with _c2:
                new_enabled = st.toggle(
                    "Enable email access",
                    value=enabled,
                    key=f"en_{slug}",
                    help="When enabled, approved emails can log in to this page only",
                )
                if new_enabled != enabled:
                    pea[slug]["enabled"] = new_enabled
                    save_page_email_access(pea)
                    st.rerun()

            st.markdown(f"**{n_emails} approved email(s)**")

            # Show current list
            if emails:
                _email_df = pd.DataFrame({"Email": emails})
                _del_col, _list_col = st.columns([1, 4])
                with _list_col:
                    st.dataframe(_email_df, use_container_width=True, hide_index=True, height=180)
                with _del_col:
                    _to_remove = st.selectbox(
                        "Remove email",
                        options=["— select —"] + emails,
                        key=f"rm_{slug}",
                    )
                    if st.button("🗑️ Remove", key=f"rmb_{slug}",
                                 disabled=_to_remove == "— select —"):
                        pea[slug]["emails"] = [e for e in emails if e != _to_remove]
                        save_page_email_access(pea)
                        st.success(f"Removed {_to_remove}")
                        st.rerun()
            else:
                st.info("No approved emails yet. Add one below or import from Substack.")

            # Add single email
            with st.form(f"add_{slug}"):
                _new_email = st.text_input(
                    "Add email", placeholder="subscriber@example.com", key=f"inp_{slug}"
                )
                if st.form_submit_button("➕ Add", use_container_width=True):
                    _ne = _new_email.strip().lower()
                    if "@" not in _ne:
                        st.error("Enter a valid email.")
                    elif _ne in [e.lower() for e in pea[slug].get("emails", [])]:
                        st.warning("Already in the list.")
                    else:
                        pea[slug].setdefault("emails", []).append(_ne)
                        pea[slug]["enabled"] = True
                        save_page_email_access(pea)
                        st.success(f"Added {_ne}")
                        st.rerun()

            # Bulk add (paste multiple)
            with st.expander("📋 Paste multiple emails"):
                _bulk = st.text_area(
                    "One email per line",
                    key=f"bulk_{slug}",
                    height=100,
                )
                if st.button("Add all", key=f"bulkb_{slug}"):
                    _existing = set(e.lower() for e in pea[slug].get("emails", []))
                    _new_list = [e.strip().lower() for e in _bulk.splitlines()
                                 if "@" in e.strip() and e.strip().lower() not in _existing]
                    pea[slug].setdefault("emails", []).extend(_new_list)
                    pea[slug]["enabled"] = True
                    save_page_email_access(pea)
                    st.success(f"Added {len(_new_list)} new email(s)")
                    st.rerun()

            # Export this page's list
            if emails:
                _csv_bytes = "\n".join(emails).encode()
                st.download_button(
                    f"⬇️ Export {name} email list",
                    data=_csv_bytes,
                    file_name=f"{slug}_emails.txt",
                    mime="text/plain",
                    key=f"dl_{slug}",
                )

    st.divider()

    # ── Global stats ─────────────────────────────────────────────────────────
    _total_unique = len(set(
        e.lower()
        for info in pea.values()
        for e in info.get("emails", [])
    ))
    _enabled_count = sum(1 for v in pea.values() if v.get("enabled"))
    _m1, _m2, _m3 = st.columns(3)
    _m1.metric("Pages with email access enabled", _enabled_count)
    _m2.metric("Total unique approved emails", _total_unique)
    _m3.metric("Total pages configured", len(pea))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — FULL DASHBOARD SUBSCRIBERS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.subheader("Full Dashboard Subscribers")
    st.caption("Users who subscribed via the Alerts page (full dashboard viewer access).")

    subs = []
    if SUBSCRIBERS_FILE.exists():
        try:
            subs = json.loads(SUBSCRIBERS_FILE.read_text())
        except Exception:
            subs = []

    if subs:
        subs_df = pd.DataFrame(subs)
        st.metric("Total subscribers", len(subs_df))
        st.dataframe(subs_df, use_container_width=True, hide_index=True)

        # Remove a subscriber
        with st.expander("Remove a subscriber"):
            _emails = [s["email"] for s in subs]
            _sel    = st.selectbox("Select email to remove", ["— select —"] + _emails, key="rm_sub")
            if st.button("Remove", key="rm_sub_btn", disabled=_sel == "— select —"):
                subs = [s for s in subs if s["email"] != _sel]
                SUBSCRIBERS_FILE.write_text(json.dumps(subs, indent=2))
                st.success(f"Removed {_sel}")
                st.rerun()

        # Export
        _sub_csv = pd.DataFrame(subs).to_csv(index=False).encode()
        st.download_button(
            "⬇️ Export subscriber list (CSV)",
            data=_sub_csv,
            file_name="dashboard_subscribers.csv",
            mime="text/csv",
        )
    else:
        st.info("No full-dashboard subscribers yet. Viewers can subscribe from the Alerts page.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — SUBSTACK MODEL VISITORS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.subheader("Substack Model Visitors")
    st.caption("Logged each time a reader unlocks a model via an article password.")

    visits = []
    if SUBSTACK_VISITS_FILE.exists():
        try:
            visits = json.loads(SUBSTACK_VISITS_FILE.read_text())
        except Exception:
            visits = []

    if visits:
        vdf = pd.DataFrame(visits)
        vdf["timestamp"] = pd.to_datetime(vdf["timestamp"])
        vdf = vdf.sort_values("timestamp", ascending=False).reset_index(drop=True)

        # Summary metrics
        _v1, _v2, _v3, _v4 = st.columns(4)
        _v1.metric("Total unlocks", len(vdf))
        _v2.metric("Unique emails", vdf[vdf["email"] != ""]["email"].nunique())
        _v3.metric("Models accessed", vdf["model_id"].nunique())
        _v4.metric("Last unlock", vdf["timestamp"].max().strftime("%d %b %H:%M"))
        st.divider()

        # Per-model breakdown
        st.markdown("#### Unlocks by model")
        _mc = vdf.groupby("model_name").size().reset_index(name="Unlocks").sort_values("Unlocks", ascending=False)
        st.dataframe(_mc, use_container_width=True, hide_index=True)
        st.divider()

        # Full log
        st.markdown("#### Full visitor log")
        _disp = vdf[["timestamp", "model_name", "email"]].rename(columns={
            "timestamp": "When", "model_name": "Model", "email": "Email"
        })
        _disp["When"] = _disp["When"].dt.strftime("%Y-%m-%d %H:%M")
        st.dataframe(_disp, use_container_width=True, hide_index=True, height=380)

        # Export
        _vis_csv = _disp.to_csv(index=False).encode()
        st.download_button(
            "⬇️ Export visitor log (CSV)",
            data=_vis_csv,
            file_name="substack_visitors.csv",
            mime="text/csv",
        )

        # Clear log
        with st.expander("⚠️ Clear visitor log"):
            st.warning("This permanently deletes all visit records.")
            if st.button("Delete all visit records", type="primary"):
                SUBSTACK_VISITS_FILE.write_text("[]")
                st.success("Log cleared.")
                st.rerun()
    else:
        st.info("No visits recorded yet. Visitors are logged when they unlock a Substack model.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — WEEKLY BRIEFS ARCHIVE
# ══════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    import base64
    import streamlit.components.v1 as _cv1

    st.subheader("Weekly Briefs Archive")
    st.caption("All PDF reports sent on Monday / Friday — stored in briefs/<date>/")

    # Collect every PDF under briefs/
    all_pdfs = sorted(BRIEFS_DIR.glob("**/Rates_Weekly_*.pdf"), reverse=True)

    if not all_pdfs:
        st.info("No PDFs generated yet. Use the Alerts page → Generate PDF / Send PDF Alert.")
    else:
        # Summary metrics
        _mon_pdfs = [p for p in all_pdfs if "Monday" in p.name]
        _fri_pdfs = [p for p in all_pdfs if "Friday" in p.name]
        _mc1, _mc2, _mc3 = st.columns(3)
        _mc1.metric("Total PDFs", len(all_pdfs))
        _mc2.metric("Monday Setups", len(_mon_pdfs))
        _mc3.metric("Friday Recaps", len(_fri_pdfs))
        st.divider()

        # Group by week folder
        _weeks = sorted(set(p.parent.name for p in all_pdfs), reverse=True)

        for _week in _weeks:
            _week_pdfs = [p for p in all_pdfs if p.parent.name == _week]
            with st.expander(
                f"📅 Week of {_week}  ·  {len(_week_pdfs)} report(s)",
                expanded=(_week == _weeks[0]),  # open most-recent by default
            ):
                for _pdf in sorted(_week_pdfs):
                    _tag  = "🟦 Monday Setup" if "Monday" in _pdf.name else "🟩 Friday Recap"
                    _size = _pdf.stat().st_size / 1024
                    _col_info, _col_dl, _col_view = st.columns([3, 1, 1])

                    with _col_info:
                        st.markdown(f"**{_tag}** &nbsp; `{_pdf.name}`")
                        st.caption(f"{_size:.0f} KB · {datetime.fromtimestamp(_pdf.stat().st_mtime).strftime('%d %b %Y %H:%M')}")

                    with _col_dl:
                        _pdf_bytes = _pdf.read_bytes()
                        st.download_button(
                            "⬇️ Download",
                            data=_pdf_bytes,
                            file_name=_pdf.name,
                            mime="application/pdf",
                            key=f"dl_{_pdf.name}",
                            use_container_width=True,
                        )

                    with _col_view:
                        if st.button("👁 Preview", key=f"prev_{_pdf.name}", use_container_width=True):
                            st.session_state[f"show_pdf_{_pdf.name}"] = True

                    # Inline viewer — shown when Preview clicked
                    if st.session_state.get(f"show_pdf_{_pdf.name}"):
                        _b64 = base64.b64encode(_pdf.read_bytes()).decode()
                        _cv1.html(
                            f'<iframe src="data:application/pdf;base64,{_b64}" '
                            f'width="100%" height="900" style="border:none;border-radius:8px"></iframe>',
                            height=920,
                            scrolling=False,
                        )
                        if st.button("✕ Close preview", key=f"close_{_pdf.name}"):
                            st.session_state[f"show_pdf_{_pdf.name}"] = False
                            st.rerun()

        st.divider()
        st.caption(f"PDFs stored at `{BRIEFS_DIR}`")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — FEATURE REQUESTS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.subheader("Feature Requests")

    if FEAT_REQ_FILE.exists():
        try:
            fr_df = pd.read_csv(FEAT_REQ_FILE, on_bad_lines="skip", engine="python")
            st.metric("Total requests", len(fr_df))
            st.dataframe(fr_df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Could not load feature requests: {e}")
    else:
        st.info("No feature requests submitted yet.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.subheader("Dashboard Settings")

    _s_rows = [
        ("ADMIN_PASSWORD",     "Admin password",                  "***" if _secret("ADMIN_PASSWORD","") else "(not set)"),
        ("VIEWER_PASSWORDS",   "Viewer passwords (pw:name list)", _secret("VIEWER_PASSWORDS","") or "(not set)"),
        ("PAGE_PASSWORDS",     "Page-specific passwords",         _secret("PAGE_PASSWORDS","") or "(not set)"),
        ("GMAIL_USER",         "Gmail sender address",            _secret("GMAIL_USER","") or "(not set)"),
        ("GMAIL_APP_PASSWORD", "Gmail app password",              "***" if _secret("GMAIL_APP_PASSWORD","") else "(not set)"),
        ("EODHD_API_TOKEN",    "EODHD market data token",         "***" if _secret("EODHD_API_TOKEN","") else "(not set)"),
        ("AUTH_SECRET",        "HMAC auth secret",                "***" if _secret("AUTH_SECRET","") else "(not set)"),
    ]
    st.dataframe(
        pd.DataFrame(_s_rows, columns=["Key", "Description", "Status"]),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()
    st.markdown("""
**Secrets live in `.streamlit/secrets.toml`** (local) or Streamlit Cloud → Settings → Secrets.

```toml
# Auth
ADMIN_PASSWORD    = "your-admin-pw"
VIEWER_PASSWORDS  = "rates:Viewer,nomh:NomH"
PAGE_PASSWORDS    = "vol:07_Vol_Surface"  # optional password-based page lock

# Email
GMAIL_USER        = "you@gmail.com"
GMAIL_APP_PASSWORD = "xxxx xxxx xxxx xxxx"

# Data
EODHD_API_TOKEN   = "your-token"
AUTH_SECRET       = "random-string-keep-secret"
```
""")
