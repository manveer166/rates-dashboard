"""Page 24 — Trade Backtester.

Backtests any outright, curve, or fly trade against the cached history.
DV01-weighting follows the same convention as the scanner, so results line
up with what the Analysis page Z-scores you (no surprises).

PnL convention (unit = bps per DV01-equivalent):
    - "Receive" trade ⇒ PnL_t = -(level_t - entry_level) * 100
    - "Pay"     trade ⇒ PnL_t = +(level_t - entry_level) * 100

Stats reported: total bps, annualised, Sharpe, hit rate (% positive days),
max drawdown, vol, average win/loss.

Carry is *not* baked into the curve PnL here — pure mark-to-market.  Adding
forward-carry roll later is straightforward via fixed_income.forward_carry_rolldown.
"""

import sys
from datetime import date, datetime, timedelta
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

st.set_page_config(page_title="Backtester", page_icon="🧪", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Backtester")

from dashboard.components.premium_gate import premium_gate
if not premium_gate("Backtester"):
    st.stop()

st.title("🧪 Trade Backtester")
st.caption(
    "Pick any outright, curve, or fly receive/pay trade and see how it would "
    "have performed over the cached history."
)
st.divider()

df = get_master_df()
if df.empty:
    st.error("No master data — refresh the cache.")
    st.stop()

# ── Inputs ────────────────────────────────────────────────────────────────
ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
avail = [t for t in ALL_TENORS if t in df.columns]

c1, c2, c3 = st.columns([1, 2, 1])
with c1:
    trade_type = st.selectbox("Type", ["Outright", "Curve", "Fly"], key="bt_type")
with c2:
    if trade_type == "Outright":
        tenors = [st.selectbox("Tenor", avail, index=avail.index("10Y") if "10Y" in avail else 0,
                                key="bt_t1")]
    elif trade_type == "Curve":
        tt1, tt2 = st.columns(2)
        t1 = tt1.selectbox("Short leg",  avail,
                            index=avail.index("2Y") if "2Y" in avail else 0,  key="bt_c1")
        t2 = tt2.selectbox("Long leg",   avail,
                            index=avail.index("10Y") if "10Y" in avail else -1, key="bt_c2")
        tenors = [t1, t2]
    else:  # Fly
        tt1, ttb, tt2 = st.columns(3)
        wing1 = tt1.selectbox("Front wing", avail,
                               index=avail.index("2Y") if "2Y" in avail else 0,  key="bt_w1")
        belly = ttb.selectbox("Belly",      avail,
                               index=avail.index("5Y") if "5Y" in avail else 0,  key="bt_bl")
        wing2 = tt2.selectbox("Back wing",  avail,
                               index=avail.index("10Y") if "10Y" in avail else -1, key="bt_w2")
        tenors = [wing1, belly, wing2]
with c3:
    direction = st.selectbox("Direction", ["receive", "pay"], key="bt_dir")

c4, c5, c6 = st.columns(3)
with c4:
    bt_start = st.date_input("Start", value=df.index[0].date(), key="bt_start")
with c5:
    bt_end = st.date_input("End", value=df.index[-1].date(), key="bt_end")
with c6:
    rebalance = st.selectbox(
        "Rebalance",
        ["No (entry weights held)", "Daily (re-weight every day)"],
        key="bt_rebal",
        help="No: lock in DV01 weights at entry. Daily: re-weight every day to neutral.",
    )

# ── Build the trade level series ──────────────────────────────────────────
def _approx_dv01(tenor: str, yld: float) -> float:
    """Quick DV01 approx (matches fixed_income.approx_dv01 closely enough for weighting)."""
    years = {"2Y":2,"3Y":3,"5Y":5,"7Y":7,"10Y":10,"20Y":20,"30Y":30}.get(tenor, 10)
    # Crude: PV of $100 par with semi-annual coupon = yield, 100% recovery.
    # DV01 ≈ duration / (1 + y/2) * 100 / 10000.  Simpler: years * a-shape.
    n = years * 2
    y = max(yld / 100.0, 0.001) / 2
    pv = sum(1 / (1 + y) ** k for k in range(1, n + 1))
    return pv * 100.0 / 10000  # rough $ per bp per $100 par


def _build_levels(df: pd.DataFrame, ttype: str, tenors: list,
                  rebalance_daily: bool) -> pd.Series:
    """Return the 'level' series whose change drives PnL."""
    if ttype == "Outright":
        return df[tenors[0]].dropna()

    sub = df[tenors].dropna()
    if sub.empty:
        return pd.Series(dtype=float)

    if rebalance_daily:
        # Recompute DV01 weights every day from that day's yield levels.
        if ttype == "Curve":
            t1, t2 = tenors
            d1 = sub[t1].apply(lambda y: _approx_dv01(t1, y))
            d2 = sub[t2].apply(lambda y: _approx_dv01(t2, y))
            ratio = (d2 / d1).where(d1 > 0, 1.0)
            return sub[t2] - ratio * sub[t1]
        else:
            w1, b, w2 = tenors
            dw1 = sub[w1].apply(lambda y: _approx_dv01(w1, y))
            db  = sub[b].apply(lambda y: _approx_dv01(b, y))
            dw2 = sub[w2].apply(lambda y: _approx_dv01(w2, y))
            wb  = (2.0 * dw1 / db).where(db > 0, 2.0)
            ww2 = (dw1 / dw2).where(dw2 > 0, 1.0)
            return wb * sub[b] - sub[w1] - ww2 * sub[w2]

    # Locked-in weights at entry (first row of window)
    entry_yields = sub.iloc[0]
    if ttype == "Curve":
        t1, t2 = tenors
        d1 = _approx_dv01(t1, entry_yields[t1])
        d2 = _approx_dv01(t2, entry_yields[t2])
        ratio = d2 / d1 if d1 > 0 else 1.0
        return sub[t2] - ratio * sub[t1]
    else:
        w1, b, w2 = tenors
        dw1 = _approx_dv01(w1, entry_yields[w1])
        db  = _approx_dv01(b,  entry_yields[b])
        dw2 = _approx_dv01(w2, entry_yields[w2])
        wb  = 2.0 * (dw1 / db) if db > 0 else 2.0
        ww2 = dw1 / dw2 if dw2 > 0 else 1.0
        return wb * sub[b] - sub[w1] - ww2 * sub[w2]


level = _build_levels(df, trade_type, tenors, rebalance == "Daily (re-weight every day)")
if level.empty:
    st.warning("Not enough overlapping data for the selected tenors.")
    st.stop()

# Slice to user window
level = level.loc[str(bt_start):str(bt_end)].dropna()
if len(level) < 10:
    st.warning("Window too short — pick a wider range.")
    st.stop()

# ── PnL series ────────────────────────────────────────────────────────────
entry_level = float(level.iloc[0])
sign = -1.0 if direction == "receive" else 1.0
pnl_bps = sign * (level - entry_level) * 100   # cumulative bps from entry
daily_pnl = pnl_bps.diff().fillna(0.0)         # daily mark-to-market change

# ── Stats ─────────────────────────────────────────────────────────────────
days       = len(daily_pnl)
total_bps  = float(pnl_bps.iloc[-1])
ann_bps    = total_bps / days * 252 if days else 0
vol_bps    = float(daily_pnl.std() * np.sqrt(252)) if daily_pnl.std() > 0 else 0
sharpe     = ann_bps / vol_bps if vol_bps > 0 else 0
positive   = float((daily_pnl > 0).mean() * 100)

cum = pnl_bps
peak = cum.cummax()
drawdown = cum - peak  # always <= 0
max_dd = float(drawdown.min())

wins  = daily_pnl[daily_pnl > 0]
losses = daily_pnl[daily_pnl < 0]
avg_win = float(wins.mean()) if len(wins) else 0
avg_loss = float(losses.mean()) if len(losses) else 0

# ── Trade name + headline ─────────────────────────────────────────────────
def _trade_name():
    d = direction.capitalize()
    if trade_type == "Outright":
        return f"{d} {tenors[0]}"
    if trade_type == "Curve":
        return f"{d} {tenors[0]}/{tenors[1]} curve"
    return f"{d} {tenors[0]}{tenors[1]}{tenors[2]} fly"

st.subheader(f"📊 {_trade_name()}")
st.caption(f"{level.index[0].date()} → {level.index[-1].date()}  ·  {days} trading days")

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Total PnL",   f"{total_bps:+.0f} bps")
m2.metric("Annualised",  f"{ann_bps:+.0f} bps")
m3.metric("Sharpe",      f"{sharpe:+.2f}")
m4.metric("Hit rate",    f"{positive:.0f}%")
m5.metric("Max DD",      f"{max_dd:.0f} bps")
m6.metric("Vol (ann)",   f"{vol_bps:.0f} bps")

st.divider()

# ── Charts ────────────────────────────────────────────────────────────────
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
                    row_heights=[0.55, 0.45],
                    subplot_titles=("Cumulative PnL (bps)",
                                    "Drawdown (bps from peak)"))
fig.add_trace(go.Scatter(
    x=cum.index, y=cum.values, name="Cumulative PnL",
    line=dict(color="#4ade80" if total_bps >= 0 else "#f87171", width=2),
    fill="tozeroy",
    fillcolor="rgba(74,222,128,0.10)" if total_bps >= 0 else "rgba(248,113,113,0.10)",
), row=1, col=1)
fig.add_hline(y=0, line_dash="dot", line_color="#94a8c9", line_width=1, row=1, col=1)

fig.add_trace(go.Scatter(
    x=drawdown.index, y=drawdown.values, name="Drawdown",
    line=dict(color="#f87171", width=1.6),
    fill="tozeroy", fillcolor="rgba(248,113,113,0.18)",
), row=2, col=1)

fig.update_layout(template=PLOTLY_THEME, height=520,
                  margin=dict(l=10, r=10, t=40, b=10),
                  showlegend=False)
st.plotly_chart(fig, use_container_width=True)

# ── Underlying level (yield/spread) chart ─────────────────────────────────
with st.expander("📈 Underlying level (driver) — yield or DV01-weighted spread"):
    f2 = go.Figure()
    f2.add_trace(go.Scatter(
        x=level.index, y=level.values, name="Level",
        line=dict(color="#4fc3f7", width=2),
    ))
    f2.add_hline(y=entry_level, line_dash="dash", line_color="#94a8c9",
                 annotation_text=f"Entry {entry_level:.3f}",
                 annotation_position="right")
    ylabel = "Yield (%)" if trade_type == "Outright" else "Spread (DV01-weighted)"
    f2.update_layout(template=PLOTLY_THEME, height=320,
                     margin=dict(l=10, r=10, t=10, b=10), yaxis_title=ylabel)
    st.plotly_chart(f2, use_container_width=True)

# ── Win / loss distribution ───────────────────────────────────────────────
with st.expander("📊 Daily PnL distribution"):
    f3 = go.Figure()
    f3.add_trace(go.Histogram(x=daily_pnl.values, nbinsx=40,
                              marker_color="#4fc3f7"))
    f3.add_vline(x=0, line_dash="dot", line_color="#94a8c9")
    f3.update_layout(template=PLOTLY_THEME, height=280,
                     margin=dict(l=10, r=10, t=10, b=10),
                     xaxis_title="Daily PnL (bps)", yaxis_title="Days")
    st.plotly_chart(f3, use_container_width=True)
    sub_c1, sub_c2 = st.columns(2)
    sub_c1.metric("Avg win",  f"{avg_win:+.1f} bps")
    sub_c2.metric("Avg loss", f"{avg_loss:+.1f} bps")

# ── Summary export ────────────────────────────────────────────────────────
with st.expander("📋 Export"):
    out = pd.DataFrame({
        "level":       level,
        "cumulative_pnl_bps": cum,
        "daily_pnl_bps":      daily_pnl,
        "drawdown_bps":       drawdown,
    })
    csv = out.to_csv()
    st.download_button("⬇️ Download CSV", data=csv,
                       file_name=f"backtest_{_trade_name().replace(' ','_')}.csv",
                       mime="text/csv", use_container_width=True)
