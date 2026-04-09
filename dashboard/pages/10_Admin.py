"""
10_Admin.py — Password-protected admin panel.

Manage subscribers, view feature requests, and configure dashboard settings.
Requires ADMIN_PASSWORD env var (or uses default) and AUTH_ENABLED=true.
"""

import csv
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st
from dashboard.state import password_gate

st.set_page_config(page_title="Admin", page_icon="🔒", layout="wide")
password_gate()

# ── Admin auth ────────────────────────────────────────────────────────────
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "macromanv2024")

if "admin_authed" not in st.session_state:
    st.session_state["admin_authed"] = False

if not st.session_state["admin_authed"]:
    st.title("🔒 Admin Panel")
    with st.form("admin_login"):
        pw = st.text_input("Admin Password", type="password")
        if st.form_submit_button("Log In"):
            if pw == ADMIN_PASSWORD:
                st.session_state["admin_authed"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    st.stop()

# ── Authenticated admin content ──────────────────────────────────────────
st.title("🔒 Admin Panel")
st.caption("Manage subscribers, feature requests, and settings.")

if st.button("Log Out", key="admin_logout"):
    st.session_state["admin_authed"] = False
    st.rerun()

st.divider()

admin_tab = st.selectbox("Section", [
    "Subscribers",
    "Feature Requests",
    "Settings",
])

# ── Subscribers ───────────────────────────────────────────────────────────
if admin_tab == "Subscribers":
    st.subheader("Subscriber Management")

    csv_path = Path(__file__).parent.parent.parent / "data" / "subscribers.csv"
    if csv_path.exists():
        subs_df = pd.read_csv(csv_path)
        st.metric("Total Subscribers", len(subs_df))

        tier_counts = subs_df["tier"].value_counts().to_dict() if "tier" in subs_df.columns else {}
        tc_cols = st.columns(max(len(tier_counts), 1))
        for i, (tier, count) in enumerate(tier_counts.items()):
            tc_cols[i % len(tc_cols)].metric(f"{tier.title()} Tier", count)

        st.divider()
        st.dataframe(subs_df.drop(columns=["password_hash"], errors="ignore"),
                      use_container_width=True, hide_index=True)

        # ── Add subscriber manually ──
        with st.expander("Add Subscriber"):
            with st.form("add_sub"):
                import sys
                sys.path.insert(0, str(Path(__file__).parent.parent.parent))
                from dashboard.auth import add_subscriber

                new_email = st.text_input("Email")
                new_name = st.text_input("Name")
                new_pw = st.text_input("Password", type="password")
                new_tier = st.selectbox("Tier", ["free", "premium", "admin"])
                if st.form_submit_button("Add"):
                    if new_email and new_pw:
                        if add_subscriber(new_email, new_pw, new_name, new_tier):
                            st.success(f"Added {new_email} ({new_tier})")
                            st.rerun()
                        else:
                            st.error("Email already exists.")
                    else:
                        st.error("Email and password required.")

        # ── Update tier ──
        with st.expander("Change Subscriber Tier"):
            if not subs_df.empty and "email" in subs_df.columns:
                with st.form("update_tier"):
                    sel_email = st.selectbox("Subscriber", subs_df["email"].tolist())
                    new_t = st.selectbox("New Tier", ["free", "premium", "admin"], key="new_tier_sel")
                    if st.form_submit_button("Update"):
                        subs_df.loc[subs_df["email"] == sel_email, "tier"] = new_t
                        subs_df.to_csv(csv_path, index=False)
                        st.success(f"Updated {sel_email} to {new_t}")
                        st.rerun()
    else:
        st.info("No subscribers yet. The subscriber list will appear once users register.")

# ── Feature Requests ──────────────────────────────────────────────────────
elif admin_tab == "Feature Requests":
    st.subheader("Feature Requests")

    fr_path = Path(__file__).parent.parent.parent / "data" / "feature_requests.csv"
    if fr_path.exists():
        fr_df = pd.read_csv(fr_path)
        st.metric("Total Requests", len(fr_df))

        if "priority" in fr_df.columns:
            p_cols = st.columns(3)
            for i, p in enumerate(["High", "Medium", "Low"]):
                count = len(fr_df[fr_df["priority"] == p])
                p_cols[i].metric(f"{p} Priority", count)

        st.divider()
        st.dataframe(fr_df, use_container_width=True, hide_index=True)
    else:
        st.info("No feature requests yet.")

# ── Settings ──────────────────────────────────────────────────────────────
elif admin_tab == "Settings":
    st.subheader("Dashboard Settings")
    st.markdown("Configure via environment variables:")

    settings = {
        "AUTH_ENABLED": ("Enable authentication", os.getenv("AUTH_ENABLED", "false")),
        "ADMIN_PASSWORD": ("Admin password", "***" if os.getenv("ADMIN_PASSWORD") else "(default)"),
        "GA_MEASUREMENT_ID": ("Google Analytics ID", os.getenv("GA_MEASUREMENT_ID", "(not set)")),
        "SMTP_HOST": ("SMTP host for emails", os.getenv("SMTP_HOST", "(not set)")),
        "SMTP_USER": ("SMTP username", os.getenv("SMTP_USER", "(not set)")),
        "GOOGLE_SHEETS_CREDENTIALS": ("GSheets service account", os.getenv("GOOGLE_SHEETS_CREDENTIALS", "(not set)")),
        "SUBSCRIBERS_SHEET_ID": ("GSheets spreadsheet ID", os.getenv("SUBSCRIBERS_SHEET_ID", "(not set)")),
    }

    settings_df = pd.DataFrame([
        {"Variable": k, "Description": v[0], "Value": v[1]}
        for k, v in settings.items()
    ])
    st.dataframe(settings_df, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("""
**To enable auth**, set the following env vars before running Streamlit:
```bash
export AUTH_ENABLED=true
export ADMIN_PASSWORD=your_secure_password

# Optional: Google Sheets backend
export GOOGLE_SHEETS_CREDENTIALS=/path/to/service-account.json
export SUBSCRIBERS_SHEET_ID=your_spreadsheet_id

# Optional: Email for feature requests
export SMTP_HOST=smtp.gmail.com
export SMTP_USER=your_email@gmail.com
export SMTP_PASS=your_app_password
```
""")
