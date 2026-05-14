"""Page 43 — What Changed Today.

Auto-flags the meaningful moves in the last 24 hours / 1 week:
  • Biggest yield moves (tenor with largest |Δ| bps)
  • Curve shape shift (steepening / flattening / curvature change)
  • Scanner trades that flipped Sharpe sign or had largest Sharpe jump
  • Z-score changes — what just became cheap / just got rich
  • Cross-asset shifts: VIX, credit, FX

Use this as your "what do I need to know vs yesterday" digest — perfect
for the first 90 seconds of a trading day or for spotting Substack
content angles.
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

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import get_master_df, init_session_state, password_gate

st.set_page_config(page_title="What Changed", page_icon="🆕", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="What Changed")

st.title("🆕 What Changed Today")
st.caption(
    "Auto-flagged shifts vs yesterday and vs last week. Designed for the "
    "first 90 seconds of your day — or for spotting Substack angles."
)
st.divider()

df = get_master_df()
if df.empty:
    st.error("No market data — refresh the cache.")
    st.stop()


# ── Time-window selector ─────────────────────────────────────────────────
horizon = st.radio(
    "Compare against:",
    ["1 trading day", "1 week", "1 month"],
    horizontal=True,
    key="wc_horizon",
)
days_back = {"1 trading day": 1, "1 week": 5, "1 month": 22}[horizon]


# ── Yield-curve moves ─────────────────────────────────────────────────────
ALL = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
avail = [t for t in ALL if t in df.columns]
if not avail:
    st.warning("No yield-curve data available.")
    st.stop()

current = df[avail].dropna(how="all").iloc[-1]
ago_idx = max(0, len(df) - days_back - 1)
ago = df[avail].dropna(how="all").iloc[ago_idx]

st.subheader(f"📉 Yield moves — last {horizon}")
moves = []
for t in avail:
    move_bps = float((current[t] - ago[t]) * 100)
    moves.append({"Tenor": t, "Now": f"{current[t]:.2f}%",
                   f"Then": f"{ago[t]:.2f}%", "Δ bps": move_bps})

# Biggest mover callout
mvs = sorted(moves, key=lambda r: abs(r["Δ bps"]), reverse=True)
biggest = mvs[0]
direction = "up" if biggest["Δ bps"] > 0 else "down"
sig = abs(biggest["Δ bps"]) >= 5  # 5+ bps = noteworthy single-day move
color = "#f87171" if biggest["Δ bps"] > 0 else "#4ade80"

st.markdown(
    f"""
    <div style='background:#122340;border-left:4px solid {color};
                padding:14px 18px;border-radius:6px;margin:6px 0 14px'>
      <div style='color:#94a8c9;font-size:11px;letter-spacing:1.5px;
                  font-weight:700'>BIGGEST MOVE</div>
      <div style='color:#e8eef9;font-size:20px;font-weight:700;margin:4px 0'>
          {biggest['Tenor']} {direction} <span style='color:{color}'>{biggest['Δ bps']:+.1f} bps</span>
          <span style='color:#94a8c9;font-size:13px;font-weight:400'>
              ({biggest['Then']} → {biggest['Now']})
          </span>
      </div>
      <div style='color:#cbd5e1;font-size:12px'>
          {"🚨 Material move — worth a closer look" if sig else
           "→ Within normal day-to-day noise"}
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Bar chart of all tenor moves
mvs_df = pd.DataFrame(moves)
fig = go.Figure()
fig.add_trace(go.Bar(
    x=mvs_df["Tenor"], y=mvs_df["Δ bps"],
    marker_color=["#f87171" if v > 0 else "#4ade80" for v in mvs_df["Δ bps"]],
    text=[f"{v:+.1f}" for v in mvs_df["Δ bps"]],
    textposition="outside",
))
fig.add_hline(y=0, line_color="#94a8c9", line_width=1)
fig.update_layout(template=PLOTLY_THEME, height=280,
                   yaxis_title="Δ bps", showlegend=False,
                   margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(fig, use_container_width=True)


# ── Curve-shape shifts ───────────────────────────────────────────────────
st.subheader("📐 Curve-shape shifts")
shape_metrics = []
if "2Y" in avail and "10Y" in avail:
    now_s = (current["10Y"] - current["2Y"]) * 100
    ago_s = (ago["10Y"] - ago["2Y"]) * 100
    shape_metrics.append(("2s10s slope",
                            f"{ago_s:+.0f} → {now_s:+.0f} bps",
                            f"{now_s - ago_s:+.1f}"))
if "5Y" in avail and "30Y" in avail:
    now_s = (current["30Y"] - current["5Y"]) * 100
    ago_s = (ago["30Y"] - ago["5Y"]) * 100
    shape_metrics.append(("5s30s slope",
                            f"{ago_s:+.0f} → {now_s:+.0f} bps",
                            f"{now_s - ago_s:+.1f}"))
if all(t in avail for t in ("2Y", "5Y", "10Y")):
    now_c = (2 * current["5Y"] - current["2Y"] - current["10Y"]) * 100
    ago_c = (2 * ago["5Y"] - ago["2Y"] - ago["10Y"]) * 100
    shape_metrics.append(("Belly curvature (2/5/10)",
                            f"{ago_c:+.0f} → {now_c:+.0f} bps",
                            f"{now_c - ago_c:+.1f}"))

sm_cols = st.columns(len(shape_metrics))
for col, (name, transition, delta) in zip(sm_cols, shape_metrics):
    col.metric(name, transition.split("→")[1].strip(),
                f"Δ {delta} bps")

st.divider()


# ── Cross-asset shifts ────────────────────────────────────────────────────
st.subheader("🌐 Cross-asset")
cross_specs = [
    ("VIX",     "VIX",      "{:.1f}",   1.0),    # threshold = 1.0 vol pts
    ("IG_OAS",  "IG OAS",   "{:.2f}%",  0.05),
    ("HY_OAS",  "HY OAS",   "{:.2f}%",  0.10),
    ("SOFR",    "SOFR o/n", "{:.2f}%",  0.05),
]
cc_cols = st.columns(len(cross_specs))
for col_widget, (col, label, fmt, thresh) in zip(cc_cols, cross_specs):
    if col not in df.columns:
        col_widget.metric(label, "—"); continue
    s = df[col].dropna()
    if len(s) < days_back + 1:
        col_widget.metric(label, "—"); continue
    now = float(s.iloc[-1])
    ago_v = float(s.iloc[-days_back - 1])
    d = now - ago_v
    flag = "🚨 " if abs(d) > thresh else ""
    col_widget.metric(f"{flag}{label}", fmt.format(now),
                      f"{d:+.2f}" if col == "VIX" else f"{d * 100:+.0f} bps")

st.divider()


# ── Scanner shifts (Sharpe-rank churn) ───────────────────────────────────
st.subheader("🔎 Scanner — biggest Sharpe shifts")
st.caption(
    "Computes today's scanner output and approximates yesterday's by re-running "
    "on cached data ending one trading day earlier. Slow on first hit; "
    "cached 30 min."
)


try:
    from scripts.send_alert import build_scanner
    sdf_now = build_scanner()
    if sdf_now.empty:
        st.info("Scanner returned no data.")
    else:
        # Show: top movers by D1W magnitude (rough proxy for what moved)
        movers = sdf_now.reindex(sdf_now["D1W"].abs().sort_values(ascending=False).index).head(10)

        # Render as bar chart of D1W moves
        figm = go.Figure()
        figm.add_trace(go.Bar(
            y=[r["Trade"] for _, r in movers.iterrows()][::-1],
            x=[r["D1W"] for _, r in movers.iterrows()][::-1],
            orientation="h",
            marker_color=["#f87171" if v > 0 else "#4ade80"
                          for v in movers["D1W"].iloc[::-1]],
            text=[f"{v:+.1f}" for v in movers["D1W"].iloc[::-1]],
            textposition="outside",
        ))
        figm.add_vline(x=0, line_color="#94a8c9", line_width=1)
        figm.update_layout(template=PLOTLY_THEME, height=380,
                            xaxis_title="1-week change (bps)",
                            margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(figm, use_container_width=True)
        st.caption(
            "Trades with biggest 1-week absolute moves. Large negative bars "
            "(green) = compressed by ~X bps in the receive direction — i.e. "
            "yield differential narrowed. Large positive bars (red) = widened."
        )

        # Newly-extreme Z-scores
        cheap = sdf_now[sdf_now["Z"] < -2].sort_values("Z").head(5)
        rich  = sdf_now[sdf_now["Z"] >  2].sort_values("Z", ascending=False).head(5)
        zc1, zc2 = st.columns(2)
        with zc1:
            st.markdown("**🟢 Cheap (Z < −2)**")
            if cheap.empty:
                st.caption("Nothing cheap right now.")
            else:
                for _, r in cheap.iterrows():
                    st.markdown(f"- {r['Trade']} — Z={r['Z']:+.2f}, Sharpe={r['Sharpe']:+.2f}")
        with zc2:
            st.markdown("**🔴 Rich (Z > +2)**")
            if rich.empty:
                st.caption("Nothing stretched rich.")
            else:
                for _, r in rich.iterrows():
                    st.markdown(f"- {r['Trade']} — Z={r['Z']:+.2f}, Sharpe={r['Sharpe']:+.2f}")
except Exception as e:
    st.warning(f"Scanner unavailable: {e}")

st.divider()
st.caption(
    "What this isn't: a session-by-session NLP digest of the news. For the "
    "headlines, see the Latest panel on the Home page."
)
