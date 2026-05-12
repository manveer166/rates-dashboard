"""Page 20 — Global Sovereign Curves.

Cross-market view: US Treasuries, ECB AAA euro-area benchmark, and UK gilts
on a single screen. Shows curve overlay, cross-market 10Y spreads with
z-scores, and a snapshot table.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import PLOTLY_THEME
from data.fetchers.ecb import ECBFetcher
from data.fetchers.boe import BoEFetcher
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import (
    get_master_df, init_session_state, password_gate,
)

st.set_page_config(page_title="Global Curves", page_icon="🌍", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Global Curves")

st.title("🌍 Global Sovereign Curves")
st.markdown(
    "US (Treasury) · EU (ECB AAA euro-area benchmark) · UK (gilts) — "
    "the three liquid DM rates markets on one screen."
)
st.divider()

# ── Fetchers, cached ──────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner="Pulling EU yields…")
def _fetch_ecb(start: str, end: str) -> pd.DataFrame:
    try:
        return ECBFetcher(start, end, use_cache=True).fetch()
    except Exception as e:
        st.warning(f"EU fetch failed: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner="Pulling UK yields…")
def _fetch_boe(start: str, end: str) -> pd.DataFrame:
    try:
        return BoEFetcher(start, end, use_cache=True).fetch()
    except Exception as e:
        st.warning(f"UK fetch failed: {e}")
        return pd.DataFrame()

# Pull last 5 years for z-score windows
_today = datetime.today().date()
_start = (_today - timedelta(days=5 * 365)).isoformat()
_end   = _today.isoformat()

us_df  = get_master_df()
eu_df  = _fetch_ecb(_start, _end)
uk_df  = _fetch_boe(_start, _end)

if us_df.empty:
    st.error("US data unavailable — refresh the cache.")
    st.stop()

# ── Tenor maps (only show tenors common across markets) ───────────────────
US_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
EU_TENOR_MAP = {"2Y":"EU_2Y","3Y":"EU_3Y","5Y":"EU_5Y","7Y":"EU_7Y",
                "10Y":"EU_10Y","20Y":"EU_20Y","30Y":"EU_30Y"}
UK_TENOR_MAP = {"2Y":"UK_2Y","5Y":"UK_5Y","10Y":"UK_10Y"}

def _curve(df, tenor_map):
    if df.empty:
        return {}
    last = df.dropna(how="all").iloc[-1]
    return {t: float(last[col]) for t, col in tenor_map.items()
            if col in last.index and pd.notna(last[col])}

us_curve = {t: float(us_df[t].dropna().iloc[-1]) for t in US_TENORS if t in us_df.columns}
eu_curve = _curve(eu_df, EU_TENOR_MAP)
uk_curve = _curve(uk_df, UK_TENOR_MAP)

# ── Curve overlay ─────────────────────────────────────────────────────────
st.subheader("🌐 Curve overlay — current")
fig = go.Figure()

if us_curve:
    fig.add_trace(go.Scatter(
        x=list(us_curve.keys()), y=list(us_curve.values()),
        mode="lines+markers", name="US (UST)",
        line=dict(color="#4fc3f7", width=2.5), marker=dict(size=8),
    ))
if eu_curve:
    fig.add_trace(go.Scatter(
        x=list(eu_curve.keys()), y=list(eu_curve.values()),
        mode="lines+markers", name="EU AAA (ECB)",
        line=dict(color="#a78bfa", width=2.5), marker=dict(size=8),
    ))
if uk_curve:
    fig.add_trace(go.Scatter(
        x=list(uk_curve.keys()), y=list(uk_curve.values()),
        mode="lines+markers", name="UK Gilts",
        line=dict(color="#f472b6", width=2.5, dash="dash"),
        marker=dict(size=8, symbol="diamond"),
    ))
fig.update_layout(template=PLOTLY_THEME, height=420, hovermode="x unified",
                  xaxis_title="Tenor", yaxis_title="Yield (%)",
                  margin=dict(l=10, r=10, t=10, b=10),
                  legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
st.plotly_chart(fig, use_container_width=True)

# ── Snapshot table ────────────────────────────────────────────────────────
st.subheader("📋 Snapshot")
snap_rows = []
for t in US_TENORS:
    snap_rows.append({
        "Tenor": t,
        "US (%)": f"{us_curve.get(t, float('nan')):.2f}" if t in us_curve else "—",
        "EU (%)": f"{eu_curve.get(t, float('nan')):.2f}" if t in eu_curve else "—",
        "UK (%)": f"{uk_curve.get(t, float('nan')):.2f}" if t in uk_curve else "—",
        "US-EU (bps)":
            f"{(us_curve[t] - eu_curve[t]) * 100:+.0f}"
            if t in us_curve and t in eu_curve else "—",
        "US-UK (bps)":
            f"{(us_curve[t] - uk_curve[t]) * 100:+.0f}"
            if t in us_curve and t in uk_curve else "—",
    })
st.dataframe(pd.DataFrame(snap_rows).set_index("Tenor"), use_container_width=True)

st.divider()

# ── Cross-market 10Y spreads with z-scores ────────────────────────────────
st.subheader("📈 Cross-market 10Y spreads (1Y history)")

def _aligned_spread(us_col, other_df, other_col, lookback_days=252):
    if us_col not in us_df.columns or other_df.empty or other_col not in other_df.columns:
        return pd.Series(dtype=float)
    a = us_df[us_col].dropna()
    b = other_df[other_col].dropna()
    common = a.index.intersection(b.index)
    if len(common) < 30:
        return pd.Series(dtype=float)
    spread = (a.loc[common] - b.loc[common]) * 100  # bps
    return spread.tail(lookback_days)

us_eu_10y = _aligned_spread("10Y", eu_df, "EU_10Y")
us_uk_10y = _aligned_spread("10Y", uk_df, "UK_10Y")

c1, c2 = st.columns(2)

def _spread_chart(col, series, label, color):
    if series.empty:
        col.info(f"{label}: not enough overlapping history yet.")
        return
    z = float((series.iloc[-1] - series.mean()) / series.std()) if series.std() > 0 else 0.0
    with col:
        st.metric(
            label, f"{series.iloc[-1]:+.0f} bps",
            f"{(series.iloc[-1] - series.iloc[-22]):+.0f} bps (1m)" if len(series) >= 22 else None,
        )
        st.caption(f"1Y mean **{series.mean():+.0f}** · stdev **{series.std():.0f}** · z **{z:+.2f}**")
        f = go.Figure()
        f.add_trace(go.Scatter(x=series.index, y=series.values,
                               line=dict(color=color, width=1.8),
                               fill="tozeroy",
                               fillcolor=color.replace(")", ",0.10)").replace("rgb", "rgba")
                                         if "rgb" in color else "rgba(167,139,250,0.10)"))
        f.add_hline(y=series.mean(), line_dash="dash", line_color="#94a8c9",
                    annotation_text=f"Mean {series.mean():+.0f}",
                    annotation_position="right")
        f.update_layout(template=PLOTLY_THEME, height=280,
                        margin=dict(l=10, r=10, t=10, b=10),
                        yaxis_title="Spread (bps)",
                        showlegend=False)
        st.plotly_chart(f, use_container_width=True)

_spread_chart(c1, us_eu_10y, "US-EU 10Y (UST minus ECB AAA)",      "#a78bfa")
_spread_chart(c2, us_uk_10y, "US-UK 10Y (UST minus Gilt)",          "#f472b6")

st.caption(
    "Negative US-UK 10Y means UK gilts trade higher than UST — usually a "
    "function of UK term-premium / supply. US-EU is the cleaner DM "
    "real-rate / inflation differential read."
)

st.divider()

# ── Curve shapes (2s10s) per region ───────────────────────────────────────
st.subheader("📐 2s10s slopes by region")
def _2s10s(df, t2, t10):
    if df.empty or t2 not in df.columns or t10 not in df.columns:
        return pd.Series(dtype=float)
    return (df[t10] - df[t2]).dropna() * 100

slopes = {
    "US 2s10s": _2s10s(us_df,           "2Y",     "10Y"),
    "EU 2s10s": _2s10s(eu_df,           "EU_2Y",  "EU_10Y"),
    "UK 2s10s": _2s10s(uk_df,           "UK_2Y",  "UK_10Y"),
}

fig3 = go.Figure()
for label, ser, color in [
    ("US 2s10s", slopes["US 2s10s"], "#4fc3f7"),
    ("EU 2s10s", slopes["EU 2s10s"], "#a78bfa"),
    ("UK 2s10s", slopes["UK 2s10s"], "#f472b6"),
]:
    if ser.empty:
        continue
    s = ser.tail(252)
    fig3.add_trace(go.Scatter(x=s.index, y=s.values, name=label,
                              line=dict(color=color, width=1.8)))
fig3.add_hline(y=0, line_dash="dot", line_color="#94a8c9", line_width=1)
fig3.update_layout(template=PLOTLY_THEME, height=320, hovermode="x unified",
                   yaxis_title="Slope (bps)",
                   margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(fig3, use_container_width=True)

st.divider()

# ── Asia overlay (China / Japan / Korea / Singapore / Taiwan) ────────────
# HKMA's own API doesn't publish yields publicly any more; econdb has HK
# listed but empty. Singapore is the standard HK rates proxy — they share
# the currency-board / USD-anchored dynamic.
st.subheader("🌏 Asian sovereign curves")
st.caption(
    "Pulled via OpenBB/econdb (no key). **Hong Kong** is listed in econdb but "
    "the provider has no daily data — Singapore is the standard practitioner "
    "proxy for HK rates (both run currency boards anchored to USD)."
)


@st.cache_data(ttl=24 * 3600, show_spinner="Pulling Asia curves via OpenBB…")
def _fetch_asia():
    from data.openbb_data import asia_yield_snapshot
    return asia_yield_snapshot()


asia = _fetch_asia()
if asia.empty:
    st.info("Asian curves unavailable right now — retry in a few minutes.")
else:
    figA = go.Figure()
    palette = {"China":"#dc2626", "Japan":"#f87171", "South Korea":"#fbbf24",
                "Singapore":"#4ade80", "Taiwan":"#a78bfa", "Hong Kong":"#22d3ee"}
    for c in sorted(asia["country"].unique()):
        sub = asia[asia["country"] == c].sort_values("maturity_years")
        if sub.empty: continue
        figA.add_trace(go.Scatter(
            x=sub["maturity_years"], y=sub["rate"] * 100,
            mode="lines+markers", name=c,
            line=dict(color=palette.get(c, "#94a8c9"), width=2),
        ))
    # Overlay US for comparison
    if us_curve:
        us_y = [{"2Y":2,"3Y":3,"5Y":5,"7Y":7,"10Y":10,"20Y":20,"30Y":30}[t]
                for t in us_curve.keys() if t in ("2Y","3Y","5Y","7Y","10Y","20Y","30Y")]
        us_r = [us_curve[t] for t in us_curve.keys() if t in ("2Y","3Y","5Y","7Y","10Y","20Y","30Y")]
        figA.add_trace(go.Scatter(
            x=us_y, y=us_r, name="US (reference)", mode="lines+markers",
            line=dict(color="#4fc3f7", width=3, dash="dash"),
        ))
    figA.update_layout(template=PLOTLY_THEME, height=420,
                        xaxis_title="Maturity (years)",
                        yaxis_title="Yield (%)",
                        hovermode="x unified",
                        margin=dict(l=10, r=10, t=10, b=10),
                        legend=dict(orientation="h", yanchor="bottom",
                                     y=1.02, xanchor="right", x=1))
    st.plotly_chart(figA, use_container_width=True)

    # Per-country 10Y snapshot
    rows = []
    for c in sorted(asia["country"].unique()):
        sub = asia[asia["country"] == c].sort_values("maturity_years")
        # Pick closest to 10Y
        ten = sub.iloc[(sub["maturity_years"] - 10).abs().argmin()] if not sub.empty else None
        if ten is None: continue
        rows.append({
            "Country":      c,
            "10Y (%)":      f"{ten['rate'] * 100:.2f}",
            "vs US 10Y":    f"{(ten['rate'] - us_curve.get('10Y', 0) / 100) * 10000:+.0f} bps"
                            if "10Y" in us_curve else "—",
            "Tenors avail": len(sub),
        })
    st.dataframe(pd.DataFrame(rows).set_index("Country"), use_container_width=True)

st.divider()
st.caption(
    "Note: ECB AAA is a synthetic curve (DE/NL/LU/FR rated AAA). HKMA's "
    "public REST API returns 404; econdb lists HK but populates no data. "
    "Singapore yields are the practical free HK proxy for now."
)
