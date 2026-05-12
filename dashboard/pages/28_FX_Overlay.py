"""Page 28 — FX Overlay.

USD-quoted FX pairs + DXY (broad trade-weighted dollar) on one screen, with
yield-spread overlays so you can eyeball the rates-FX relationship that
matters most for macro RV (USDJPY vs 10Y, EURUSD vs Bund-UST).

Pulls FRED directly via pandas_datareader (no API key) and caches for 1 day.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import FX_SERIES, PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import get_master_df, init_session_state, password_gate

st.set_page_config(page_title="FX Overlay", page_icon="💱", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="FX Overlay")

st.title("💱 FX Overlay")
st.caption(
    "Major USD pairs + the broad trade-weighted dollar, overlaid against US "
    "10Y and 2s10s for a quick rates-FX read."
)
st.divider()


@st.cache_data(ttl=24 * 3600, show_spinner="Pulling FX from FRED…")
def _fetch_fx(start: str, end: str) -> pd.DataFrame:
    import pandas_datareader.data as web
    frames = []
    for col_name, series_id in FX_SERIES.items():
        try:
            s = web.DataReader(series_id, "fred", start, end).squeeze()
            s.name = col_name
            frames.append(s)
        except Exception:
            pass
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1).sort_index().ffill(limit=3)


# Pull last 5 years
_today = datetime.today().date()
fx = _fetch_fx((_today - timedelta(days=5 * 365)).isoformat(), _today.isoformat())
us  = get_master_df()

if fx.empty:
    st.error("FX fetch failed — try again, or refresh data.")
    st.stop()

# ── Snapshot ──────────────────────────────────────────────────────────────
last = fx.dropna(how="all").iloc[-1]
m1, m2, m3, m4 = st.columns(4)

def _delta(col, days=22):
    if col not in fx.columns: return None
    s = fx[col].dropna()
    if len(s) < days + 1: return None
    return float((s.iloc[-1] / s.iloc[-days - 1] - 1) * 100)

with m1:
    if "USD_EUR" in fx.columns:
        st.metric("EUR/USD", f"{last['USD_EUR']:.4f}",
                  f"{_delta('USD_EUR'):+.2f}% (1m)" if _delta('USD_EUR') is not None else None)
with m2:
    if "JPY_USD" in fx.columns:
        st.metric("USD/JPY", f"{last['JPY_USD']:.2f}",
                  f"{_delta('JPY_USD'):+.2f}% (1m)" if _delta('JPY_USD') is not None else None)
with m3:
    if "GBP_USD" in fx.columns:
        st.metric("GBP/USD", f"{last['GBP_USD']:.4f}",
                  f"{_delta('GBP_USD'):+.2f}% (1m)" if _delta('GBP_USD') is not None else None)
with m4:
    if "DXY" in fx.columns:
        st.metric("Trade-weighted USD", f"{last['DXY']:.2f}",
                  f"{_delta('DXY'):+.2f}% (1m)" if _delta('DXY') is not None else None)

st.divider()

# ── FX time series with US rates overlay ──────────────────────────────────
st.subheader("📈 USD pairs vs US 10Y")

window = fx.tail(252)
us_window = us["10Y"].reindex(window.index).ffill() if "10Y" in us.columns else pd.Series(dtype=float)

fig = make_subplots(specs=[[{"secondary_y": True}]])
for col, color in [("USD_EUR", "#4fc3f7"),
                    ("JPY_USD", "#fb923c"),
                    ("DXY",     "#a78bfa")]:
    if col in window.columns:
        # Normalize to 100 at window start
        s = window[col].dropna()
        if s.empty: continue
        norm = s / s.iloc[0] * 100
        fig.add_trace(go.Scatter(x=norm.index, y=norm.values,
                                 line=dict(color=color, width=1.8),
                                 name=col), secondary_y=False)
if not us_window.empty:
    fig.add_trace(go.Scatter(x=us_window.index, y=us_window.values,
                             line=dict(color="#f87171", width=1.6, dash="dash"),
                             name="US 10Y (right)"), secondary_y=True)

fig.update_yaxes(title_text="Indexed to 100 at start", secondary_y=False)
fig.update_yaxes(title_text="US 10Y (%)", secondary_y=True)
fig.update_layout(template=PLOTLY_THEME, height=420, hovermode="x unified",
                  margin=dict(l=10, r=10, t=10, b=10),
                  legend=dict(orientation="h", yanchor="bottom", y=1.02,
                              xanchor="right", x=1))
st.plotly_chart(fig, use_container_width=True)

# ── USDJPY vs US-JP yield differential ────────────────────────────────────
st.subheader("🧭 USDJPY vs US-JP 10Y yield spread")
if "JPY_USD" in fx.columns and "JP_10Y" in us.columns and "10Y" in us.columns:
    spread = ((us["10Y"] - us["JP_10Y"]) * 100).dropna().tail(252)  # bps
    jpy = fx["JPY_USD"].reindex(spread.index).ffill()
    if not spread.empty and not jpy.empty:
        f2 = make_subplots(specs=[[{"secondary_y": True}]])
        f2.add_trace(go.Scatter(x=jpy.index, y=jpy.values, name="USDJPY",
                                line=dict(color="#fb923c", width=2)),
                     secondary_y=False)
        f2.add_trace(go.Scatter(x=spread.index, y=spread.values, name="US-JP 10Y (bps)",
                                line=dict(color="#4fc3f7", width=1.8, dash="dash")),
                     secondary_y=True)
        f2.update_yaxes(title_text="USDJPY", secondary_y=False)
        f2.update_yaxes(title_text="US-JP 10Y (bps)", secondary_y=True)
        f2.update_layout(template=PLOTLY_THEME, height=380,
                         margin=dict(l=10, r=10, t=10, b=10),
                         hovermode="x unified")
        st.plotly_chart(f2, use_container_width=True)
        # Correlation
        common = spread.index.intersection(jpy.index)
        if len(common) >= 30:
            r = float(jpy.loc[common].corr(spread.loc[common]))
            st.caption(f"1Y correlation: **{r:+.2f}**  ·  positive = rates differential drives JPY weakness as expected.")
else:
    st.info("US-JP yield differential needs JP_10Y in cache (FRED INTL series — refresh to pull).")

# ── Snapshot table ────────────────────────────────────────────────────────
st.divider()
st.subheader("📋 Snapshot vs 1Y")
rows = []
for col in fx.columns:
    s = fx[col].dropna().tail(252)
    if len(s) < 60: continue
    z = float((s.iloc[-1] - s.mean()) / s.std()) if s.std() > 0 else 0.0
    rows.append({
        "Pair":    col,
        "Current": f"{s.iloc[-1]:.4f}" if abs(s.iloc[-1]) < 100 else f"{s.iloc[-1]:.2f}",
        "1Y mean": f"{s.mean():.4f}"   if abs(s.mean())   < 100 else f"{s.mean():.2f}",
        "1Y stdev": f"{s.std():.4f}"   if abs(s.std())    < 100 else f"{s.std():.2f}",
        "Z-score": f"{z:+.2f}",
    })
st.dataframe(pd.DataFrame(rows).set_index("Pair"), use_container_width=True)
