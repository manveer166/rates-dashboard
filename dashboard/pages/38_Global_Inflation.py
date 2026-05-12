"""Page 38 — Global Inflation Tracker (OpenBB).

Cross-country headline CPI + unemployment via OECD/OpenBB.  Combines with
our existing US TIPS / breakevens so you can read realised inflation
against what markets are pricing.

Why this matters for rates: inflation differentials drive cross-market
real-rate / FX trades. UK CPI persistently above EU CPI explains why
gilts trade through Bunds.  This page makes that comparison visual.

Keyless — uses only OECD (no API key needed).  First load ~3s.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import get_master_df, init_session_state, password_gate

st.set_page_config(page_title="Global Inflation", page_icon="🔥", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Global Inflation")

st.title("🔥 Global Inflation Tracker")
st.caption(
    "Cross-country headline CPI, year-on-year, via OECD/OpenBB. "
    "Overlaid against US 5Y/10Y breakevens for a realised-vs-priced read."
)
st.divider()


COUNTRIES = {
    "United States":  "united_states",
    "Euro Area":      "euro_area",
    "United Kingdom": "united_kingdom",
    "Germany":        "germany",
    "France":         "france",
    "Italy":          "italy",
    "Japan":          "japan",
    "Canada":         "canada",
}


@st.cache_data(ttl=24 * 3600, show_spinner="Pulling OECD CPI via OpenBB…")
def _fetch_cpi(codes_csv: str, transform: str, years: int) -> pd.DataFrame:
    from data.openbb_data import cpi
    start = (datetime.today() - timedelta(days=years * 365)).strftime("%Y-%m-%d")
    return cpi(tuple(codes_csv.split(",")), start=start, transform=transform)


@st.cache_data(ttl=24 * 3600, show_spinner="Pulling unemployment via OpenBB…")
def _fetch_unemp(codes_csv: str, years: int) -> pd.DataFrame:
    from data.openbb_data import unemployment
    start = (datetime.today() - timedelta(days=years * 365)).strftime("%Y-%m-%d")
    return unemployment(tuple(codes_csv.split(",")), start=start)


# ── Inputs ────────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    selected = st.multiselect(
        "Countries", list(COUNTRIES.keys()),
        default=["United States", "Euro Area", "United Kingdom", "Japan"],
    )
with c2:
    transform = st.selectbox("Transform",
                              [("YoY %", "yoy"), ("MoM %", "mom"), ("Index", "index")],
                              format_func=lambda x: x[0])
    tf_key = transform[1]
with c3:
    years_back = st.slider("Years", 1, 15, 5, key="cpi_years")

codes = [COUNTRIES[l] for l in selected] if selected else ["united_states"]
df = _fetch_cpi(",".join(codes), tf_key, years_back)

if df.empty:
    st.warning("OECD CPI unavailable right now — try again in a moment.")
    st.stop()


# ── Multi-country CPI chart ───────────────────────────────────────────────
st.subheader(f"📈 Headline CPI — {transform[0]}")

palette = ["#4fc3f7", "#fb923c", "#a78bfa", "#4ade80", "#fbbf24", "#f472b6", "#f87171", "#22d3ee"]

fig = go.Figure()
if "country" in df.columns and "value" in df.columns:
    for i, c in enumerate(sorted(df["country"].unique())):
        sub = df[df["country"] == c].sort_index()
        fig.add_trace(go.Scatter(
            x=sub.index, y=sub["value"], name=c,
            line=dict(color=palette[i % len(palette)], width=2),
        ))
if tf_key in ("yoy", "mom"):
    fig.add_hline(y=2.0, line_dash="dash", line_color="#4ade80",
                   annotation_text="Most CB targets 2%",
                   annotation_position="right")
    fig.add_hline(y=0, line_dash="dot", line_color="#94a8c9")
fig.update_layout(template=PLOTLY_THEME, height=440, hovermode="x unified",
                  yaxis_title=transform[0], margin=dict(l=10, r=10, t=10, b=10),
                  legend=dict(orientation="h", yanchor="bottom", y=1.02,
                              xanchor="right", x=1))
st.plotly_chart(fig, use_container_width=True)


# ── Snapshot table ───────────────────────────────────────────────────────
st.markdown("**📍 Latest readings**")
rows = []
if "country" in df.columns and "value" in df.columns:
    for c in sorted(df["country"].unique()):
        sub = df[df["country"] == c].sort_index()
        if sub.empty: continue
        last_v = float(sub.iloc[-1]["value"])
        # 12m change vs same metric a year ago (if YoY) or vs 12mo ago index
        prev_idx = max(0, len(sub) - 13)
        delta_12m = float(last_v - sub.iloc[prev_idx]["value"]) if len(sub) > 12 else None
        rows.append({
            "Country":    c,
            "Latest":     round(last_v, 2),
            "Δ 12m":      round(delta_12m, 2) if delta_12m is not None else "—",
            "vs 2% target": round(last_v - 2.0, 2) if tf_key == "yoy" else "—",
            "Date":       sub.index[-1].strftime("%Y-%m"),
        })
st.dataframe(pd.DataFrame(rows).set_index("Country"), use_container_width=True)

st.divider()


# ── Realised CPI vs market-priced breakevens (US only) ───────────────────
st.subheader("🎯 US realised CPI vs market-priced breakevens")
st.caption(
    "**The gap matters:** when realised CPI is above breakevens, markets are "
    "underpricing future inflation — TIPS look cheap. When realised is below, "
    "breakevens are pricing inflation premium that may not materialise."
)

mdf = get_master_df()
if mdf.empty or "BREAKEVEN_5Y" not in mdf.columns:
    st.info("US breakevens not in cache — refresh data.")
else:
    us_cpi = df[df.get("country", "") == "United States"].sort_index() \
             if "country" in df.columns else pd.DataFrame()
    if us_cpi.empty:
        st.info("US not selected above — pick 'United States' to see this comparison.")
    else:
        five_be = mdf["BREAKEVEN_5Y"].dropna()
        ten_be  = mdf["BREAKEVEN_10Y"].dropna()
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=us_cpi.index, y=us_cpi["value"], name="US CPI YoY",
                                   line=dict(color="#f87171", width=2.5)))
        fig2.add_trace(go.Scatter(x=five_be.index, y=five_be.values, name="5Y breakeven",
                                   line=dict(color="#fbbf24", width=1.8, dash="dash")))
        fig2.add_trace(go.Scatter(x=ten_be.index, y=ten_be.values, name="10Y breakeven",
                                   line=dict(color="#fb923c", width=1.8, dash="dash")))
        fig2.add_hline(y=2.0, line_dash="dot", line_color="#4ade80",
                        annotation_text="Fed 2% target", annotation_position="right")
        fig2.update_layout(template=PLOTLY_THEME, height=380, hovermode="x unified",
                            yaxis_title="% YoY", margin=dict(l=10, r=10, t=10, b=10),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                        xanchor="right", x=1))
        st.plotly_chart(fig2, use_container_width=True)

        # Current gap
        if not us_cpi.empty and not five_be.empty:
            latest_cpi = float(us_cpi.iloc[-1]["value"])
            latest_be5 = float(five_be.iloc[-1])
            latest_be10 = float(ten_be.iloc[-1])
            gap5 = latest_cpi - latest_be5
            gap10 = latest_cpi - latest_be10
            m1, m2, m3 = st.columns(3)
            m1.metric("US CPI YoY", f"{latest_cpi:.2f}%")
            m2.metric("CPI vs 5Y BE", f"{gap5:+.2f}pp",
                       delta="CPI > pricing" if gap5 > 0 else "pricing > CPI")
            m3.metric("CPI vs 10Y BE", f"{gap10:+.2f}pp",
                       delta="CPI > pricing" if gap10 > 0 else "pricing > CPI")


# ── Unemployment side panel ──────────────────────────────────────────────
st.divider()
st.subheader("👷 Unemployment rates (OECD-harmonised)")

unemp = _fetch_unemp(",".join(codes), years_back)
if unemp.empty:
    st.info("Unemployment data unavailable right now.")
else:
    fig3 = go.Figure()
    if "country" in unemp.columns and "value" in unemp.columns:
        for i, c in enumerate(sorted(unemp["country"].unique())):
            sub = unemp[unemp["country"] == c].sort_index()
            fig3.add_trace(go.Scatter(x=sub.index, y=sub["value"], name=c,
                                       line=dict(color=palette[i % len(palette)], width=2)))
    fig3.update_layout(template=PLOTLY_THEME, height=340, hovermode="x unified",
                       yaxis_title="Unemployment rate (%)",
                       margin=dict(l=10, r=10, t=10, b=10),
                       legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                    xanchor="right", x=1))
    st.plotly_chart(fig3, use_container_width=True)

st.divider()
st.caption(
    "Data via OECD through OpenBB. CPI is monthly, released with ~1-month lag. "
    "Unemployment monthly, also lagged ~1 month. "
    "US breakevens from FRED `T5YIE` / `T10YIE` — daily."
)
