"""Page 17 — Real Rates & Inflation Breakevens.

Shows TIPS yields, 5Y/10Y breakevens, and the implied inflation premium vs
nominal Treasuries. Uses data already pulled by FREDFetcher (DFII10, T5YIE, T10YIE).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import get_master_df, init_session_state, password_gate

st.set_page_config(page_title="Real Rates", page_icon="📉", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Real Rates")

st.title("📉 Real Rates & Breakevens")
st.markdown(
    "10Y TIPS real yield, 5Y/10Y inflation breakevens, and the implied "
    "inflation premium relative to nominal Treasuries."
)
st.divider()

df = get_master_df()
if df.empty:
    st.error("No data available — refresh the cache.")
    st.stop()

# ── Identify available series ─────────────────────────────────────────────
COLS = {c: c for c in ["TIPS_10Y", "BREAKEVEN_5Y", "BREAKEVEN_10Y", "10Y", "5Y"]
        if c in df.columns}
if "TIPS_10Y" not in COLS:
    st.warning("TIPS / breakeven series not in cache. Run a data refresh first.")
    st.stop()

# Compute implied 10Y inflation expectation = nominal - real
implied_10y = (df["10Y"] - df["TIPS_10Y"]) if "10Y" in COLS else None

# ── Snapshot ──────────────────────────────────────────────────────────────
last = df.dropna(subset=list(COLS.values()), how="all").iloc[-1]

def _delta(col):
    s = df[col].dropna()
    if len(s) >= 22:
        return float(s.iloc[-1] - s.iloc[-22]) * 100  # bps over ~1m
    return None

from dashboard.components.signal_card import render_market_kpi_row
items = []
if "TIPS_10Y" in COLS:
    d = _delta("TIPS_10Y")
    items.append({"label": "10Y Real (TIPS)", "value": f"{last['TIPS_10Y']:.2f}%",
                  "unit": "% (annualised)",
                  "delta": f"{d:+.0f} bps (1m)" if d is not None else None,
                  "color": "#4fc3f7"})
if "BREAKEVEN_5Y" in COLS:
    d = _delta("BREAKEVEN_5Y")
    items.append({"label": "5Y Breakeven", "value": f"{last['BREAKEVEN_5Y']:.2f}%",
                  "unit": "% YoY",
                  "delta": f"{d:+.0f} bps (1m)" if d is not None else None,
                  "color": "#fbbf24"})
if "BREAKEVEN_10Y" in COLS:
    d = _delta("BREAKEVEN_10Y")
    items.append({"label": "10Y Breakeven", "value": f"{last['BREAKEVEN_10Y']:.2f}%",
                  "unit": "% YoY",
                  "delta": f"{d:+.0f} bps (1m)" if d is not None else None,
                  "color": "#fb923c"})
if "10Y" in COLS:
    d = _delta("10Y")
    items.append({"label": "10Y Nominal", "value": f"{float(last['10Y']):.2f}%",
                  "unit": "% (annualised)",
                  "delta": f"{d:+.0f} bps (1m)" if d is not None else None,
                  "color": "#a78bfa"})
render_market_kpi_row(items)

st.divider()

# ── Real-yield time series ────────────────────────────────────────────────
st.subheader("10Y TIPS real yield — history")
fig1 = go.Figure()
fig1.add_trace(go.Scatter(
    x=df.index, y=df["TIPS_10Y"], name="10Y TIPS",
    line=dict(color="#4fc3f7", width=2),
))
# Zero line is a meaningful reference for real rates
fig1.add_hline(y=0, line_dash="dot", line_color="#94a8c9", line_width=1,
               annotation_text="Zero real rate", annotation_position="right")
fig1.update_layout(template=PLOTLY_THEME, height=380, hovermode="x unified",
                   xaxis_title="", yaxis_title="Real yield (%)",
                   margin=dict(l=10, r=10, t=20, b=10))
st.plotly_chart(fig1, use_container_width=True)

# ── Breakevens ────────────────────────────────────────────────────────────
st.subheader("Inflation breakevens — 5Y vs 10Y")
fig2 = go.Figure()
if "BREAKEVEN_5Y" in COLS:
    fig2.add_trace(go.Scatter(
        x=df.index, y=df["BREAKEVEN_5Y"], name="5Y breakeven",
        line=dict(color="#fbbf24", width=2),
    ))
if "BREAKEVEN_10Y" in COLS:
    fig2.add_trace(go.Scatter(
        x=df.index, y=df["BREAKEVEN_10Y"], name="10Y breakeven",
        line=dict(color="#fb923c", width=2),
    ))
# Fed's 2% target as a reference line
fig2.add_hline(y=2.0, line_dash="dash", line_color="#4ade80", line_width=1,
               annotation_text="Fed 2% target", annotation_position="right")
fig2.update_layout(template=PLOTLY_THEME, height=380, hovermode="x unified",
                   xaxis_title="", yaxis_title="Breakeven (%)",
                   margin=dict(l=10, r=10, t=20, b=10))
st.plotly_chart(fig2, use_container_width=True)

# ── 5y-5y forward breakeven (long-term inflation expectations) ────────────
if "BREAKEVEN_5Y" in COLS and "BREAKEVEN_10Y" in COLS:
    st.subheader("5Y5Y forward breakeven — long-run inflation expectations")
    # 5y5y = (10*BE10 - 5*BE5) / 5
    fwd_5y5y = (10 * df["BREAKEVEN_10Y"] - 5 * df["BREAKEVEN_5Y"]) / 5
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(
        x=df.index, y=fwd_5y5y, name="5Y5Y forward breakeven",
        line=dict(color="#a78bfa", width=2),
    ))
    fig3.add_hline(y=2.0, line_dash="dash", line_color="#4ade80", line_width=1,
                   annotation_text="Fed 2% target", annotation_position="right")
    fig3.update_layout(template=PLOTLY_THEME, height=320, hovermode="x unified",
                       xaxis_title="", yaxis_title="5Y5Y breakeven (%)",
                       margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig3, use_container_width=True)
    st.caption(
        "5Y5Y forward = the implied 5-year inflation expectation 5 years forward — "
        "a cleaner read on long-run inflation expectations than the spot 10Y."
    )

st.divider()

# ── Z-score panel ─────────────────────────────────────────────────────────
st.subheader("📐 1Y z-scores")
def _z(col, window=252):
    s = df[col].dropna().tail(window)
    if len(s) < 60:
        return None
    return float((s.iloc[-1] - s.mean()) / s.std()) if s.std() > 0 else None

zrows = []
for label, col in [("10Y Real (TIPS)", "TIPS_10Y"),
                   ("5Y Breakeven",   "BREAKEVEN_5Y"),
                   ("10Y Breakeven",  "BREAKEVEN_10Y"),
                   ("10Y Nominal",    "10Y")]:
    if col in COLS:
        z = _z(col)
        zrows.append({
            "Series": label,
            "Current": f"{float(last[col]):.2f}%",
            "1Y mean": f"{df[col].dropna().tail(252).mean():.2f}%",
            "Z-score": f"{z:+.2f}" if z is not None else "—",
        })
st.dataframe(pd.DataFrame(zrows).set_index("Series"), use_container_width=True)
