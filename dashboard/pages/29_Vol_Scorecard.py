"""Page 29 — Rates Vol Scorecard.

Tracks realised yield volatility across the curve at multiple windows
(1m / 3m / 1y) plus a 1-year-percentile read so you can see whether vol is
extreme or quiet.  Uses existing yield data — no MOVE needed.

(Implied vol via MOVE requires a paid FRED key; the realised vol read is
usually a better signal anyway because realised lags implied.)
"""

from __future__ import annotations  # PEP 604 unions on Python 3.9

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

st.set_page_config(page_title="Vol Scorecard", page_icon="🌊", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Vol Scorecard")

st.title("🌊 Rates Vol Scorecard")
st.caption(
    "Realised yield volatility (annualised bps) across the curve, with "
    "1Y percentile so you know whether you're pricing a calm or noisy regime."
)
st.divider()

df = get_master_df()
if df.empty:
    st.error("No master data — refresh the cache.")
    st.stop()

ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
present = [t for t in ALL_TENORS if t in df.columns]

WINDOWS = [("1m", 21), ("3m", 63), ("1y", 252)]


def realised_vol_bps(yld: pd.Series, window_days: int) -> pd.Series:
    """Annualised realised vol in bps, computed on daily yield changes."""
    chg_bps = yld.diff().dropna() * 100  # bps per day
    return chg_bps.rolling(window_days).std() * np.sqrt(252)


def percentile_1y(series: pd.Series) -> float | None:
    s = series.dropna().tail(252)
    if len(s) < 60: return None
    return float((s <= s.iloc[-1]).mean() * 100)


# ── Snapshot table ────────────────────────────────────────────────────────
st.subheader("📊 Realised vol — current vs 1Y history")
rows = []
for t in present:
    s = df[t].dropna()
    if len(s) < 65: continue
    row = {"Tenor": t, "Yield (%)": f"{s.iloc[-1]:.2f}"}
    for label, w in WINDOWS:
        rv_series = realised_vol_bps(s, w)
        cur = float(rv_series.iloc[-1]) if not rv_series.empty and pd.notna(rv_series.iloc[-1]) else None
        pct = percentile_1y(rv_series)
        row[f"{label} vol (bps)"]  = f"{cur:.1f}" if cur is not None else "—"
        row[f"{label} pctile"]     = f"{pct:.0f}%" if pct is not None else "—"
    rows.append(row)

vol_df = pd.DataFrame(rows).set_index("Tenor")
st.dataframe(vol_df, use_container_width=True)
st.caption(
    "Percentile = where today's vol sits in the last 252 trading days. "
    "≥85th percentile flags an unusually noisy regime; ≤15th flags an unusually quiet one."
)

st.divider()

# ── Time series — 3m realised vol per tenor ──────────────────────────────
st.subheader("📈 3-month realised vol — last 12 months")
fig = go.Figure()
palette = ["#fb923c", "#fbbf24", "#4ade80", "#4fc3f7", "#a78bfa", "#f472b6", "#f87171"]
for i, t in enumerate(present):
    s = df[t].dropna()
    rv = realised_vol_bps(s, 63).dropna().tail(252)
    if rv.empty: continue
    fig.add_trace(go.Scatter(x=rv.index, y=rv.values, name=t,
                              line=dict(color=palette[i % len(palette)], width=1.6)))
fig.update_layout(template=PLOTLY_THEME, height=420, hovermode="x unified",
                  yaxis_title="3m realised vol (annualised bps)",
                  margin=dict(l=10, r=10, t=10, b=10),
                  legend=dict(orientation="h", yanchor="bottom", y=1.02,
                              xanchor="right", x=1))
st.plotly_chart(fig, use_container_width=True)

# ── Vol spread between tenors (rich/cheap term structure of vol) ──────────
st.divider()
st.subheader("📐 Vol term structure — long-end vol vs front-end vol")
if "2Y" in df.columns and "10Y" in df.columns:
    rv2  = realised_vol_bps(df["2Y"].dropna(),  63).dropna()
    rv10 = realised_vol_bps(df["10Y"].dropna(), 63).dropna()
    common = rv2.index.intersection(rv10.index)
    if len(common) >= 60:
        ratio = (rv10.loc[common] / rv2.loc[common]).tail(252)
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=ratio.index, y=ratio.values,
                                   line=dict(color="#4fc3f7", width=2)))
        fig2.add_hline(y=ratio.mean(), line_dash="dash", line_color="#94a8c9",
                        annotation_text=f"1Y mean {ratio.mean():.2f}",
                        annotation_position="right")
        fig2.add_hline(y=1.0, line_dash="dot", line_color="#6a7e9e",
                        annotation_text="Equal", annotation_position="left")
        fig2.update_layout(template=PLOTLY_THEME, height=320,
                            margin=dict(l=10, r=10, t=10, b=10),
                            yaxis_title="10Y vol / 2Y vol")
        st.plotly_chart(fig2, use_container_width=True)
        c = (ratio.iloc[-1] - ratio.mean()) / ratio.std() if ratio.std() > 0 else 0
        st.caption(
            f"Current 10Y/2Y vol ratio: **{ratio.iloc[-1]:.2f}** "
            f"(1Y z = **{c:+.2f}**). Above 1.0 = long-end vol > front-end "
            "(typical) — well above 1.5 suggests duration scare; "
            "below 1.0 = front-end driving (Fed-driven repricing)."
        )

st.divider()

# ── Realised vs equity vol cross-context ─────────────────────────────────
st.subheader("🌐 Rates vol vs equity vol")
if "VIX" in df.columns and "10Y" in df.columns:
    rv10 = realised_vol_bps(df["10Y"].dropna(), 63).dropna().tail(252)
    vix  = df["VIX"].reindex(rv10.index).ffill().dropna()
    common = rv10.index.intersection(vix.index)
    if len(common) >= 60:
        f3 = make_subplots(specs=[[{"secondary_y": True}]])
        f3.add_trace(go.Scatter(x=common, y=rv10.loc[common], name="10Y realised vol (bps)",
                                line=dict(color="#4fc3f7", width=1.8)),
                     secondary_y=False)
        f3.add_trace(go.Scatter(x=common, y=vix.loc[common], name="VIX",
                                line=dict(color="#f87171", width=1.6, dash="dash")),
                     secondary_y=True)
        f3.update_yaxes(title_text="10Y realised vol (bps)", secondary_y=False)
        f3.update_yaxes(title_text="VIX", secondary_y=True)
        f3.update_layout(template=PLOTLY_THEME, height=380,
                          margin=dict(l=10, r=10, t=10, b=10),
                          hovermode="x unified")
        st.plotly_chart(f3, use_container_width=True)
        r = float(rv10.loc[common].corr(vix.loc[common]))
        st.caption(
            f"1Y correlation: **{r:+.2f}**  ·  rates vol and equity vol usually "
            "move together; persistent decorrelation is a regime change signal."
        )
