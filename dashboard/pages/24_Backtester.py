"""Page 24 — Trade Backtester.

Backtests any outright, curve, or fly trade against the cached history.
DV01-weighting follows the same convention as the scanner, so results line
up with what the Analysis page Z-scores you (no surprises).

PnL decomposition (all in bps per long-leg DV01):
    1. Directional   = sign × (level_t − entry_level) × 100
                       (sign = −1 for receive, +1 for pay)
    2. Carry accrual = (annual_carry_bps / 252) × days_held
                       (computed once at entry from the forward curve;
                       static through the backtest)
    3. Transaction   = − round-trip bid/ask × bps  (paid at entry & exit)

Total = directional + carry − tcosts. Each component is tracked
separately so you can see what's actually driving P&L.

Methodology assumptions:
  • Single curve discounting (no separate OIS curve)
  • Static carry at entry — does not re-mark as the curve moves
  • Bid/ask widths from `fixed_income.risk.bid_ask_bps` (practitioner
    consensus for USD on-the-run; off-the-run widens)
  • No slippage beyond the bid/ask (no execution-size impact modelled)
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

# ── Cost & carry toggles ──────────────────────────────────────────────────
cost_col1, cost_col2, cost_col3, cost_col4 = st.columns(4)
with cost_col1:
    bake_carry = st.checkbox(
        "Bake in carry", value=True, key="bt_carry",
        help=("Path-dependent: carry recomputed every day from that day's "
              "curve via forward_carry_rolldown, accrued daily."),
    )
with cost_col2:
    bake_convexity = st.checkbox(
        "Bake in convexity", value=True, key="bt_convexity",
        help=("Adds second-order P&L: ½·C·Δy²·notional, computed per leg "
              "from entry-time convexity. Receivers gain, payers lose."),
    )
with cost_col3:
    bake_tcost = st.checkbox(
        "Bake in transaction costs", value=True, key="bt_tcost",
        help=("Subtracts round-trip bid/ask widths from total P&L. Defaults "
              "are practitioner-consensus widths for USD on-the-run."),
    )
with cost_col4:
    cost_instrument = st.selectbox(
        "Bid/ask source",
        ["treasury (cash)", "swap"],
        key="bt_instr",
        help="Swaps are tighter than cash for benchmark tenors.",
    )
_instr = "swap" if cost_instrument.startswith("swap") else "treasury"


# ── Build the trade level series ──────────────────────────────────────────
import fixed_income as fi

_TY_MAP = {"2Y":2,"3Y":3,"5Y":5,"7Y":7,"10Y":10,"20Y":20,"30Y":30}

def _dv01(tenor: str, yld: float) -> float:
    """Single source of truth — fixed_income.dv01_par."""
    return fi.dv01_par(_TY_MAP.get(tenor, 10), yld)


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
            d1 = sub[t1].apply(lambda y: _dv01(t1, y))
            d2 = sub[t2].apply(lambda y: _dv01(t2, y))
            ratio = (d2 / d1).where(d1 > 0, 1.0)
            return sub[t2] - ratio * sub[t1]
        else:
            w1, b, w2 = tenors
            dw1 = sub[w1].apply(lambda y: _dv01(w1, y))
            db  = sub[b].apply(lambda y: _dv01(b, y))
            dw2 = sub[w2].apply(lambda y: _dv01(w2, y))
            wb  = (2.0 * dw1 / db).where(db > 0, 2.0)
            ww2 = (dw1 / dw2).where(dw2 > 0, 1.0)
            return wb * sub[b] - sub[w1] - ww2 * sub[w2]

    # Locked-in weights at entry (first row of window)
    entry_yields = sub.iloc[0]
    if ttype == "Curve":
        t1, t2 = tenors
        d1 = _dv01(t1, entry_yields[t1])
        d2 = _dv01(t2, entry_yields[t2])
        ratio = d2 / d1 if d1 > 0 else 1.0
        return sub[t2] - ratio * sub[t1]
    else:
        w1, b, w2 = tenors
        dw1 = _dv01(w1, entry_yields[w1])
        db  = _dv01(b,  entry_yields[b])
        dw2 = _dv01(w2, entry_yields[w2])
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

# ── PnL components ────────────────────────────────────────────────────────
entry_level = float(level.iloc[0])
sign = -1.0 if direction == "receive" else 1.0

# 1. Directional P&L — pure mark-to-market on the level
directional_cum = sign * (level - entry_level) * 100   # cumulative bps from entry

# 2. Carry accrual — PATH-DEPENDENT. Recompute carry every day from that
# day's curve, then accrue. This is the right thing for long backtest
# windows: a position held through a regime change earns different daily
# carry as the curve shape evolves, not the entry-time carry forever.
def _compute_carry_path() -> pd.Series:
    """Per-day carry accrual in bps, indexed by `level`.

    Uses fixed_income.forward_carry_rolldown at each date with the
    prevailing curve. ~0.04s for a 5-year backtest — well affordable.

    Returns a Series of daily P&L from carry (positive = trade is
    making money from holding it; negative = paying away).
    """
    # Prefetch the SOFR / overnight series so we can index it per-date
    on_series = None
    for col in ["SOFR", "DFF", "EFFR"]:
        if col in df.columns:
            on_series = df[col].dropna()
            if len(on_series): break

    # Slice the rate matrix to the backtest window
    sub = df[tenors].loc[level.index].copy()
    daily_carry = pd.Series(0.0, index=level.index)

    # Direction sign — receivers earn positive carry when forward < spot;
    # this is already encoded in cr["total"] for a receive trade.
    dir_sign = 1.0 if direction == "receive" else -1.0

    for idx, row in sub.iterrows():
        curve_dict = {t: float(row[t]) for t in tenors if pd.notna(row[t])}
        if len(curve_dict) < len(tenors):
            continue   # missing data on this date — skip
        on_rate = 5.3
        if on_series is not None:
            v = on_series.loc[:idx]
            if len(v): on_rate = float(v.iloc[-1])
        try:
            if trade_type == "Outright":
                cr = fi.forward_carry_rolldown(curve_dict, on_rate, "outright",
                                                tenors[0], holding_months=12.0)
            elif trade_type == "Curve":
                cr = fi.forward_carry_rolldown(curve_dict, on_rate, "spread",
                                                tenors[1], tenors[0],
                                                holding_months=12.0)
            else:
                cr = fi.forward_carry_rolldown(curve_dict, on_rate, "fly",
                                                tenors[0], tenors[1], tenors[2],
                                                holding_months=12.0)
            # cr["total"] is now the 12-month carry+rolldown estimate at
            # this day's curve. Daily accrual = annual / 252.
            daily_carry.loc[idx] = (cr.get("total", 0.0) or 0.0) / 252.0
        except Exception:
            daily_carry.loc[idx] = 0.0

    return dir_sign * daily_carry


if bake_carry:
    carry_daily = _compute_carry_path()
    carry_cum = carry_daily.cumsum()
    # The "annualised carry at entry" comparison number for the breakdown card
    carry_annual_bps = float(carry_daily.iloc[0] * 252) if len(carry_daily) else 0.0
    # The realised average carry across the backtest window
    carry_avg_annual_bps = float(carry_daily.mean() * 252) if len(carry_daily) else 0.0
else:
    carry_cum = pd.Series(0.0, index=level.index)
    carry_annual_bps = 0.0
    carry_avg_annual_bps = 0.0

# 3. Convexity-adjusted P&L — second-order term on every mark
# For each leg, P&L_conv = sign × ½ × C × (Δy)² × leg_notional, summed
# across legs and converted to bps yield-equivalent at the long leg's DV01.
# Receivers gain from convexity (long bonds are convex up), payers lose.
def _compute_convexity_path() -> pd.Series:
    """Per-day cumulative convexity P&L in bps yield-equivalent.

    Convexity is computed from entry-time yields (locked-in) so it stays
    consistent with the entry DV01 weights. The Δy term is path-dependent
    — uses each leg's yield at every date in the window.
    """
    if not bake_convexity:
        return pd.Series(0.0, index=level.index)

    leg_yields = df[tenors].loc[level.index]
    entry_yields = leg_yields.iloc[0]
    is_receiver = (direction == "receive")

    # Per-leg convexity at entry yield (par-bond convention)
    leg_convs = {
        t: fi.convexity_par(_TY_MAP.get(t, 10), float(entry_yields[t]))
        for t in tenors
    }

    if trade_type == "Outright":
        t = tenors[0]
        years = _TY_MAP.get(t, 10)
        dv01_pb = fi.dv01_par(years, float(entry_yields[t]))
        if dv01_pb <= 0:
            return pd.Series(0.0, index=level.index)
        dy_dec = (leg_yields[t] - entry_yields[t]) / 100.0
        sign_leg = 1.0 if is_receiver else -1.0
        dollar_pnl = sign_leg * 0.5 * leg_convs[t] * (dy_dec ** 2) * 1e6
        return (dollar_pnl / dv01_pb).fillna(0.0)

    if trade_type == "Curve":
        # tenors = [short, long]
        t1, t2 = tenors
        years1, years2 = _TY_MAP.get(t1, 2), _TY_MAP.get(t2, 10)
        dv01_short = fi.dv01_par(years1, float(entry_yields[t1]))
        dv01_long  = fi.dv01_par(years2, float(entry_yields[t2]))
        if dv01_short <= 0 or dv01_long <= 0:
            return pd.Series(0.0, index=level.index)
        # DV01-neutral: short notional = (dv01_long / dv01_short) × $1M
        ratio = dv01_long / dv01_short
        dy_short_dec = (leg_yields[t1] - entry_yields[t1]) / 100.0
        dy_long_dec  = (leg_yields[t2] - entry_yields[t2]) / 100.0
        # Receive long (+conv), pay short (-conv). Flip for payer.
        sign_long, sign_short = (1.0, -1.0) if is_receiver else (-1.0, 1.0)
        long_pnl  = sign_long  * 0.5 * leg_convs[t2] * (dy_long_dec ** 2)  * 1e6
        short_pnl = sign_short * 0.5 * leg_convs[t1] * (dy_short_dec ** 2) * (ratio * 1e6)
        return ((long_pnl + short_pnl) / dv01_long).fillna(0.0)

    # Fly: tenors = [wing1, belly, wing2]
    w1, b, w2 = tenors
    yw1, yb, yw2 = _TY_MAP.get(w1, 2), _TY_MAP.get(b, 5), _TY_MAP.get(w2, 10)
    dv01_w1 = fi.dv01_par(yw1, float(entry_yields[w1]))
    dv01_b  = fi.dv01_par(yb,  float(entry_yields[b]))
    dv01_w2 = fi.dv01_par(yw2, float(entry_yields[w2]))
    if min(dv01_w1, dv01_b, dv01_w2) <= 0:
        return pd.Series(0.0, index=level.index)
    # DV01-neutral: belly $1M; each wing notional = 0.5 × dv01_b/dv01_wi
    r1 = 0.5 * dv01_b / dv01_w1
    r2 = 0.5 * dv01_b / dv01_w2
    dy_w1_dec = (leg_yields[w1] - entry_yields[w1]) / 100.0
    dy_b_dec  = (leg_yields[b]  - entry_yields[b])  / 100.0
    dy_w2_dec = (leg_yields[w2] - entry_yields[w2]) / 100.0
    sign_b, sign_w = (1.0, -1.0) if is_receiver else (-1.0, 1.0)
    belly_pnl = sign_b * 0.5 * leg_convs[b]  * (dy_b_dec  ** 2) * 1e6
    w1_pnl    = sign_w * 0.5 * leg_convs[w1] * (dy_w1_dec ** 2) * (r1 * 1e6)
    w2_pnl    = sign_w * 0.5 * leg_convs[w2] * (dy_w2_dec ** 2) * (r2 * 1e6)
    return ((belly_pnl + w1_pnl + w2_pnl) / dv01_b).fillna(0.0)


conv_cum = _compute_convexity_path()
conv_annual_avg_bps = (float(conv_cum.iloc[-1] * 252 / len(conv_cum))
                       if bake_convexity and len(conv_cum) else 0.0)


# 4. Transaction costs — paid up-front at entry and exit
def _compute_tcost_bps() -> float:
    if not bake_tcost:
        return 0.0
    if trade_type == "Outright":
        return fi.tcost_outright_bps(_TY_MAP.get(tenors[0], 10), instrument=_instr)
    if trade_type == "Curve":
        return fi.tcost_curve_bps(_TY_MAP.get(tenors[0], 2), _TY_MAP.get(tenors[1], 10),
                                   instrument=_instr)
    return fi.tcost_fly_bps(_TY_MAP.get(tenors[0], 2), _TY_MAP.get(tenors[1], 5),
                             _TY_MAP.get(tenors[2], 10), instrument=_instr)

tcost_bps = _compute_tcost_bps()
# Entry cost paid on day 1, exit cost paid on the last day. For the cumulative
# series, we charge half at entry and half at the end so the curve dips at both
# ends — visually shows the "drag" without artificially front-loading.
half_tcost = tcost_bps / 2.0
tcost_cum = pd.Series(0.0, index=level.index)
if len(tcost_cum):
    tcost_cum.iloc[0]  = -half_tcost   # entry slip
    tcost_cum.iloc[-1] = -tcost_bps    # entry + exit slip
    # Linear interp between is misleading; just step the second hit at the end
    # by carrying the entry value forward
    tcost_cum = tcost_cum.replace(0.0, np.nan).ffill().fillna(-half_tcost) \
                          if len(tcost_cum) > 1 else tcost_cum

# Total cumulative P&L (directional + carry + convexity − tcosts)
pnl_bps = directional_cum + carry_cum + conv_cum + tcost_cum
daily_pnl = pnl_bps.diff().fillna(0.0)

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

# Headline metric strip (kept for at-a-glance scanning)
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Total PnL (bps)",      f"{total_bps:+.0f}")
m2.metric("Annualised (bps/yr)",  f"{ann_bps:+.0f}")
m3.metric("Sharpe",               f"{sharpe:+.2f}")
m4.metric("Hit rate (%)",         f"{positive:.0f}")
m5.metric("Max DD (bps)",         f"{max_dd:.0f}")
m6.metric("Vol (bps/yr)",         f"{vol_bps:.0f}")

# Branded signal card — same visual language as Scanner / Regime
from dashboard.components.signal_card import render_signal_card, render_units_legend

# Approximate Z by the level vs its full-window mean
_z = float((level.iloc[-1] - level.mean()) / level.std()) if level.std() > 0 else 0.0
dir_total   = float(directional_cum.iloc[-1])
carry_total = float(carry_cum.iloc[-1])
conv_total  = float(conv_cum.iloc[-1])
tcost_total = float(tcost_cum.iloc[-1])
note_lines = [
    f"Backtest window: {level.index[0].date()} → {level.index[-1].date()}.",
    f"<b>P&L decomposition (bps):</b> "
    f"directional {dir_total:+.0f}  ·  "
    f"carry {carry_total:+.0f}  ·  "
    f"convexity {conv_total:+.0f}  ·  "
    f"transaction cost {tcost_total:+.0f}  →  total <b>{total_bps:+.0f}</b>.",
]
if not bake_carry:     note_lines.append("⚠️ Carry excluded by toggle.")
if not bake_convexity: note_lines.append("⚠️ Convexity excluded by toggle.")
if not bake_tcost:     note_lines.append("⚠️ Transaction costs excluded by toggle.")

render_signal_card(
    trade=("Rcv " if direction == "receive" else "Pay ") + "/".join(tenors),
    type_=trade_type,
    sharpe=sharpe,
    z=_z,
    expected_return_bps_yr=ann_bps,
    risk_bps_yr=vol_bps,
    hit_rate_pct=positive,
    max_dd_bps=max_dd,
    days=days,
    direction=direction,
    note=" ".join(note_lines),
)

# P&L breakdown — explicit cards (5 components: dir + carry + conv − tcost = total)
brk1, brk2, brk3, brk4, brk5 = st.columns(5)
brk1.metric("Directional",      f"{dir_total:+.0f} bps")
_carry_delta = (
    f"entry {carry_annual_bps:+.0f} → avg {carry_avg_annual_bps:+.0f} bps/yr"
    if bake_carry else "off"
)
brk2.metric("Carry (path-dependent)", f"{carry_total:+.0f} bps",
            delta=_carry_delta)
brk3.metric("Convexity (½·C·Δy²)", f"{conv_total:+.0f} bps",
            delta=(f"avg {conv_annual_avg_bps:+.0f} bps/yr"
                   if bake_convexity else "off"))
brk4.metric("Transaction cost", f"{tcost_total:+.0f} bps",
            delta=f"−{tcost_bps:.1f} bps round-trip" if bake_tcost else "off")
brk5.metric("Total",            f"{total_bps:+.0f} bps")
with st.expander("Units key"):
    render_units_legend()

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

# ── Carry path chart (path-dependent only) ───────────────────────────────
if bake_carry:
    with st.expander("📈 Carry path — daily accrual & cumulative carry"):
        # Reconstruct the daily-carry series for the chart
        _daily_carry_annual = carry_cum.diff().fillna(carry_cum.iloc[0]) * 252
        f_carry = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                  vertical_spacing=0.05, row_heights=[0.55, 0.45],
                                  subplot_titles=("Cumulative carry (bps)",
                                                  "Annualised carry rate (bps/yr)"))
        f_carry.add_trace(go.Scatter(
            x=carry_cum.index, y=carry_cum.values, name="Cumulative carry",
            line=dict(color="#fbbf24", width=2),
            fill="tozeroy", fillcolor="rgba(251,191,36,0.08)",
        ), row=1, col=1)
        f_carry.add_hline(y=0, line_dash="dot", line_color="#94a8c9",
                          line_width=1, row=1, col=1)
        f_carry.add_trace(go.Scatter(
            x=_daily_carry_annual.index, y=_daily_carry_annual.values,
            name="Annualised carry rate",
            line=dict(color="#a78bfa", width=1.5),
        ), row=2, col=1)
        f_carry.add_hline(y=carry_avg_annual_bps, line_dash="dash",
                          line_color="#94a8c9", line_width=1,
                          annotation_text=f"Avg {carry_avg_annual_bps:+.0f}",
                          annotation_position="right",
                          row=2, col=1)
        f_carry.update_layout(template=PLOTLY_THEME, height=440,
                               margin=dict(l=10, r=10, t=40, b=10),
                               showlegend=False)
        st.plotly_chart(f_carry, use_container_width=True)
        st.caption(
            "Carry is recomputed every day from the prevailing curve via "
            "`fixed_income.forward_carry_rolldown`. The annualised rate "
            "(bottom panel) shows how rich/cheap carry on this trade was "
            "throughout the holding window — flat = stable curve, dispersed "
            "= position lived through different carry environments."
        )

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
        "level":              level,
        "directional_bps":    directional_cum,
        "carry_bps":          carry_cum,
        "convexity_bps":      conv_cum,
        "tcost_bps":          tcost_cum,
        "cumulative_pnl_bps": cum,
        "daily_pnl_bps":      daily_pnl,
        "drawdown_bps":       drawdown,
    })
    csv = out.to_csv()
    st.download_button("⬇️ Download CSV", data=csv,
                       file_name=f"backtest_{_trade_name().replace(' ','_')}.csv",
                       mime="text/csv", use_container_width=True)
