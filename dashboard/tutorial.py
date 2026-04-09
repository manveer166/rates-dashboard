"""
tutorial.py — Native Streamlit guided tour.

Uses st.dialog for a modal walkthrough of dashboard features.
No external JS dependencies — works reliably on Streamlit Cloud.
"""

import streamlit as st


# ── Step definitions ─────────────────────────────────────────────────────

WELCOME_STEPS = [
    {
        "title": "Welcome to the Rates Dashboard",
        "icon": "📈",
        "body": (
            "This tutorial walks you through every feature of the dashboard.\n\n"
            "Click **Next** to preview what's inside."
        ),
    },
    {
        "title": "Home — Market Overview",
        "icon": "🏠",
        "body": (
            "The **Home page** shows live KPI metrics for:\n\n"
            "- **US Treasury yields** (1Y – 30Y)\n"
            "- **International yields** (DE, UK, CH, JP)\n"
            "- **SOFR swaps & credit spreads** (IG, HY, BBB)\n"
            "- **Yield curve snapshot** — today vs N months ago\n\n"
            "Every metric shows the change vs your chosen lookback period."
        ),
    },
    {
        "title": "Yield Curve & Spreads",
        "icon": "📊",
        "body": (
            "**Yield Curve page:** Animated curve evolution, butterfly analysis, "
            "and curve shape metrics.\n\n"
            "**Spreads page:** 2s10s, 5s30s, and custom spreads with z-score "
            "bands and percentile rankings."
        ),
    },
    {
        "title": "Regression & PCA",
        "icon": "📐",
        "body": (
            "**Regression:** Run rolling OLS on any two series — find rich/cheap "
            "vs fair value, with residual z-scores.\n\n"
            "**PCA:** Decompose the curve into Level, Slope, and Curvature factors. "
            "See how much each explains."
        ),
    },
    {
        "title": "Trade Scanner (Analysis)",
        "icon": "🔍",
        "body": (
            "The most powerful page — scans **100+ outright, curve, and fly trades** "
            "and ranks them by:\n\n"
            "- **Sharpe ratio** — risk-adjusted expected return\n"
            "- **Z-score** — how cheap/rich vs history\n"
            "- **Carry + Rolldown** — income from holding\n"
            "- **Net Convexity** — DV01-weighted convexity pickup\n\n"
            "Click any trade for a deep-dive detail panel with charts."
        ),
    },
    {
        "title": "Vol Surface & Trade Tracker",
        "icon": "🌊",
        "body": (
            "**Vol Surface:** 3D swaption vol surface, heatmap, and SABR smile estimator.\n\n"
            "**Trade Tracker:** Log trade ideas with live entry levels, track P&L in "
            "real-time, and see your win rate and cumulative performance."
        ),
    },
    {
        "title": "Alerts, Glossary & More",
        "icon": "🔔",
        "body": (
            "**Alerts:** Set up email notifications for top scanner movers.\n\n"
            "**Glossary:** Definitions for every metric and column.\n\n"
            "**Feature Request:** Submit ideas directly.\n\n"
            "---\n"
            "Enter the password **rates** to get started!"
        ),
    },
]

HOME_STEPS = [
    {
        "title": "Welcome",
        "icon": "📈",
        "body": (
            "This tutorial highlights the key features of the **Home page**.\n\n"
            "Click **Next** to begin."
        ),
    },
    {
        "title": "Sidebar Controls",
        "icon": "🎛️",
        "body": (
            "The **sidebar** (left panel) is your control centre:\n\n"
            "- **Quick Select:** Set lookback period (3M to 5Y)\n"
            "- **Date Range:** Custom start/end dates\n"
            "- **Refresh Data:** Force reload from all sources\n"
            "- **Cache:** Shows how fresh your data is"
        ),
    },
    {
        "title": "KPI Metrics",
        "icon": "📋",
        "body": (
            "The metric cards show **current yields** and their **change** "
            "vs the lookback period.\n\n"
            "- Green arrow = rates fell (good for receivers)\n"
            "- Red arrow = rates rose"
        ),
    },
    {
        "title": "Yield Curve Snapshot",
        "icon": "📉",
        "body": (
            "The chart compares **today's yield curve** vs the curve N months ago.\n\n"
            "- **Hover** for exact values\n"
            "- **Click+drag** to zoom\n"
            "- **Double-click** to reset"
        ),
    },
    {
        "title": "Lookback Slider",
        "icon": "📅",
        "body": (
            "Drag the slider to change the comparison period. "
            "KPI deltas and charts update instantly.\n\n"
            "Try switching between **3 Months** and **2 Years** to see "
            "how the curve evolved."
        ),
    },
    {
        "title": "Explore the Pages",
        "icon": "🗂️",
        "body": (
            "Use the **sidebar navigation** to explore:\n\n"
            "- **Yield Curve** — curve shapes & evolution\n"
            "- **Spreads** — 2s10s, 5s30s with z-scores\n"
            "- **Regression** — rich/cheap analysis\n"
            "- **PCA** — level, slope, curvature factors\n"
            "- **Analysis** — the Trade Scanner (most important!)\n"
            "- **Vol Surface** — swaption vol visualisation\n"
            "- **Trade Tracker** — log & track your ideas\n\n"
            "The **Trade Scanner** on the Analysis page is where trade ideas "
            "come from. Start there!"
        ),
    },
]

STEPS = {
    "welcome": WELCOME_STEPS,
    "home": HOME_STEPS,
}


# ── Public API ───────────────────────────────────────────────────────────

def render_tutorial_button(key_suffix: str = ""):
    """Render the 'Start Tutorial' button. Sets session state to open the tour."""
    key = f"start_tut_btn_{key_suffix}" if key_suffix else "start_tut_btn"
    if st.button("Start Tutorial", key=key, use_container_width=True):
        st.session_state["tut_active"] = True
        st.session_state["tut_step"] = 0
        st.rerun()


def render_tutorial(page: str = "welcome"):
    """Render the tutorial modal if active. Call on every page that has a tutorial."""
    if not st.session_state.get("tut_active"):
        return

    steps = STEPS.get(page, WELCOME_STEPS)
    step_idx = st.session_state.get("tut_step", 0)
    step_idx = min(step_idx, len(steps) - 1)
    step = steps[step_idx]

    # ── Modal container ──────────────────────────────────────────────────
    st.markdown("""
    <style>
    .tut-overlay {
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
        background: rgba(0,0,0,0.65); z-index: 99998;
    }
    .tut-card {
        position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
        background: #1a1a2e; border: 1px solid #333; border-radius: 16px;
        padding: 32px 36px 24px; max-width: 520px; width: 90vw;
        z-index: 99999; box-shadow: 0 20px 60px rgba(0,0,0,0.5);
        font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    }
    .tut-card h2 { color: #4fc3f7; margin: 0 0 6px; font-size: 22px; }
    .tut-progress {
        color: #666; font-size: 12px; margin-bottom: 16px;
        letter-spacing: 0.5px;
    }
    .tut-bar { height: 3px; background: #333; border-radius: 2px; margin-bottom: 20px; }
    .tut-bar-fill { height: 100%; background: #4fc3f7; border-radius: 2px; transition: width 0.3s; }
    </style>
    """, unsafe_allow_html=True)

    pct = int(((step_idx + 1) / len(steps)) * 100)
    st.markdown(f"""
    <div class="tut-overlay"></div>
    <div class="tut-card">
        <h2>{step['icon']} {step['title']}</h2>
        <div class="tut-progress">Step {step_idx + 1} of {len(steps)}</div>
        <div class="tut-bar"><div class="tut-bar-fill" style="width:{pct}%"></div></div>
    </div>
    """, unsafe_allow_html=True)

    # Body text via Streamlit markdown (supports full formatting)
    with st.container():
        st.markdown(step["body"])

    # ── Navigation buttons ───────────────────────────────────────────────
    bcols = st.columns([1, 1, 1])
    with bcols[0]:
        if step_idx > 0:
            if st.button("← Back", key="tut_back", use_container_width=True):
                st.session_state["tut_step"] = step_idx - 1
                st.rerun()
    with bcols[1]:
        if st.button("✕ Exit", key="tut_exit", use_container_width=True):
            st.session_state["tut_active"] = False
            st.session_state["tut_step"] = 0
            st.rerun()
    with bcols[2]:
        if step_idx < len(steps) - 1:
            if st.button("Next →", key="tut_next", type="primary", use_container_width=True):
                st.session_state["tut_step"] = step_idx + 1
                st.rerun()
        else:
            if st.button("Finish ✓", key="tut_finish", type="primary", use_container_width=True):
                st.session_state["tut_active"] = False
                st.session_state["tut_step"] = 0
                st.rerun()


# Keep old name as alias for backwards compat
render_tutorial_overlay = render_tutorial
