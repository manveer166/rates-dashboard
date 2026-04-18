"""Shared sidebar controls — date pickers, refresh button, settings."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime, timedelta

import streamlit as st

from dashboard.state import init_session_state, refresh_data, cache_age_str, password_gate, is_admin


def render_sidebar_controls() -> None:
    """Render the global sidebar controls and update session state."""
    password_gate()
    init_session_state()

    st.sidebar.title("⚙️ Controls")

    # ── Date range ──────────────────────────────────────────────────────
    st.sidebar.subheader("📅 Date Range")

    preset = st.sidebar.selectbox(
        "Quick Select",
        ["Custom", "3 Months", "6 Months", "9 Months", "1 Year", "2 Years", "5 Years"],
        index=4,   # default = 1 Year
    )

    today = datetime.today().date()
    if preset != "Custom":
        days_map = {
            "3 Months": 92,
            "6 Months": 183,
            "9 Months": 274,
            "1 Year":   365,
            "2 Years":  730,
            "5 Years":  1825,
        }
        default_start = today - timedelta(days=days_map[preset])
        default_end   = today
        st.session_state.start_date = str(default_start)
        st.session_state.end_date   = str(default_end)

    col1, col2 = st.sidebar.columns(2)
    with col1:
        start = st.date_input(
            "Start",
            value=datetime.strptime(st.session_state.start_date, "%Y-%m-%d").date(),
            max_value=today,
        )
    with col2:
        end = st.date_input(
            "End",
            value=datetime.strptime(st.session_state.end_date, "%Y-%m-%d").date(),
            max_value=today,
        )

    if start > end:
        st.sidebar.error("Start date must be before end date.")
    else:
        st.session_state.start_date = str(start)
        st.session_state.end_date   = str(end)

    # ── Cache control ────────────────────────────────────────────────────
    st.sidebar.divider()
    st.session_state.use_cache = st.sidebar.checkbox(
        "Use disk cache", value=True,
        help="Uncheck to force fresh data fetch from all sources.",
    )

    if st.sidebar.button(
        "🔄 Refresh Data",
        type="primary",
        use_container_width=True,
        disabled=not is_admin(),
        help=None if is_admin() else "Admin only — log in with the admin password to refresh shared data.",
    ):
        refresh_data()

    role_tag = "👑 admin" if is_admin() else "👁️ viewer"
    st.sidebar.caption(f"Cache: {cache_age_str()}  ·  {role_tag}")

    # ── Auth / Logout ─────────────────────────────────────────────────────
    st.sidebar.divider()
    user_label = st.session_state.get("site_user", "")
    if user_label:
        st.sidebar.caption(f"👤 Logged in as **{user_label}**")
    if st.sidebar.button("🚪 Log Out", use_container_width=True):
        for key in ("site_authenticated", "site_admin", "site_user"):
            st.session_state.pop(key, None)
        try:
            st.query_params.clear()
        except Exception:
            pass
        st.rerun()

    # ── Info ─────────────────────────────────────────────────────────────
    st.sidebar.divider()
    st.sidebar.caption(
        "**Data Sources**\n"
        "- US Treasury: treasury.gov\n"
        "- SOFR Swaps: FRED (ICE)\n"
        "- Credit Spreads: FRED (ICE BofA)\n"
        "- Macro: FRED (Federal Reserve)"
    )
