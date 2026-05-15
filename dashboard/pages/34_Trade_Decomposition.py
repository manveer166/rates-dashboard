"""Page 34 — Trade Decomposition.

Breaks the expected return of any outright / curve / fly into:
  • Carry      — funding cost (or benefit) of holding the position
  • Rolldown   — yield-curve-shape benefit (yield drifts to a lower point as
                 tenor shortens)
  • Mean rev.  — Z-score-driven reversion to historical mean

Plus a waterfall chart, a sensitivity table, and the "regime conditional
Sharpe" pulled from the same logic as the Regime page so the user gets the
full credibility picture in one screen.
"""

from __future__ import annotations

import sys
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

st.set_page_config(page_title="Trade Decomposition", page_icon="🧩", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Trade Decomposition")

from dashboard.components.premium_gate import premium_gate
if not premium_gate("Trade Decomposition"):
    st.stop()

st.title("🧩 Trade Decomposition")
st.caption(
    "Breaks expected return into carry, rolldown, and mean-reversion. "
    "Same forward-carry math the scanner uses, plus a Z-score reversion "
    "estimate so you can see WHY a trade has positive (or negative) E[Ret]."
)
st.divider()

df = get_master_df()
if df.empty:
    st.error("No master data — refresh the cache.")
    st.stop()

ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
avail = [t for t in ALL_TENORS if t in df.columns]


# ── Inputs ────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns([1, 2, 1, 1])
with c1:
    structure = st.selectbox("Structure", ["Outright", "Curve", "Fly"], key="td_struct")
with c2:
    if structure == "Outright":
        tenors = [st.selectbox("Tenor", avail,
                                index=avail.index("10Y") if "10Y" in avail else 0,
                                key="td_t1")]
    elif structure == "Curve":
        cc1, cc2 = st.columns(2)
        t1 = cc1.selectbox("Short leg", avail,
                            index=avail.index("2Y") if "2Y" in avail else 0,
                            key="td_c1")
        t2 = cc2.selectbox("Long leg", avail,
                            index=avail.index("10Y") if "10Y" in avail else -1,
                            key="td_c2")
        tenors = [t1, t2]
    else:
        cc1, ccb, cc2 = st.columns(3)
        w1 = cc1.selectbox("Front wing", avail,
                            index=avail.index("2Y") if "2Y" in avail else 0,
                            key="td_w1")
        b  = ccb.selectbox("Belly",      avail,
                            index=avail.index("5Y") if "5Y" in avail else 0,
                            key="td_b")
        w2 = cc2.selectbox("Back wing",  avail,
                            index=avail.index("10Y") if "10Y" in avail else -1,
                            key="td_w2")
        tenors = [w1, b, w2]
with c3:
    direction = st.selectbox("Direction", ["receive", "pay"], key="td_dir")
with c4:
    holding = st.selectbox("Holding period",
                            [("1 month", 1.0), ("3 months", 3.0), ("6 months", 6.0),
                             ("1 year", 12.0)],
                            format_func=lambda x: x[0] if isinstance(x, tuple) else x,
                            key="td_hold")
    holding_months = holding[1]

st.divider()

# ── Pull current curve + overnight rate ──────────────────────────────────
last = df.dropna(subset=avail, how="all").iloc[-1]
curve = {t: float(last[t]) for t in avail if pd.notna(last[t])}

on_rate = 5.3
for col in ("SOFR", "DFF", "EFFR"):
    if col in df.columns:
        s = df[col].dropna()
        if len(s):
            on_rate = float(s.iloc[-1])
            break


# ── Compute carry + rolldown via fixed_income lib ────────────────────────
import fixed_income as fi

TYPE_MAP = {"Outright": "outright", "Curve": "spread", "Fly": "fly"}
ti = TYPE_MAP[structure]

if ti == "outright":
    cr = fi.forward_carry_rolldown(curve, on_rate, "outright",
                                    tenor1=tenors[0],
                                    holding_months=holding_months)
elif ti == "spread":
    # Convention: tenor1 = long, tenor2 = short (matches scanner)
    cr = fi.forward_carry_rolldown(curve, on_rate, "spread",
                                    tenor1=tenors[1], tenor2=tenors[0],
                                    holding_months=holding_months)
else:
    cr = fi.forward_carry_rolldown(curve, on_rate, "fly",
                                    tenor1=tenors[0], tenor2=tenors[1],
                                    tenor3=tenors[2],
                                    holding_months=holding_months)

# Sign for direction (lib returns receive-side; flip for pay)
sign = 1.0 if direction == "receive" else -1.0
carry_bps    = sign * cr["carry"]
rolldown_bps = sign * cr["rolldown"]
total_cr_bps = carry_bps + rolldown_bps   # excluding mean reversion


# ── Compute mean reversion premium — empirical OU fit ────────────────────
# Replaces the previous 50%-per-year heuristic with a fitted half-life
# from the trade's own price history. The Methodology page documents the
# model (Ornstein-Uhlenbeck via AR(1) regression).
def _spread_series():
    if ti == "outright":
        return df[tenors[0]].dropna()
    if ti == "spread":
        # Conventional spread (not DV01-weighted) — easier to fit + interpret
        return (df[tenors[1]] - df[tenors[0]]).dropna()
    # Conventional fly: belly − 0.5 × (wing1 + wing2)
    return (df[tenors[1]] - 0.5 * (df[tenors[0]] + df[tenors[2]])).dropna()

spread_ts = _spread_series().tail(252)
if len(spread_ts) >= 60 and spread_ts.std() > 0:
    z_now = float((spread_ts.iloc[-1] - spread_ts.mean()) / spread_ts.std())
else:
    z_now = 0.0

# Fit OU and project over the user-selected holding period (in trading days)
horizon_days = int(round(holding_months * 21.0))   # ~21 BDays / month
ou_fit = fi.fit_ou(spread_ts, window_days=252, horizon_days=horizon_days)
# Sign: for a receive trade, level falling = positive P&L.
# fit.expected_move_h is signed (μ − X_0)(1 − b^h): negative if X_0 > μ.
# So receive_pnl = -expected_move × 100 (bps) × sign for direction.
mean_rev_bps = -sign * ou_fit.expected_move_h * 100.0 if ou_fit.valid else 0.0

total_exp_bps = carry_bps + rolldown_bps + mean_rev_bps


# ── Trade name ───────────────────────────────────────────────────────────
def _trade_name():
    d = direction.capitalize()
    if structure == "Outright": return f"{d} {tenors[0]}"
    if structure == "Curve":    return f"{d} {tenors[0]}/{tenors[1]} curve"
    return f"{d} {tenors[0]}{tenors[1]}{tenors[2]} fly"

st.subheader(f"📊 {_trade_name()}  ·  {holding[0]} horizon")

# ── Headline metrics ─────────────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Carry",         f"{carry_bps:+.1f} bps")
m2.metric("Rolldown",      f"{rolldown_bps:+.1f} bps")
m3.metric("Mean reversion",f"{mean_rev_bps:+.1f} bps")
m4.metric("Total E[Ret]",  f"{total_exp_bps:+.1f} bps",
          delta=f"{total_exp_bps * 12 / holding_months:+.0f} bps/yr")
m5.metric("Z-score (1Y)",  f"{z_now:+.2f}")

st.divider()

# ── Waterfall chart ──────────────────────────────────────────────────────
st.subheader("📐 Component waterfall")
fig = go.Figure(go.Waterfall(
    orientation="v",
    measure=["relative", "relative", "relative", "total"],
    x=["Carry", "Rolldown", "Mean reversion", "Total E[Ret]"],
    text=[f"{carry_bps:+.1f}",
          f"{rolldown_bps:+.1f}",
          f"{mean_rev_bps:+.1f}",
          f"{total_exp_bps:+.1f}"],
    y=[carry_bps, rolldown_bps, mean_rev_bps, total_exp_bps],
    connector={"line": {"color": "#94a8c9"}},
    increasing={"marker": {"color": "#4ade80"}},
    decreasing={"marker": {"color": "#f87171"}},
    totals={"marker": {"color": "#4fc3f7"}},
))
fig.update_layout(template=PLOTLY_THEME, height=380,
                  margin=dict(l=10, r=10, t=10, b=10),
                  yaxis_title=f"Expected return over {holding[0]} (bps)",
                  showlegend=False)
st.plotly_chart(fig, use_container_width=True)

# ── Plain-English read ───────────────────────────────────────────────────
def _share(x):
    return abs(x) / max(abs(carry_bps) + abs(rolldown_bps) + abs(mean_rev_bps), 0.01)

dominant = max(
    [("carry", carry_bps), ("rolldown", rolldown_bps), ("mean_rev", mean_rev_bps)],
    key=lambda kv: abs(kv[1]),
)[0]
share = _share({"carry": carry_bps, "rolldown": rolldown_bps,
                 "mean_rev": mean_rev_bps}[dominant])

label_map = {"carry": "carry (funding cost)",
             "rolldown": "rolldown (curve shape)",
             "mean_rev": "mean reversion (Z-score)"}

st.markdown(
    f"**Read:** total expected return is **{total_exp_bps:+.1f} bps** over "
    f"{holding[0]}, driven primarily by **{label_map[dominant]}** "
    f"({share*100:.0f}% of absolute contribution). "
    + ("Trade is **carry-positive** — gets paid to hold even before any "
       "directional move." if carry_bps > 0 else
       "Trade is **carry-negative** — costs to hold; needs the directional "
       "thesis to play out.")
)

st.divider()

# ── Sensitivity table ────────────────────────────────────────────────────
st.subheader("🔧 Sensitivity to curve shifts")
st.caption(
    "How total expected return changes if the level / slope / curvature "
    "shifts by ±5 / ±10 bps. Useful for sizing risk against your view."
)

# Scenarios: parallel up/down + steepener/flattener
scenarios = [
    ("Parallel +10 bps",   {t: 0.10 for t in tenors}),
    ("Parallel +5 bps",    {t: 0.05 for t in tenors}),
    ("Unchanged",          {t: 0.00 for t in tenors}),
    ("Parallel -5 bps",    {t: -0.05 for t in tenors}),
    ("Parallel -10 bps",   {t: -0.10 for t in tenors}),
]
# Add steepener / flattener if it's a 2- or 3-leg trade
if structure == "Curve":
    t1, t2 = tenors
    scenarios.append(("Steepener +10 (long)",  {t1: 0.0,  t2: 0.10}))
    scenarios.append(("Flattener -10 (long)",  {t1: 0.0,  t2: -0.10}))
elif structure == "Fly":
    w1, b, w2 = tenors
    scenarios.append(("Belly cheapens +5",     {w1: 0.0, b: 0.05, w2: 0.0}))
    scenarios.append(("Belly richens -5",      {w1: 0.0, b: -0.05, w2: 0.0}))

rows = []
for name, shifts in scenarios:
    new_curve = {t: curve.get(t, 0) + shifts.get(t, 0) for t in curve}
    if ti == "outright":
        cr2 = fi.forward_carry_rolldown(new_curve, on_rate, "outright",
                                          tenor1=tenors[0],
                                          holding_months=holding_months)
    elif ti == "spread":
        cr2 = fi.forward_carry_rolldown(new_curve, on_rate, "spread",
                                          tenor1=tenors[1], tenor2=tenors[0],
                                          holding_months=holding_months)
    else:
        cr2 = fi.forward_carry_rolldown(new_curve, on_rate, "fly",
                                          tenor1=tenors[0], tenor2=tenors[1],
                                          tenor3=tenors[2],
                                          holding_months=holding_months)
    new_total = sign * (cr2["carry"] + cr2["rolldown"]) + mean_rev_bps
    delta = new_total - total_exp_bps
    rows.append({
        "Scenario":   name,
        "New E[Ret]": round(new_total, 1),
        "Δ vs base":  round(delta, 1),
    })
sens_df = pd.DataFrame(rows)
st.dataframe(sens_df, use_container_width=True, hide_index=True,
             column_config={
                 "New E[Ret]": st.column_config.NumberColumn(format="%+.1f bps"),
                 "Δ vs base":  st.column_config.NumberColumn(format="%+.1f bps"),
             })

# ── Footer notes ─────────────────────────────────────────────────────────
st.divider()
st.caption(
    "**Mean reversion:** fitted Ornstein-Uhlenbeck process — half-life and "
    "long-run mean estimated by AR(1) regression on the trade's own 1-year "
    "history. Expected P&L = direction × (μ − X_0) × (1 − exp(−θ · h)) × 100, "
    f"where the fitted half-life is **{ou_fit.half_life_days:.0f} days** and "
    f"R² = {ou_fit.r_squared:.2f} (high R² ⇒ trustworthy fit). "
    "See [Methodology](/Methodology) for the full derivation."
)
