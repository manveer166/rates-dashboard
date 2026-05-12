"""Page 25 — Trade Construction Wizard.

Designs a DV01-neutral curve or fly given target risk (DV01 budget or notional
on the belly), shows leg sizes, current carry/roll proxy, current spread, and
1Y z-score — and emits a clean trade ticket for the desk.

The wizard mirrors the scanner's DV01 convention so anything you build here
shows up consistently on the Analysis / Backtester pages.
"""

import sys
from datetime import date
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

st.set_page_config(page_title="Trade Builder", page_icon="🧰", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Trade Builder")

from dashboard.components.premium_gate import premium_gate
if not premium_gate("Trade Builder"):
    st.stop()

st.title("🧰 Trade Construction Wizard")
st.caption(
    "Designs a DV01-neutral curve or fly. Pick tenors → set risk budget → "
    "get leg sizes, live spread, z-score, and a copy-pasteable ticket."
)
st.divider()

df = get_master_df()
if df.empty:
    st.error("No master data — refresh the cache.")
    st.stop()

ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
avail = [t for t in ALL_TENORS if t in df.columns]
TENOR_YEARS = {"2Y":2,"3Y":3,"5Y":5,"7Y":7,"10Y":10,"20Y":20,"30Y":30}

# ── DV01 helper (par-bond approximation) ──────────────────────────────────
def dv01_per_100(tenor: str, yld: float) -> float:
    """Approx DV01 per $100 par for a par-coupon bond. Returns $ per bp."""
    n = TENOR_YEARS[tenor] * 2
    y = max(yld / 100.0, 0.001) / 2
    pv_annuity = sum(1 / (1 + y) ** k for k in range(1, n + 1))
    pv_principal = 1 / (1 + y) ** n
    # Sensitivity ≈ duration; use Macaulay-style approximation
    weighted = (sum(k * 1 / (1 + y) ** k for k in range(1, n + 1)) + n * pv_principal)
    duration = weighted / 2  # in years (semi-annual cashflows → divide by 2)
    return duration * 100 / 10000  # $ per bp per $100 par

# ── Inputs ────────────────────────────────────────────────────────────────
c1, c2 = st.columns([1, 3])
with c1:
    structure = st.radio("Structure", ["Curve (2-leg)", "Fly (3-leg)"], key="tb_struct")
with c2:
    if structure.startswith("Curve"):
        cc1, cc2 = st.columns(2)
        with cc1:
            t1 = st.selectbox("Short leg",
                               avail, index=avail.index("2Y") if "2Y" in avail else 0,
                               key="tb_c1")
        with cc2:
            t2 = st.selectbox("Long leg",
                               avail, index=avail.index("10Y") if "10Y" in avail else -1,
                               key="tb_c2")
        tenors = [t1, t2]
    else:
        cc1, ccb, cc2 = st.columns(3)
        with cc1:
            wing1 = st.selectbox("Front wing", avail,
                                  index=avail.index("2Y") if "2Y" in avail else 0,
                                  key="tb_w1")
        with ccb:
            belly = st.selectbox("Belly",      avail,
                                  index=avail.index("5Y") if "5Y" in avail else 0,
                                  key="tb_bl")
        with cc2:
            wing2 = st.selectbox("Back wing",  avail,
                                  index=avail.index("10Y") if "10Y" in avail else -1,
                                  key="tb_w2")
        tenors = [wing1, belly, wing2]

direction = st.selectbox("Direction", ["receive", "pay"], key="tb_dir")

# ── Risk budget ───────────────────────────────────────────────────────────
budget_mode = st.radio(
    "Risk budget",
    ["Belly notional ($mm)", "Total DV01 ($/bp)"],
    horizontal=True, key="tb_budget",
)
if budget_mode == "Belly notional ($mm)":
    notional = st.number_input("Belly / long-leg notional ($mm)",
                                value=100.0, min_value=1.0, step=10.0,
                                help="For curves: notional on the long leg. For flies: belly leg.")
else:
    target_dv01 = st.number_input("Target DV01 per leg ($/bp)",
                                   value=100_000.0, min_value=1_000.0, step=10_000.0)

st.divider()

# ── Compute weights + sized legs ──────────────────────────────────────────
last = df.iloc[-1]
yields = {t: float(last[t]) for t in tenors if t in df.columns and pd.notna(last[t])}
if any(t not in yields for t in tenors):
    st.warning("Some selected tenors have no data on the latest date.")
    st.stop()

# DV01 per $100 par at current yields
dv01_unit = {t: dv01_per_100(t, yields[t]) for t in tenors}

sign = -1.0 if direction == "receive" else 1.0

if structure.startswith("Curve"):
    t1, t2 = tenors
    if budget_mode == "Belly notional ($mm)":
        notional_long = notional
        # $ DV01 of long leg
        dv01_long = notional_long * 1_000_000 / 100 * dv01_unit[t2]
        # Short leg matches DV01
        notional_short = dv01_long / (dv01_unit[t1] * 1_000_000 / 100)
    else:
        dv01_long = target_dv01
        dv01_short = target_dv01
        notional_long  = dv01_long  / (dv01_unit[t2] * 1_000_000 / 100)
        notional_short = dv01_short / (dv01_unit[t1] * 1_000_000 / 100)

    legs = [
        {"Tenor": t2, "Side": "Receive" if direction == "receive" else "Pay",
         "Notional ($mm)": round(notional_long, 2),
         "DV01 ($/bp)": round(notional_long * 1_000_000 / 100 * dv01_unit[t2], 0),
         "Yield (%)": round(yields[t2], 3)},
        {"Tenor": t1, "Side": "Pay" if direction == "receive" else "Receive",
         "Notional ($mm)": round(notional_short, 2),
         "DV01 ($/bp)": round(notional_short * 1_000_000 / 100 * dv01_unit[t1], 0),
         "Yield (%)": round(yields[t1], 3)},
    ]
    # Spread and z
    sub = df[[t1, t2]].dropna()
    ratio = dv01_unit[t2] / dv01_unit[t1]
    spread = sub[t2] - ratio * sub[t1]
    spread_now = float(spread.iloc[-1])
    spread_z = float((spread.iloc[-1] - spread.tail(252).mean()) / spread.tail(252).std()) \
               if spread.tail(252).std() > 0 else 0.0
    spread_label = f"DV01-weighted spread ({t1}/{t2})"
else:
    w1, b, w2 = tenors
    # Belly receives twice the DV01 weight; wings each carry half (DV01-neutral)
    if budget_mode == "Belly notional ($mm)":
        notional_belly = notional
        dv01_belly = notional_belly * 1_000_000 / 100 * dv01_unit[b]
        # Each wing carries half the belly DV01
        dv01_wing = dv01_belly / 2.0
        notional_w1 = dv01_wing / (dv01_unit[w1] * 1_000_000 / 100)
        notional_w2 = dv01_wing / (dv01_unit[w2] * 1_000_000 / 100)
    else:
        dv01_belly = 2 * target_dv01
        dv01_wing  = target_dv01
        notional_belly = dv01_belly / (dv01_unit[b]  * 1_000_000 / 100)
        notional_w1    = dv01_wing  / (dv01_unit[w1] * 1_000_000 / 100)
        notional_w2    = dv01_wing  / (dv01_unit[w2] * 1_000_000 / 100)

    legs = [
        {"Tenor": b, "Side": "Receive" if direction == "receive" else "Pay",
         "Notional ($mm)": round(notional_belly, 2),
         "DV01 ($/bp)": round(notional_belly * 1_000_000 / 100 * dv01_unit[b], 0),
         "Yield (%)": round(yields[b], 3)},
        {"Tenor": w1, "Side": "Pay" if direction == "receive" else "Receive",
         "Notional ($mm)": round(notional_w1, 2),
         "DV01 ($/bp)": round(notional_w1 * 1_000_000 / 100 * dv01_unit[w1], 0),
         "Yield (%)": round(yields[w1], 3)},
        {"Tenor": w2, "Side": "Pay" if direction == "receive" else "Receive",
         "Notional ($mm)": round(notional_w2, 2),
         "DV01 ($/bp)": round(notional_w2 * 1_000_000 / 100 * dv01_unit[w2], 0),
         "Yield (%)": round(yields[w2], 3)},
    ]
    sub = df[[w1, b, w2]].dropna()
    wb  = 2.0 * dv01_unit[w1] / dv01_unit[b]
    ww2 = dv01_unit[w1] / dv01_unit[w2]
    spread = wb * sub[b] - sub[w1] - ww2 * sub[w2]
    spread_now = float(spread.iloc[-1])
    spread_z = float((spread.iloc[-1] - spread.tail(252).mean()) / spread.tail(252).std()) \
               if spread.tail(252).std() > 0 else 0.0
    spread_label = f"DV01-weighted fly ({w1}/{b}/{w2})"

# ── Output: legs table ────────────────────────────────────────────────────
st.subheader("📋 Trade legs (DV01-neutral)")
legs_df = pd.DataFrame(legs)
st.dataframe(legs_df, use_container_width=True, hide_index=True)

# DV01 net check
dv01_total = sum(l["DV01 ($/bp)"] * (1 if l["Side"] == "Receive" else -1) for l in legs)
st.caption(f"Net DV01: **${dv01_total:+,.0f}/bp** "
           f"(should be ≈ 0 for DV01-neutral). ")

# ── Spread context ────────────────────────────────────────────────────────
st.subheader("📐 Spread context")
sc1, sc2, sc3 = st.columns(3)
sc1.metric("Current level", f"{spread_now:.3f}")
sc2.metric("1Y mean",       f"{spread.tail(252).mean():.3f}")
sc3.metric("Z-score (1Y)",  f"{spread_z:+.2f}")

# Mini chart
f = go.Figure()
last_year = spread.tail(252)
f.add_trace(go.Scatter(x=last_year.index, y=last_year.values,
                       line=dict(color="#4fc3f7", width=2)))
f.add_hline(y=last_year.mean(), line_dash="dash", line_color="#94a8c9",
            annotation_text=f"1Y mean {last_year.mean():.2f}",
            annotation_position="right")
f.add_hline(y=spread_now, line_dash="dot", line_color="#fbbf24",
            annotation_text="Now", annotation_position="left")
f.update_layout(template=PLOTLY_THEME, height=300,
                margin=dict(l=10, r=10, t=10, b=10),
                yaxis_title=spread_label, showlegend=False)
st.plotly_chart(f, use_container_width=True)

st.divider()

# ── Trade ticket (copy-pasteable) ─────────────────────────────────────────
st.subheader("📝 Trade ticket")
ticket_lines = [
    f"TRADE TICKET  ·  {date.today().strftime('%d %b %Y')}",
    "=" * 50,
    f"Structure:  {structure}",
    f"Direction:  {direction.upper()}",
    "",
    "Legs:",
]
for leg in legs:
    ticket_lines.append(
        f"  {leg['Side']:8s} {leg['Notional ($mm)']:>8.2f}mm "
        f"{leg['Tenor']:4s}  @ {leg['Yield (%)']:.3f}%  "
        f"(DV01 ${leg['DV01 ($/bp)']:>8,.0f}/bp)"
    )
ticket_lines += [
    "",
    f"Spread:     {spread_now:+.3f}  ({spread_label})",
    f"1Y mean:    {spread.tail(252).mean():+.3f}",
    f"Z-score:    {spread_z:+.2f}",
    "",
    f"Net DV01:   ${dv01_total:+,.0f}/bp  (DV01-neutral target = $0)",
]
ticket = "\n".join(ticket_lines)
st.code(ticket, language=None)
st.download_button("⬇️ Download ticket",
                   data=ticket.encode("utf-8"),
                   file_name=f"ticket_{date.today().isoformat()}.txt",
                   mime="text/plain", use_container_width=True)
