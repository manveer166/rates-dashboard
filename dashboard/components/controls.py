"""Shared sidebar controls — date pickers, refresh button, settings."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime, timedelta

import streamlit as st

from dashboard.state import init_session_state, refresh_data, cache_age_str, password_gate


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

    if st.sidebar.button("🔄 Refresh Data", type="primary", use_container_width=True):
        refresh_data()

    st.sidebar.caption(f"Cache: {cache_age_str()}")

    # ── Auth status ────────────────────────────────────────────────────
    import os
    if os.getenv("AUTH_ENABLED", "false").lower() == "true":
        st.sidebar.divider()
        from dashboard.auth import is_logged_in, current_user, logout
        if is_logged_in():
            user = current_user()
            st.sidebar.markdown(f"**{user.get('name') or user.get('email', '')}**")
            st.sidebar.caption(f"Tier: {user.get('tier', 'free').title()}")
            if st.sidebar.button("Log Out", use_container_width=True):
                logout()
        else:
            st.sidebar.info("Not signed in")

    # ── Info ─────────────────────────────────────────────────────────────
    st.sidebar.divider()
    st.sidebar.caption(
        "**Data Sources**\n"
        "- US Treasury: treasury.gov\n"
        "- SOFR Swaps: FRED (ICE)\n"
        "- Credit Spreads: FRED (ICE BofA)\n"
        "- Macro: FRED (Federal Reserve)"
    )
