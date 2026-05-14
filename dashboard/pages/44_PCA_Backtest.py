"""Page 44 — Curve PCA Backtest.

Runs a mean-reversion strategy on the yield curve's principal components:
  • Compute PC1 (level), PC2 (slope), PC3 (curvature) of the 2Y–30Y curve
  • Each PC has its own z-score series (rolling 1Y)
  • Strategy:  go long the PC when z < -threshold (mean-revert up)
               go short when z > +threshold
               flat in between
  • PnL = position × (next-day change in PC score)
  • Sharpe / hit-rate / max DD computed for each PC + portfolio

Result: a defensible backtest of "is z-score mean-reversion actually a
strategy?" rather than a heuristic.
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
from plotly.subplots import make_subplots
import streamlit as st

try:
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    SKLEARN_OK = True
except ImportError:
    SKLEARN_OK = False

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.components.signal_card import render_signal_card, render_market_kpi_row
from dashboard.state import get_master_df, init_session_state, password_gate

st.set_page_config(page_title="PCA Backtest", page_icon="🧮", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="PCA Backtest")

st.title("🧮 Curve PCA Backtest")
st.caption(
    "How well does mean-reversion on curve principal components actually work? "
    "We decompose the yield curve into level / slope / curvature, then trade "
    "the z-score of each PC against itself."
)
st.divider()

if not SKLEARN_OK:
    st.error("scikit-learn missing in venv. `pip install scikit-learn` to enable.")
    st.stop()

df = get_master_df()
if df.empty:
    st.error("No master data — refresh the cache.")
    st.stop()

ALL = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
avail = [t for t in ALL if t in df.columns]
if len(avail) < 5:
    st.warning("Need 5+ tenors for a meaningful PCA.")
    st.stop()


# ── Inputs ────────────────────────────────────────────────────────────────
ic1, ic2, ic3 = st.columns(3)
with ic1:
    z_window = st.slider("Z-score window (days)", 30, 252, 126,
                          help="Rolling window for the PC z-score.")
with ic2:
    z_entry = st.slider("Entry threshold (|z|)", 0.5, 3.0, 1.5, 0.1,
                         help="Enter long when z < −X, short when z > +X.")
with ic3:
    z_exit = st.slider("Exit threshold (|z|)", 0.0, 2.0, 0.3, 0.1,
                        help="Flatten once |z| falls below this.")


# ── PCA fit on full history ───────────────────────────────────────────────
yields = df[avail].dropna()
scaler = StandardScaler()
X = scaler.fit_transform(yields.values)
pca = PCA(n_components=min(3, len(avail)))
scores = pca.fit_transform(X)
score_df = pd.DataFrame(scores, index=yields.index,
                         columns=[f"PC{i+1}" for i in range(scores.shape[1])])

# Loadings: how each tenor contributes to each PC
loadings = pd.DataFrame(pca.components_.T, index=avail,
                         columns=[f"PC{i+1}" for i in range(scores.shape[1])])

# Top KPI strip — variance explained
explained = pca.explained_variance_ratio_
render_market_kpi_row([
    {"label": f"PC{i+1}",
     "value": f"{explained[i]*100:.1f}%",
     "unit": "var explained",
     "hint": "level"  if i == 0 else "slope" if i == 1 else "curvature" if i == 2 else "",
     "color": ["#4fc3f7", "#fb923c", "#a78bfa"][i % 3]}
    for i in range(len(explained))
])

st.divider()


# ── PC loadings visualisation ────────────────────────────────────────────
st.subheader("🧬 Loadings — how each tenor contributes to each PC")
fig_load = go.Figure()
colors_pc = ["#4fc3f7", "#fb923c", "#a78bfa"]
for i, pc in enumerate(loadings.columns):
    fig_load.add_trace(go.Bar(
        name=pc, x=loadings.index, y=loadings[pc],
        marker_color=colors_pc[i % 3],
    ))
fig_load.update_layout(template=PLOTLY_THEME, height=300, barmode="group",
                       yaxis_title="Loading", margin=dict(l=10, r=10, t=10, b=10),
                       legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                    xanchor="right", x=1))
st.plotly_chart(fig_load, use_container_width=True)
st.caption(
    "PC1 typically has all-positive loadings → parallel curve shifts (level). "
    "PC2 usually flips sign across tenors → slope (steepener/flattener). "
    "PC3 is the curvature mode (belly vs wings)."
)

st.divider()


# ── Z-score series for each PC ────────────────────────────────────────────
z_df = pd.DataFrame(index=score_df.index)
for pc in score_df.columns:
    rolling_mean = score_df[pc].rolling(z_window, min_periods=z_window // 2).mean()
    rolling_std  = score_df[pc].rolling(z_window, min_periods=z_window // 2).std()
    z_df[pc] = (score_df[pc] - rolling_mean) / rolling_std.replace(0, np.nan)


# ── Strategy: trade z-score mean-reversion on each PC ────────────────────
def _backtest(pc_name: str, z_series: pd.Series, pc_score: pd.Series) -> dict:
    """Mean-reversion strategy on a single PC."""
    pos = pd.Series(0.0, index=z_series.index)
    z = z_series.fillna(0)
    state = 0   # -1 short, 0 flat, +1 long
    for i, t in enumerate(z.index):
        if state == 0:
            if z.iloc[i] < -z_entry:  state = +1
            elif z.iloc[i] > +z_entry: state = -1
        else:
            # Exit when z reverts past the exit band
            if abs(z.iloc[i]) < z_exit: state = 0
        pos.iloc[i] = state

    # Daily PnL = position × next-day change in PC score
    pc_chg = pc_score.diff().shift(-1).fillna(0)
    daily = pos * pc_chg
    cum = daily.cumsum()
    n = (pos != 0).sum()
    sharpe = (daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0
    hit_rate = (daily[daily != 0] > 0).mean() * 100 if (daily != 0).any() else 0
    max_dd = float((cum - cum.cummax()).min())
    return {
        "name":    pc_name,
        "pos":     pos,
        "daily":   daily,
        "cum":     cum,
        "n_days":  int(n),
        "sharpe":  float(sharpe),
        "hit":     float(hit_rate),
        "max_dd":  max_dd,
        "total":   float(cum.iloc[-1]),
    }


results = []
for pc in z_df.columns:
    results.append(_backtest(pc, z_df[pc], score_df[pc]))


# ── Per-PC summary cards ─────────────────────────────────────────────────
st.subheader("📊 Per-PC strategy stats")
for i, r in enumerate(results):
    sub = pc_names = {"PC1": "Level", "PC2": "Slope", "PC3": "Curvature"}.get(r["name"], r["name"])
    render_signal_card(
        trade=f"Rcv {r['name']}",   # adapter — using card with synthetic label
        type_="Outright",
        sharpe=r["sharpe"],
        z=0.0,
        expected_return_bps_yr=r["total"] / max((r["pos"] != 0).sum(), 1) * 252,
        hit_rate_pct=r["hit"],
        max_dd_bps=r["max_dd"],
        days=r["n_days"],
        direction="receive",
        tags=[f"{r['name']} · {sub}",
              f"Entry |z| ≥ {z_entry}",
              f"Exit |z| < {z_exit}"],
        note=(f"Mean-reversion on the {sub.lower()} PC. Total cumulative PnL "
              f"of {r['total']:+.2f} score units across {r['n_days']} days in-market. "
              "Units here are PC-score points — to convert to bps, multiply by the "
              "loadings + standardised yields stdev."),
    )

st.divider()


# ── Combined portfolio chart ──────────────────────────────────────────────
st.subheader("📈 Cumulative strategy PnL")
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                    row_heights=[0.65, 0.35],
                    subplot_titles=("Cumulative PnL per PC",
                                    "Position over time"))
for i, r in enumerate(results):
    fig.add_trace(go.Scatter(
        x=r["cum"].index, y=r["cum"].values, name=f"{r['name']} cum PnL",
        line=dict(color=colors_pc[i % 3], width=2),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=r["pos"].index, y=r["pos"].values, name=f"{r['name']} pos",
        line=dict(color=colors_pc[i % 3], width=1, dash="dot"),
        showlegend=False,
    ), row=2, col=1)
fig.add_hline(y=0, line_color="#94a8c9", line_width=1, row=1, col=1)
fig.add_hline(y=0, line_color="#6a7e9e", line_width=1, row=2, col=1)
fig.update_yaxes(title_text="Score units", row=1, col=1)
fig.update_yaxes(title_text="-1 / 0 / +1", row=2, col=1, range=[-1.5, 1.5])
fig.update_layout(template=PLOTLY_THEME, height=520, hovermode="x unified",
                   margin=dict(l=10, r=10, t=40, b=10),
                   legend=dict(orientation="h", yanchor="bottom", y=1.06,
                                xanchor="right", x=1))
st.plotly_chart(fig, use_container_width=True)


# ── Z-score panels (so user sees what's driving the trades) ──────────────
st.subheader("📐 PC z-scores driving the strategy")
fig_z = go.Figure()
for i, pc in enumerate(z_df.columns):
    s = z_df[pc].dropna()
    fig_z.add_trace(go.Scatter(x=s.index, y=s.values, name=pc,
                                line=dict(color=colors_pc[i % 3], width=1.5)))
fig_z.add_hline(y=+z_entry, line_dash="dash", line_color="#f87171",
                 annotation_text=f"+{z_entry}")
fig_z.add_hline(y=-z_entry, line_dash="dash", line_color="#4ade80",
                 annotation_text=f"−{z_entry}")
fig_z.add_hline(y=0, line_color="#94a8c9", line_width=1)
fig_z.update_layout(template=PLOTLY_THEME, height=340, hovermode="x unified",
                     yaxis_title="z-score",
                     margin=dict(l=10, r=10, t=10, b=10),
                     legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="right", x=1))
st.plotly_chart(fig_z, use_container_width=True)

st.divider()
st.caption(
    "**Convention.** Position +1 = long PC = mean-reversion back to zero. PnL = "
    "position × next-day PC change. Strategy is in-sample (PCA fit on full history) "
    "— treat results as illustrative, not deployable as-is. Walk-forward would "
    "be the next refinement."
)
