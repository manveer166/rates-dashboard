"""
Main Streamlit app entry point for the Rates Dashboard.
Run with: streamlit run dashboard/app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import TENOR_LABELS, TENOR_YEARS, PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import get_master_df, init_session_state
from dashboard.tutorial import render_tutorial_button, render_tutorial

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(
    page_title="Home · Rates Dashboard",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "**Rates Dashboard** — Global Rates & Spread Analysis"},
)

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
    /* ─────────────────────────────────────────────────────────────────
       Design system — based on 11 UI/UX principles
       Color ramp (single brand blue, lightened for cards & text):
         --c-bg-0: deepest navy   (page canvas)
         --c-bg-1: card / sidebar (one shade lighter — depth via lightness, not borders)
         --c-bg-2: hover / nested
         --c-bg-3: input / pressed
         --c-accent:  cyan brand highlight
         --c-text-1:  primary text
         --c-text-2:  secondary text (inactive / labels)
         --c-text-3:  tertiary text (captions, hints)
       Spacing follows a 4-point grid.
       Font: Inter, single family across the app.
       ───────────────────────────────────────────────────────────────── */
    :root {
        --c-bg-0:   #0a1628;
        --c-bg-1:   #122340;
        --c-bg-2:   #1a3056;
        --c-bg-3:   #233e6e;
        --c-accent: #4fc3f7;
        --c-accent-soft: rgba(79, 195, 247, 0.14);
        --c-text-1: #e8eef9;
        --c-text-2: #94a8c9;
        --c-text-3: #6a7e9e;
        --c-success: #4ade80;
        --c-danger:  #f87171;
        --c-warning: #fbbf24;
        --shadow-1: 0 1px 2px rgba(0,0,0,0.10);
        --shadow-2: 0 4px 14px rgba(0,0,0,0.18);
        --shadow-3: 0 12px 32px rgba(0,0,0,0.28);
        --r-sm: 4px;
        --r-md: 6px;
        --r-lg: 10px;
    }

    /* ── Typography (single sans-serif, tightened headers) ── */
    html, body, [class*="css"], .stApp, .stMarkdown, .stTextInput, .stSelectbox,
    .stButton, button, input, textarea, select {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        font-feature-settings: 'cv11', 'ss01';
        -webkit-font-smoothing: antialiased;
    }
    h1 {
        color: var(--c-text-1) !important;
        font-weight: 700 !important;
        font-size: 32px !important;
        letter-spacing: -0.02em !important;
        line-height: 1.15 !important;
        margin-bottom: 4px !important;
    }
    h2 {
        color: var(--c-text-1) !important;
        font-weight: 600 !important;
        font-size: 22px !important;
        letter-spacing: -0.015em !important;
        line-height: 1.2 !important;
    }
    h3, .stSubheader {
        color: var(--c-text-1) !important;
        font-weight: 600 !important;
        font-size: 17px !important;
        letter-spacing: -0.01em !important;
        line-height: 1.3 !important;
    }
    p, .stMarkdown { color: var(--c-text-1); line-height: 1.55; }
    .stCaption, [data-testid="stCaptionContainer"] { color: var(--c-text-3) !important; font-size: 12px !important; }

    /* ── Page canvas (depth via lightness, not borders) ── */
    .stApp { background: var(--c-bg-0); }
    [data-testid="stHeader"] { background: rgba(10, 22, 40, 0.80); backdrop-filter: blur(8px); }
    [data-testid="stAppViewContainer"] > .main { background: var(--c-bg-0); }
    [data-testid="block-container"] { padding-top: 24px !important; padding-bottom: 32px !important; }

    /* ── Sidebar (slightly lighter than canvas → reads as elevated) ── */
    [data-testid="stSidebar"] {
        background: var(--c-bg-1);
        border-right: none;
        box-shadow: var(--shadow-2);
    }
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] p { color: var(--c-text-2) !important; }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 { color: var(--c-text-1) !important; font-size: 15px !important; }

    /* ── Cards (KPI metrics, dataframes) — depth via lighter background ── */
    [data-testid="stMetric"] {
        background: var(--c-bg-1);
        border: none;
        border-radius: var(--r-lg);
        padding: 16px 18px;
        box-shadow: var(--shadow-1);
        transition: background 0.18s ease, box-shadow 0.18s ease;
    }
    [data-testid="stMetric"]:hover {
        background: var(--c-bg-2);
        box-shadow: var(--shadow-2);
    }
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: var(--c-text-1) !important;
        font-weight: 600 !important;
        font-size: 26px !important;
        letter-spacing: -0.015em !important;
    }
    [data-testid="stMetric"] [data-testid="stMetricLabel"] {
        color: var(--c-text-2) !important;
        font-size: 11px !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    [data-testid="stMetric"] [data-testid="stMetricDelta"] svg { width: 12px !important; height: 12px !important; }

    .section-header {
        font-size: 11px; font-weight: 700; color: var(--c-accent);
        text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 12px;
    }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] {
        background: var(--c-bg-1);
        border-radius: var(--r-md);
        padding: 4px;
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        color: var(--c-text-2);
        border-radius: var(--r-sm);
        padding: 8px 16px;
        transition: all 0.15s ease;
    }
    .stTabs [data-baseweb="tab"]:hover { color: var(--c-text-1); background: var(--c-bg-2); }
    .stTabs [aria-selected="true"] {
        background: var(--c-bg-3) !important;
        color: var(--c-text-1) !important;
    }

    /* ── Dataframes ── */
    .stDataFrame, [data-testid="stDataFrame"] {
        background: var(--c-bg-1);
        border-radius: var(--r-md);
        border: none;
    }

    /* ── Inputs (focus state for accessibility) ── */
    div[data-baseweb="select"] > div,
    .stTextInput > div > div > input,
    .stNumberInput > div > div > input,
    .stTextArea textarea,
    .stDateInput > div > div > input {
        background: var(--c-bg-1) !important;
        border: 1px solid transparent !important;
        border-radius: var(--r-md) !important;
        color: var(--c-text-1) !important;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    div[data-baseweb="select"] > div:hover,
    .stTextInput > div > div > input:hover { background: var(--c-bg-2) !important; }
    .stTextInput > div > div > input:focus,
    .stNumberInput > div > div > input:focus,
    .stTextArea textarea:focus,
    .stDateInput > div > div > input:focus {
        border-color: var(--c-accent) !important;
        box-shadow: 0 0 0 3px var(--c-accent-soft) !important;
        outline: none;
    }

    /* ── Buttons — 4 explicit states (default, hover, active, disabled) ── */
    .stButton > button,
    .stDownloadButton > button,
    .stFormSubmitButton > button {
        background: transparent;
        color: var(--c-text-1);
        border: 1px solid var(--c-bg-3);
        border-radius: var(--r-md);
        padding: 9px 18px;
        font-weight: 500;
        transition: all 0.15s ease;
        box-shadow: none;
    }
    .stButton > button:hover,
    .stDownloadButton > button:hover,
    .stFormSubmitButton > button:hover {
        background: var(--c-bg-2);
        border-color: var(--c-accent);
        color: #ffffff;
    }
    .stButton > button:active,
    .stDownloadButton > button:active,
    .stFormSubmitButton > button:active {
        background: var(--c-bg-3);
        transform: translateY(1px);
    }
    .stButton > button:disabled,
    .stDownloadButton > button:disabled,
    .stFormSubmitButton > button:disabled {
        background: transparent !important;
        border-color: var(--c-bg-1) !important;
        color: var(--c-text-3) !important;
        cursor: not-allowed;
    }
    /* Primary button — filled accent */
    .stButton > button[kind="primary"],
    .stFormSubmitButton > button[kind="primary"] {
        background: var(--c-accent);
        color: var(--c-bg-0);
        border: 1px solid var(--c-accent);
        font-weight: 600;
        box-shadow: var(--shadow-1);
    }
    .stButton > button[kind="primary"]:hover,
    .stFormSubmitButton > button[kind="primary"]:hover {
        background: #81d4fa;
        border-color: #81d4fa;
        color: var(--c-bg-0);
        box-shadow: var(--shadow-2);
    }
    .stButton > button[kind="primary"]:active,
    .stFormSubmitButton > button[kind="primary"]:active { transform: translateY(1px); }

    /* ── Dividers ── */
    hr, [data-testid="stDivider"] { border-color: var(--c-bg-1) !important; opacity: 0.6; }

    /* ── Alerts (semantic colors) ── */
    [data-testid="stAlert"] { border-radius: var(--r-md); border: none; }
    [data-testid="stAlert"][data-baseweb="notification"] { background: var(--c-bg-1) !important; }

    /* ── Plotly — make charts blend into the deep blue ── */
    .js-plotly-plot, .plot-container { background: transparent !important; }

    /* ── Micro-interactions ── */
    @keyframes mm-fade-in {
        from { opacity: 0; transform: translateY(4px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    [data-testid="stMetric"], [data-testid="stDataFrame"] { animation: mm-fade-in 0.35s ease-out; }

    /* ── Mobile responsive ── */
    @media (max-width: 768px) {
        /* Stack columns vertically on mobile */
        [data-testid="column"] { width: 100% !important; flex: 100% !important; min-width: 100% !important; }
        /* Smaller fonts */
        .stMetric label { font-size: 10px !important; }
        .stMetric [data-testid="stMetricValue"] { font-size: 18px !important; }
        h1 { font-size: 24px !important; }
        h2, .stSubheader { font-size: 18px !important; }
        /* Compact sidebar */
        [data-testid="stSidebar"] { min-width: 220px !important; max-width: 220px !important; }
        /* Scrollable dataframes */
        [data-testid="stDataFrame"] { max-height: 400px; overflow: auto; }
        /* Full-width buttons */
        .stButton > button { width: 100%; }
        /* Smaller chart margins */
        .js-plotly-plot .plotly { margin: 0 !important; }
    }

    /* ── Tablet ── */
    @media (min-width: 769px) and (max-width: 1024px) {
        [data-testid="stSidebar"] { min-width: 250px !important; max-width: 250px !important; }
        h1 { font-size: 28px !important; }
    }

    /* ── Touch-friendly targets ── */
    @media (hover: none) and (pointer: coarse) {
        .stSelectbox, .stMultiSelect, .stSlider { min-height: 44px; }
        .stButton > button { min-height: 44px; font-size: 16px; }
        .stTextInput > div > input { min-height: 44px; }
    }
</style>
""", unsafe_allow_html=True)

# ── Google Analytics + AdSense ────────────────────────────────────────────
# Set env vars: GA_MEASUREMENT_ID (e.g. G-XXXXXXXXXX), ADSENSE_CLIENT (e.g. ca-pub-XXXXXXXX)
import os as _os
import streamlit.components.v1 as _components

_GA_ID = _os.getenv("GA_MEASUREMENT_ID", "")
_ADSENSE_ID = _os.getenv("ADSENSE_CLIENT", "")

_tracking_html = ""
if _GA_ID:
    _tracking_html += f"""
    <!-- Google Analytics (gtag.js) -->
    <script async src="https://www.googletagmanager.com/gtag/js?id={_GA_ID}"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());
      gtag('config', '{_GA_ID}');
    </script>
    """
if _ADSENSE_ID:
    _tracking_html += f"""
    <!-- Google AdSense -->
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={_ADSENSE_ID}"
            crossorigin="anonymous"></script>
    """
if _tracking_html:
    _components.html(_tracking_html, height=0)


def render_ad_unit(slot: str = "", ad_format: str = "auto", height: int = 100):
    """Render a Google AdSense ad unit. Call anywhere you want an ad banner.
    Set ADSENSE_CLIENT env var and pass your ad slot ID."""
    client = _os.getenv("ADSENSE_CLIENT", "")
    if not client or not slot:
        return
    _components.html(f"""
    <ins class="adsbygoogle"
         style="display:block"
         data-ad-client="{client}"
         data-ad-slot="{slot}"
         data-ad-format="{ad_format}"
         data-full-width-responsive="true"></ins>
    <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
    """, height=height)


# ── Lookback helper ────────────────────────────────────────────────────────
LOOKBACK_OPTIONS = {
    "3 Months": 63,
    "6 Months": 126,
    "9 Months": 189,
    "1 Year":   252,
    "2 Years":  504,
    "5 Years":  1260,
}

def metric_row(df: pd.DataFrame, definitions: list, lookback_days: int):
    """Render a row of st.metric cards comparing latest vs N days ago."""
    latest = df.iloc[-1]
    prev_idx = max(0, len(df) - 1 - lookback_days)
    prev = df.iloc[prev_idx]

    cols = st.columns(len(definitions))
    for col, (label, field, unit) in zip(cols, definitions):
        if field in df.columns:
            val = latest.get(field, None)
            prv = prev.get(field, None)
            if val is not None and not pd.isna(val):
                delta = round(val - prv, 3) if prv is not None and not pd.isna(prv) else None
                col.metric(
                    label=label,
                    value=f"{val:.3f} {unit}",
                    delta=f"{delta:+.3f}" if delta is not None else None,
                )


def main():
    init_session_state()
    render_sidebar_controls()
    render_page_header(current="Home")

    st.title("🏠 Home")
    st.markdown(
        '<p style="color:var(--c-text-2);font-size:15px;margin-top:-4px;">'
        "US Treasury · EUR / GBP / CHF · SOFR Swaps · Credit Spreads"
        "</p>",
        unsafe_allow_html=True,
    )

    # ── Quick-jump grid to every section (ghost cards on the 4-pt grid) ─
    st.markdown(
        """
<style>
.mm-jump-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 12px;
    margin: 24px 0 8px 0;
}
.mm-jump-card {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    background: var(--c-bg-1);
    border-radius: 10px;
    text-decoration: none;
    color: var(--c-text-1);
    font-size: 14px;
    font-weight: 500;
    box-shadow: 0 1px 2px rgba(0,0,0,0.10);
    transition: all 0.18s ease;
    border-left: 3px solid transparent;
}
.mm-jump-card:hover {
    background: var(--c-bg-2);
    transform: translateY(-2px);
    box-shadow: 0 4px 14px rgba(0,0,0,0.18);
    border-left-color: var(--c-accent);
    color: #ffffff;
}
.mm-jump-card:active { transform: translateY(0); }
.mm-jump-card.mm-jump-featured {
    background: var(--c-bg-2);
    border-left-color: var(--c-accent);
    box-shadow: 0 4px 14px rgba(0,0,0,0.18);
}
.mm-jump-card .mm-jump-emoji { font-size: 18px; }
</style>
<div class="mm-jump-grid">
  <a class="mm-jump-card mm-jump-featured" href="/Analysis"      target="_self"><span class="mm-jump-emoji">🔍</span> Trade Scanner ⭐</a>
  <a class="mm-jump-card" href="/Yield_Curve"   target="_self"><span class="mm-jump-emoji">📉</span> Yield Curve</a>
  <a class="mm-jump-card" href="/Spreads"       target="_self"><span class="mm-jump-emoji">📊</span> Spreads</a>
  <a class="mm-jump-card" href="/Regression"    target="_self"><span class="mm-jump-emoji">📐</span> Regression</a>
  <a class="mm-jump-card" href="/PCA"           target="_self"><span class="mm-jump-emoji">🧮</span> PCA</a>
  <a class="mm-jump-card" href="/Correlation"   target="_self"><span class="mm-jump-emoji">🔗</span> Correlation</a>
  <a class="mm-jump-card" href="/Vol_Surface"   target="_self"><span class="mm-jump-emoji">🌊</span> Vol Surface</a>
  <a class="mm-jump-card" href="/Trade_Tracker" target="_self"><span class="mm-jump-emoji">📒</span> Trade Tracker</a>
  <a class="mm-jump-card" href="/Alerts"        target="_self"><span class="mm-jump-emoji">🔔</span> Alerts</a>
  <a class="mm-jump-card" href="/Data_Sources"  target="_self"><span class="mm-jump-emoji">📡</span> Data Sources</a>
  <a class="mm-jump-card" href="/Glossary"      target="_self"><span class="mm-jump-emoji">📖</span> Glossary</a>
  <a class="mm-jump-card" href="/User_Guide"    target="_self"><span class="mm-jump-emoji">📘</span> User Guide</a>
  <a class="mm-jump-card" href="/Feature_Request" target="_self"><span class="mm-jump-emoji">💡</span> Feature Request</a>
</div>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

    # ── Lookback selector (top of page) ───────────────────────────────────
    lb_col, _ = st.columns([2, 5])
    with lb_col:
        lookback_label = st.select_slider(
            "📅 Lookback period (for Δ change on metrics)",
            options=list(LOOKBACK_OPTIONS.keys()),
            value="1 Year",
        )
    lookback_days = LOOKBACK_OPTIONS[lookback_label]

    st.divider()

    # ── Load data ─────────────────────────────────────────────────────────
    with st.spinner("Loading market data…"):
        df = get_master_df()

    if df.empty:
        st.error("❌ No data loaded. Check your internet connection and try refreshing.")
        return

    # Derived columns
    if "10Y" in df.columns and "2Y" in df.columns:
        df["2s10s"] = df["10Y"] - df["2Y"]
    if "30Y" in df.columns and "5Y" in df.columns:
        df["5s30s"] = df["30Y"] - df["5Y"]

    # ── US Treasury KPIs ───────────────────────────────────────────────────
    st.markdown('<p class="section-header">🇺🇸 US Treasury Yields</p>', unsafe_allow_html=True)
    metric_row(df, [
        ("1Y",          "1Y",   "%"),
        ("2Y",          "2Y",   "%"),
        ("5Y",          "5Y",   "%"),
        ("10Y",         "10Y",  "%"),
        ("30Y",         "30Y",  "%"),
        ("2s10s Spread","2s10s","pp"),
        ("5s30s Spread","5s30s","pp"),
    ], lookback_days)

    st.divider()

    # ── International yields ───────────────────────────────────────────────
    intl_definitions = []
    if "DE_10Y" in df.columns:
        intl_definitions.append(("🇩🇪 DE 10Y (EUR)", "DE_10Y", "%"))
    if "DE_2Y" in df.columns:
        intl_definitions.append(("🇩🇪 DE 2Y", "DE_2Y", "%"))
    if "GB_10Y" in df.columns:
        intl_definitions.append(("🇬🇧 UK 10Y (Gilt)", "GB_10Y", "%"))
    if "GB_2Y" in df.columns:
        intl_definitions.append(("🇬🇧 UK 2Y", "GB_2Y", "%"))
    if "CH_10Y" in df.columns:
        intl_definitions.append(("🇨🇭 CH 10Y (CHF)", "CH_10Y", "%"))
    if "JP_10Y" in df.columns:
        intl_definitions.append(("🇯🇵 JP 10Y (JGB)", "JP_10Y", "%"))
    if "ECB_RATE" in df.columns:
        intl_definitions.append(("🏦 ECB Rate", "ECB_RATE", "%"))

    if intl_definitions:
        st.markdown('<p class="section-header">🌍 International Government Yields</p>', unsafe_allow_html=True)
        metric_row(df, intl_definitions, lookback_days)
        st.divider()

    # ── SOFR / Credit KPIs ────────────────────────────────────────────────
    sofr_credit = []
    if "SOFR_10Y" in df.columns:
        sofr_credit.append(("SOFR Swap 10Y", "SOFR_10Y", "%"))
    if "SOFR_2Y" in df.columns:
        sofr_credit.append(("SOFR Swap 2Y",  "SOFR_2Y",  "%"))
    if "IG_OAS" in df.columns:
        sofr_credit.append(("IG OAS",         "IG_OAS",   "bps"))
    if "HY_OAS" in df.columns:
        sofr_credit.append(("HY OAS",         "HY_OAS",   "bps"))
    if "BBB_OAS" in df.columns:
        sofr_credit.append(("BBB OAS",        "BBB_OAS",  "bps"))
    if "VIX" in df.columns:
        sofr_credit.append(("VIX",            "VIX",      ""))

    if sofr_credit:
        st.markdown('<p class="section-header">💱 SOFR Swaps & Credit</p>', unsafe_allow_html=True)
        metric_row(df, sofr_credit, lookback_days)
        st.divider()

    # ── Filter df to lookback window for charts ────────────────────────────
    chart_start = df.index[-1] - pd.Timedelta(days=int(lookback_days * 1.45))
    df_chart = df[df.index >= chart_start]

    # ── US Yield Curve Snapshot ────────────────────────────────────────────
    col1, col2 = st.columns([3, 2])

    with col1:
        st.subheader("📊 US Yield Curve — Snapshot")
        avail_tenors = [t for t in TENOR_LABELS if t in df.columns]
        latest       = df.iloc[-1]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=avail_tenors,
            y=[latest.get(t, None) for t in avail_tenors],
            mode="lines+markers",
            name=f"Today ({df.index[-1].strftime('%d %b %Y')})",
            line=dict(color="#00D4FF", width=2.5),
            marker=dict(size=8),
        ))
        prev_row = df.iloc[max(0, len(df)-1-lookback_days)]
        fig.add_trace(go.Scatter(
            x=avail_tenors,
            y=[prev_row.get(t, None) for t in avail_tenors],
            mode="lines+markers",
            name=f"{lookback_label} Ago",
            line=dict(color="#FF6B6B", width=2, dash="dash"),
            marker=dict(size=6),
        ))
        fig.update_layout(
            template=PLOTLY_THEME, hovermode="x unified",
            xaxis_title="Tenor", yaxis_title="Yield (%)",
            height=340, margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("🌍 Intl 10Y Yields — Snapshot")
        intl_10y = {
            "🇺🇸 US":  "10Y",
            "🇩🇪 DE":  "DE_10Y",
            "🇬🇧 UK":  "GB_10Y",
            "🇨🇭 CH":  "CH_10Y",
            "🇯🇵 JP":  "JP_10Y",
        }
        labels_bar, vals_bar, colors_bar = [], [], []
        colors_list = ["#00D4FF","#FFD93D","#FF6B6B","#6BCB77","#FF9F40"]
        for i, (lbl, col_name) in enumerate(intl_10y.items()):
            if col_name in df.columns:
                v = df[col_name].dropna()
                if not v.empty:
                    labels_bar.append(lbl)
                    vals_bar.append(round(v.iloc[-1], 3))
                    colors_bar.append(colors_list[i % len(colors_list)])
        if vals_bar:
            fig_bar = go.Figure(go.Bar(
                x=labels_bar, y=vals_bar,
                marker_color=colors_bar,
                text=[f"{v:.2f}%" for v in vals_bar],
                textposition="outside",
            ))
            fig_bar.update_layout(
                template=PLOTLY_THEME, yaxis_title="Yield (%)",
                height=340, margin=dict(l=10, r=10, t=10, b=10),
                showlegend=False,
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("International yield data loading — refresh in a moment.")

    st.divider()

    # ── 10Y History chart — US vs international ────────────────────────────
    st.subheader(f"📈 10Y Yield History — Last {lookback_label}")
    fig2 = go.Figure()
    series_10y = [
        ("🇺🇸 US 10Y",  "10Y",    "#00D4FF"),
        ("🇩🇪 DE 10Y",  "DE_10Y", "#FFD93D"),
        ("🇬🇧 UK 10Y",  "GB_10Y", "#FF6B6B"),
        ("🇨🇭 CH 10Y",  "CH_10Y", "#6BCB77"),
        ("🇯🇵 JP 10Y",  "JP_10Y", "#FF9F40"),
    ]
    for name, col_name, color in series_10y:
        if col_name in df_chart.columns:
            s = df_chart[col_name].dropna()
            if not s.empty:
                fig2.add_trace(go.Scatter(
                    x=s.index, y=s.values, mode="lines",
                    name=name, line=dict(color=color, width=1.8),
                ))
    fig2.update_layout(
        template=PLOTLY_THEME, hovermode="x unified",
        xaxis_title="Date", yaxis_title="Yield (%)",
        height=350, margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig2, use_container_width=True)

    # ── 2s10s spread history ───────────────────────────────────────────────
    if "2s10s" in df_chart.columns:
        st.subheader(f"📉 US 2s10s Spread — Last {lookback_label}")
        s = df_chart["2s10s"].dropna()
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines",
            name="2s10s", line=dict(color="#FFD93D", width=1.8),
            fill="tozeroy",
            fillcolor="rgba(255,217,61,0.07)",
        ))
        fig3.add_hline(y=0, line_dash="dot", line_color="white", opacity=0.4)
        fig3.update_layout(
            template=PLOTLY_THEME, hovermode="x unified",
            xaxis_title="Date", yaxis_title="Spread (pp)",
            height=280, margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig3, use_container_width=True)

    # ── Substack / links ────────────────────────────────────────────────────
    st.divider()
    link_cols = st.columns([1, 1, 1, 4])
    with link_cols[0]:
        st.link_button("Macro Manv Substack", "https://manveersahota.substack.com/?utm_campaign=profile_chips", use_container_width=True)
    with link_cols[1]:
        st.link_button("Subscribe", "https://manveersahota.substack.com/subscribe", use_container_width=True)
    with link_cols[2]:
        st.link_button("Contact", "mailto:ratesteam@macromanv.com", use_container_width=True)

    # ── Tutorial button ────────────────────────────────────────────────────
    st.divider()
    render_tutorial_button(key_suffix="home")

    # ── Data info footer ───────────────────────────────────────────────────
    st.divider()
    st.caption(
        f"Data range: **{df.index[0].strftime('%d %b %Y')}** → **{df.index[-1].strftime('%d %b %Y')}** "
        f"| {len(df):,} trading days | {df.shape[1]} series "
        f"| Sources: US Treasury · FRED (ICE SOFR, ICE BofA, OECD)"
    )

    # ── Tutorial (must be LAST — renders after all content) ────────────
    render_tutorial(page="home")


if __name__ == "__main__":
    main()
