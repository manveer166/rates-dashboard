"""Page 39 — CME Bond Futures.

Front-month UST futures: 2Y (ZT), 5Y (ZF), 10Y (ZN), Ultra 10Y (TN),
30Y (ZB), Ultra Bond (UB).  Source: yfinance continuous contracts.

Includes:
  • Snapshot strip per contract
  • NOB-style inter-contract spread (10Y futures − 30Y futures)
  • Futures vs cash UST overlay (rough — ignores conversion factors / CTD)

Built for the Substack content angle: "the steepener is on" / "front-end
futures pricing X bps of cuts" reads, not full deliverable-basis trading.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import get_master_df, init_session_state, password_gate

st.set_page_config(page_title="Bond Futures", page_icon="📈", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Bond Futures")

st.title("📈 CME Bond Futures")
st.caption(
    "Front-month USTs as continuous contracts via yfinance. Prices are clean "
    "futures levels (no CTD / conversion-factor adjustment) — useful for "
    "directional + RV reads, not for delivery-basis trading."
)
st.divider()


CONTRACTS = {
    "ZT=F": ("ZT",  "2Y Note",    "#fb923c"),
    "ZF=F": ("ZF",  "5Y Note",    "#fbbf24"),
    "ZN=F": ("ZN",  "10Y Note",   "#4fc3f7"),
    "TN=F": ("TN",  "Ultra 10Y",  "#22d3ee"),
    "ZB=F": ("ZB",  "30Y Bond",   "#a78bfa"),
    "UB=F": ("UB",  "Ultra Bond", "#f472b6"),
}


@st.cache_data(ttl=3600, show_spinner="Pulling CME futures via yfinance…")
def _fetch_futures(period: str = "1y") -> pd.DataFrame:
    frames = []
    for sym, (short, _, _) in CONTRACTS.items():
        try:
            h = yf.Ticker(sym).history(period=period, interval="1d")
            if h.empty: continue
            s = h["Close"].rename(short)
            s.index = pd.to_datetime(s.index).tz_localize(None)
            frames.append(s)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1).ffill(limit=2)


fdf = _fetch_futures("1y")
if fdf.empty:
    st.error("Futures fetch failed — yfinance may be rate-limited.")
    st.stop()


# ── Snapshot strip ───────────────────────────────────────────────────────
st.subheader("📍 Snapshot")
last = fdf.dropna(how="all").iloc[-1]
cols = st.columns(len(CONTRACTS))
for i, (sym, (short, name, color)) in enumerate(CONTRACTS.items()):
    if short not in fdf.columns: continue
    s = fdf[short].dropna()
    if s.empty: continue
    d1 = float(s.iloc[-1] - s.iloc[-2]) if len(s) > 1 else 0.0
    d5 = float(s.iloc[-1] - s.iloc[-6]) if len(s) > 5 else 0.0
    with cols[i]:
        st.metric(
            f"{short} — {name}",
            f"{s.iloc[-1]:.4f}",
            f"1d {d1:+.4f} / 1w {d5:+.4f}",
        )

st.divider()


# ── Price history chart (normalised to 100 at start) ─────────────────────
st.subheader("📈 12-month history (indexed to 100 at start)")
window = fdf.tail(252)
fig = go.Figure()
for sym, (short, name, color) in CONTRACTS.items():
    if short not in window.columns: continue
    s = window[short].dropna()
    if s.empty: continue
    norm = s / s.iloc[0] * 100
    fig.add_trace(go.Scatter(
        x=norm.index, y=norm.values, name=f"{short} {name}",
        line=dict(color=color, width=1.8),
    ))
fig.update_layout(template=PLOTLY_THEME, height=420, hovermode="x unified",
                  yaxis_title="Index (100 at window start)",
                  margin=dict(l=10, r=10, t=10, b=10),
                  legend=dict(orientation="h", yanchor="bottom", y=1.02,
                              xanchor="right", x=1))
st.plotly_chart(fig, use_container_width=True)

st.divider()


# ── Inter-contract spreads (NOB-style) ───────────────────────────────────
st.subheader("📐 Inter-contract spreads")
st.caption(
    "NOB = ZN − ZB (10Y vs 30Y price diff). FYT = ZF − ZT (5Y vs 2Y). "
    "These trade as flatteners/steepeners on the futures board — the same "
    "DV01-neutral curve trades you'd put on with cash."
)

spread_pairs = [
    ("NOB", "ZN", "ZB", "#4fc3f7", "10Y − 30Y (NOB)"),
    ("FYT", "ZF", "ZT", "#fbbf24", "5Y − 2Y (FYT)"),
    ("BOB", "ZB", "ZT", "#a78bfa", "30Y − 2Y (BOB)"),
]

g1, g2, g3 = st.columns(3)
for col_widget, (name, a, b, color, label) in zip([g1, g2, g3], spread_pairs):
    if a not in fdf.columns or b not in fdf.columns:
        continue
    sp = (fdf[a] - fdf[b]).dropna().tail(252)
    if sp.empty: continue
    z = float((sp.iloc[-1] - sp.mean()) / sp.std()) if sp.std() > 0 else 0.0
    with col_widget:
        st.metric(label, f"{sp.iloc[-1]:+.3f}",
                  f"1Y z = {z:+.2f}")
        f = go.Figure()
        f.add_trace(go.Scatter(x=sp.index, y=sp.values,
                                line=dict(color=color, width=1.8),
                                fill="tozeroy",
                                fillcolor=("rgba(79,195,247,0.10)" if color == "#4fc3f7"
                                            else "rgba(251,191,36,0.10)" if color == "#fbbf24"
                                            else "rgba(167,139,250,0.10)")))
        f.add_hline(y=sp.mean(), line_dash="dash", line_color="#94a8c9",
                     annotation_text=f"Mean {sp.mean():+.3f}",
                     annotation_position="right")
        f.update_layout(template=PLOTLY_THEME, height=240,
                         margin=dict(l=10, r=10, t=10, b=10),
                         showlegend=False)
        st.plotly_chart(f, use_container_width=True)

st.divider()


# ── Cross-market: futures vs cash UST ─────────────────────────────────────
st.subheader("🔁 Futures vs cash UST")
st.caption(
    "Futures yield (rough — assumes 6% coupon / 100-day convention) vs cash. "
    "Persistent gap = funding/repo dislocation or carry mispricing — not "
    "tradable directly here, but signals where to look."
)

mdf = get_master_df()
if not mdf.empty and "10Y" in mdf.columns and "ZN" in fdf.columns:
    # Convert ZN price to implied yield (rough)
    # ZN delivers $100K face on a 6.5-10Y note. Price 100 → 6% coupon.
    # Approx: yield ≈ 6% − (Price − 100) * 0.0625 (1pt move ≈ 6.25bps)
    zn_implied = 6.0 - (fdf["ZN"] - 100) * 0.0625
    cash_10y = mdf["10Y"].reindex(zn_implied.index).ffill()
    overlap = zn_implied.index.intersection(cash_10y.index)
    if len(overlap) >= 30:
        fig = go.Figure()
        sub = zn_implied.loc[overlap].tail(252)
        cash_sub = cash_10y.loc[overlap].tail(252)
        fig.add_trace(go.Scatter(x=sub.index, y=sub.values,
                                  name="ZN implied yield (rough)",
                                  line=dict(color="#fb923c", width=1.8)))
        fig.add_trace(go.Scatter(x=cash_sub.index, y=cash_sub.values,
                                  name="Cash 10Y UST",
                                  line=dict(color="#4fc3f7", width=2, dash="dash")))
        fig.update_layout(template=PLOTLY_THEME, height=320, hovermode="x unified",
                           yaxis_title="Yield (%)",
                           margin=dict(l=10, r=10, t=10, b=10),
                           legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                        xanchor="right", x=1))
        st.plotly_chart(fig, use_container_width=True)
        diff_bps = (sub.iloc[-1] - cash_sub.iloc[-1]) * 100
        st.caption(f"Current gap: **{diff_bps:+.0f} bps** "
                    f"({'futures cheap to cash' if diff_bps < 0 else 'futures rich'}).")
