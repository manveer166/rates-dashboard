"""Page 1 — Yield Curve Snapshot + Nelson-Siegel Fit."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from analysis.nelson_siegel import fit_curve, fit_history
from config import TENOR_LABELS, TENOR_YEARS, PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.state import get_master_df, init_session_state

st.set_page_config(page_title="Yield Curve", page_icon="📉", layout="wide")
init_session_state()
render_sidebar_controls()

st.title("📉 Yield Curve Analysis")
st.markdown("US Treasury yield curve snapshot, historical evolution, and Nelson-Siegel model fit.")
st.divider()

df = get_master_df()
if df.empty:
    st.error("No data available. Please refresh.")
    st.stop()

avail = [t for t in TENOR_LABELS if t in df.columns]
avail_years = [TENOR_YEARS[TENOR_LABELS.index(t)] for t in avail]

# ── Date selector for curve snapshot ──────────────────────────────────────
dates_available = df.index.strftime("%Y-%m-%d").tolist()
selected_date = st.selectbox(
    "Select curve date",
    options=dates_available,
    index=len(dates_available) - 1,
)
selected_ts = st.session_state.get("curve_compare_date", dates_available[max(0, len(dates_available)-252)])
compare_date = st.selectbox(
    "Compare with",
    options=["None"] + dates_available,
    index=max(0, len(dates_available)-252),
)

# ── Nelson-Siegel fit ──────────────────────────────────────────────────────
row        = df.loc[selected_date, avail]
fit_result = fit_curve(row)

# ── Snapshot chart ─────────────────────────────────────────────────────────
fig = go.Figure()

fig.add_trace(go.Scatter(
    x=avail, y=row.values,
    mode="lines+markers",
    name=f"Actual ({selected_date})",
    line=dict(color="#00D4FF", width=2.5),
    marker=dict(size=9),
))

if fit_result["success"]:
    fig.add_trace(go.Scatter(
        x=fit_result["tau_dense"], y=fit_result["fitted_dense"],
        mode="lines",
        name="Nelson-Siegel Fit",
        line=dict(color="#FFD93D", width=2, dash="dash"),
    ))

if compare_date != "None":
    row_cmp = df.loc[compare_date, avail]
    fig.add_trace(go.Scatter(
        x=avail, y=row_cmp.values,
        mode="lines+markers",
        name=f"Compare ({compare_date})",
        line=dict(color="#FF6B6B", width=2),
        marker=dict(size=7),
    ))

fig.update_layout(
    template=PLOTLY_THEME,
    hovermode="x unified",
    xaxis_title="Tenor",
    yaxis_title="Yield (%)",
    height=420,
    margin=dict(l=20, r=20, t=10, b=20),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)
st.plotly_chart(fig, use_container_width=True)

# ── NS parameters ─────────────────────────────────────────────────────────
if fit_result["success"]:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("β₀ (Level)",     f"{fit_result['beta0']:.3f}%",
              help="Long-run yield level")
    c2.metric("β₁ (Slope)",     f"{fit_result['beta1']:.3f}%",
              help="Short-term factor (negative = upward sloping)")
    c3.metric("β₂ (Curvature)", f"{fit_result['beta2']:.3f}%",
              help="Medium-term hump")
    c4.metric("λ (Decay)",      f"{fit_result['lambda']:.3f}",
              help="Controls where the hump peaks")
    st.caption(f"RMSE: {fit_result['rmse']:.4f}%")

st.divider()

# ── 3D Yield Curve Surface ─────────────────────────────────────────────────
st.subheader("🗺️ Yield Curve Surface — Historical 3D View")
freq = st.select_slider("Resample frequency", ["W", "2W", "ME"], value="2W")

sub_df = df[avail].resample(freq).last().dropna(how="all").tail(104)

if not sub_df.empty:
    z_matrix  = sub_df.values
    dates_list = sub_df.index.strftime("%Y-%m-%d").tolist()

    fig3d = go.Figure(data=[go.Surface(
        z=z_matrix,
        x=avail,
        y=list(range(len(dates_list))),
        colorscale="Viridis",
        showscale=True,
    )])
    fig3d.update_layout(
        template=PLOTLY_THEME,
        scene=dict(
            xaxis_title="Tenor",
            yaxis_title="Time",
            zaxis_title="Yield (%)",
            yaxis=dict(tickvals=list(range(0, len(dates_list), max(1, len(dates_list)//10))),
                       ticktext=dates_list[::max(1, len(dates_list)//10)]),
        ),
        height=500,
        margin=dict(l=0, r=0, t=10, b=0),
    )
    st.plotly_chart(fig3d, use_container_width=True)

st.divider()

# ── Nelson-Siegel factor history ───────────────────────────────────────────
st.subheader("📊 Nelson-Siegel Factor History")

with st.spinner("Fitting Nelson-Siegel to historical data…"):
    ns_history = fit_history(df, freq="W")

if not ns_history.empty:
    fig_ns = go.Figure()
    colors = {"beta0": "#00D4FF", "beta1": "#FF6B6B", "beta2": "#FFD93D"}
    labels = {"beta0": "β₀ Level", "beta1": "β₁ Slope", "beta2": "β₂ Curvature"}
    for col, color in colors.items():
        fig_ns.add_trace(go.Scatter(
            x=ns_history.index, y=ns_history[col],
            mode="lines", name=labels[col],
            line=dict(color=color, width=1.8),
        ))
    fig_ns.update_layout(
        template=PLOTLY_THEME,
        hovermode="x unified",
        xaxis_title="Date",
        yaxis_title="Factor Value (%)",
        height=320,
        margin=dict(l=20, r=20, t=10, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig_ns, use_container_width=True)

# ── Tutorial overlay (must be LAST) ────────────────────────────────────
from dashboard.tutorial import render_tutorial
render_tutorial(page="yield_curve")
