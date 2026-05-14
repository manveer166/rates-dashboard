"""Page 18 — Cross-Asset 1-pager.

Snapshot of credit (IG/HY/BB/EM OAS), equity vol (VIX), and rates (10Y, 2Y,
SOFR, EFFR) on a single screen. Useful for a 'what's the market doing'
context check before drilling into the rates pages.
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

st.set_page_config(page_title="Cross-Asset", page_icon="🌐", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Cross-Asset")

st.title("🌐 Cross-Asset 1-Pager")
st.markdown(
    "Credit spreads, equity vol, and rates on a single screen — the regime "
    "context for any rates trade."
)
st.divider()

df = get_master_df()
if df.empty:
    st.error("No data — refresh the cache.")
    st.stop()

# ── Helper: 1-month change in bps for spread/yield series ─────────────────
def _delta_bps(col, days=22):
    if col not in df.columns:
        return None
    s = df[col].dropna()
    if len(s) < days + 1:
        return None
    return float(s.iloc[-1] - s.iloc[-days - 1]) * 100

def _z_1y(col):
    if col not in df.columns:
        return None
    s = df[col].dropna().tail(252)
    if len(s) < 60 or s.std() == 0:
        return None
    return float((s.iloc[-1] - s.mean()) / s.std())

def _last(col):
    if col not in df.columns:
        return None
    s = df[col].dropna()
    return float(s.iloc[-1]) if len(s) else None

# ── Top metric strip ──────────────────────────────────────────────────────
st.subheader("📍 Snapshot")
from dashboard.components.signal_card import render_market_kpi_row
ca_specs = [
    ("VIX",    "VIX",    "{:.1f}",  "vol pts",         "1m",        "#f87171"),
    ("IG_OAS", "IG OAS", "{:.2f}%", "% (annualised)",  "1m bps",    "#4fc3f7"),
    ("HY_OAS", "HY OAS", "{:.2f}%", "% (annualised)",  "1m bps",    "#fb923c"),
    ("10Y",    "10Y UST","{:.2f}%", "% (annualised)",  "1m bps",    "#a78bfa"),
    ("2Y",     "2Y UST", "{:.2f}%", "% (annualised)",  "1m bps",    "#fbbf24"),
]
ca_items = []
for col, name, fmt, unit, lbl, color in ca_specs:
    val = _last(col)
    if val is None:
        ca_items.append({"label": name, "value": "—", "unit": unit, "color": color})
        continue
    if "bps" in lbl:
        d = _delta_bps(col)
        d_str = f"{d:+.0f} bps (1m)" if d is not None else None
    else:
        s = df[col].dropna()
        d = float(s.iloc[-1] - s.iloc[-22]) if len(s) > 22 else None
        d_str = f"{d:+.1f} (1m)" if d is not None else None
    ca_items.append({"label": name, "value": fmt.format(val),
                      "unit": unit, "delta": d_str, "color": color})
render_market_kpi_row(ca_items)

st.divider()

# ── Chart grid: 2x2 ───────────────────────────────────────────────────────
st.subheader("📊 Last 12 months")
window = df.tail(252)

g1c1, g1c2 = st.columns(2)

with g1c1:
    st.markdown("**Credit spreads (bps)**")
    fig = go.Figure()
    for col, name, color in [
        ("IG_OAS", "IG",  "#4fc3f7"),
        ("BB_OAS", "BB",  "#fbbf24"),
        ("HY_OAS", "HY",  "#fb923c"),
        ("EM_OAS", "EM",  "#a78bfa"),
    ]:
        if col in window.columns:
            fig.add_trace(go.Scatter(
                x=window.index, y=window[col] * 100, name=name,
                line=dict(color=color, width=1.8),
            ))
    fig.update_layout(template=PLOTLY_THEME, height=320, hovermode="x unified",
                      margin=dict(l=10, r=10, t=20, b=10),
                      yaxis_title="OAS (bps)")
    st.plotly_chart(fig, use_container_width=True)

with g1c2:
    st.markdown("**VIX (equity vol)**")
    fig = go.Figure()
    if "VIX" in window.columns:
        fig.add_trace(go.Scatter(
            x=window.index, y=window["VIX"], name="VIX",
            line=dict(color="#f87171", width=1.8), fill="tozeroy",
            fillcolor="rgba(248,113,113,0.10)",
        ))
        # 12mo mean as ref
        fig.add_hline(y=float(window["VIX"].mean()), line_dash="dash",
                      line_color="#94a8c9",
                      annotation_text=f"12mo avg {window['VIX'].mean():.1f}",
                      annotation_position="right")
    fig.update_layout(template=PLOTLY_THEME, height=320, hovermode="x unified",
                      margin=dict(l=10, r=10, t=20, b=10),
                      yaxis_title="VIX")
    st.plotly_chart(fig, use_container_width=True)

g2c1, g2c2 = st.columns(2)

with g2c1:
    st.markdown("**US Treasuries (yields)**")
    fig = go.Figure()
    for col, name, color in [
        ("2Y",  "2Y",  "#fb923c"),
        ("5Y",  "5Y",  "#fbbf24"),
        ("10Y", "10Y", "#4fc3f7"),
        ("30Y", "30Y", "#a78bfa"),
    ]:
        if col in window.columns:
            fig.add_trace(go.Scatter(
                x=window.index, y=window[col], name=name,
                line=dict(color=color, width=1.8),
            ))
    fig.update_layout(template=PLOTLY_THEME, height=320, hovermode="x unified",
                      margin=dict(l=10, r=10, t=20, b=10),
                      yaxis_title="Yield (%)")
    st.plotly_chart(fig, use_container_width=True)

with g2c2:
    st.markdown("**Money market (overnight)**")
    fig = go.Figure()
    for col, name, color in [
        ("SOFR", "SOFR", "#4fc3f7"),
        ("EFFR", "EFFR", "#fb923c"),
    ]:
        if col in window.columns:
            fig.add_trace(go.Scatter(
                x=window.index, y=window[col], name=name,
                line=dict(color=color, width=1.8),
            ))
    fig.update_layout(template=PLOTLY_THEME, height=320, hovermode="x unified",
                      margin=dict(l=10, r=10, t=20, b=10),
                      yaxis_title="Overnight rate (%)")
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ── Cross-asset z-score heatmap ───────────────────────────────────────────
st.subheader("🌡️ 1Y Z-score heatmap")
st.caption(
    "Where each series sits relative to its 1-year history. "
    "Cheap (negative Z) is green for spreads/vol; tight/rich (positive Z) is red."
)
z_specs = [
    ("Equity vol",   "VIX"),
    ("IG OAS",       "IG_OAS"),
    ("HY OAS",       "HY_OAS"),
    ("BB OAS",       "BB_OAS"),
    ("EM OAS",       "EM_OAS"),
    ("10Y nominal",  "10Y"),
    ("2Y nominal",   "2Y"),
    ("SOFR",         "SOFR"),
]
rows = []
for label, col in z_specs:
    z = _z_1y(col)
    val = _last(col)
    rows.append({
        "Series":  label,
        "Current": "—" if val is None else (f"{val:.1f}" if col == "VIX" else f"{val:.2f}%"),
        "1Y mean": "—" if col not in df.columns else
                   (f"{df[col].dropna().tail(252).mean():.1f}" if col == "VIX"
                    else f"{df[col].dropna().tail(252).mean():.2f}%"),
        "Z-score": "—" if z is None else f"{z:+.2f}",
    })
zdf = pd.DataFrame(rows).set_index("Series")

def _color_z(val):
    try:
        z = float(val)
    except (TypeError, ValueError):
        return ""
    if z > 1.5:    return "background-color:#7f1d1d;color:white"
    if z > 1.0:    return "background-color:#431407;color:white"
    if z < -1.5:   return "background-color:#166534;color:white"
    if z < -1.0:   return "background-color:#14532d;color:white"
    return ""

st.dataframe(
    zdf.style.applymap(_color_z, subset=["Z-score"]),
    use_container_width=True,
)

st.caption(
    "Tip: When credit and equity vol Z's diverge from rates Z's, that's "
    "usually a cleaner regime signal than rates alone."
)
