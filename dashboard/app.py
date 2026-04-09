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
from dashboard.state import get_master_df, init_session_state
from dashboard.tutorial import render_tutorial_button, render_tutorial

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(
    page_title="Rates Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "**Rates Dashboard** — Global Rates & Spread Analysis"},
)

st.markdown("""
<style>
    /* ── Base styles ── */
    .stMetric label { font-size: 12px !important; color: #8892a4 !important; }
    [data-testid="stSidebar"] { background-color: #161b27; }
    .section-header { font-size: 14px; font-weight: 600; color: #8892a4;
                      text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }

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

    st.title("📈 Rates Dashboard")
    st.markdown("### US Treasury · EUR/GBP/CHF · SOFR Swaps · Credit Spreads")
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
