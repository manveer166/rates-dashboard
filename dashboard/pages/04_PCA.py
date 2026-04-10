"""Page 4 — PCA Decomposition of the Yield Curve."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import plotly.graph_objects as go
import plotly.figure_factory as ff
import streamlit as st
import pandas as pd

from analysis.pca import run_pca, pca_summary_table
from config import PLOTLY_THEME, TENOR_LABELS
from dashboard.components.controls import render_sidebar_controls
from dashboard.state import get_master_df, init_session_state

st.set_page_config(page_title="PCA", page_icon="🧮", layout="wide")
init_session_state()
render_sidebar_controls()

st.title("🧮 PCA — Yield Curve Decomposition")
st.markdown(
    "Principal Component Analysis decomposes yield curve moves into:\n"
    "**PC1 (Level)** → parallel shift · **PC2 (Slope)** → steepening/flattening · **PC3 (Curvature)** → butterfly"
)
st.divider()

df = get_master_df()
if df.empty:
    st.error("No data available. Please refresh.")
    st.stop()

n_components = st.slider("Number of components", min_value=2, max_value=5, value=3)

with st.spinner("Running PCA…"):
    pca_result = run_pca(df, n_components=n_components)

if not pca_result:
    st.error("PCA failed — insufficient data or missing tenor columns.")
    st.stop()

# ── Variance explained ─────────────────────────────────────────────────────
st.subheader("📊 Variance Explained")
col1, col2 = st.columns([1, 2])

with col1:
    st.dataframe(pca_summary_table(pca_result), use_container_width=True)

with col2:
    ev = pca_result["explained_variance"]
    pc_names = list(pca_result["scores"].columns)
    fig_var = go.Figure()
    fig_var.add_trace(go.Bar(
        x=pc_names, y=[v * 100 for v in ev],
        name="Explained Variance",
        marker_color="#00D4FF",
    ))
    fig_var.add_trace(go.Scatter(
        x=pc_names, y=[v * 100 for v in pca_result["cumulative_variance"]],
        name="Cumulative",
        mode="lines+markers",
        line=dict(color="#FFD93D", width=2),
        yaxis="y2",
    ))
    fig_var.update_layout(
        template=PLOTLY_THEME,
        xaxis_title="Component",
        yaxis_title="Variance Explained (%)",
        yaxis2=dict(title="Cumulative (%)", overlaying="y", side="right", range=[0, 105]),
        height=280,
        margin=dict(l=20, r=20, t=10, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig_var, use_container_width=True)

st.divider()

# ── Factor loadings heatmap ────────────────────────────────────────────────
st.subheader("🔥 Factor Loadings Heatmap")

loadings = pca_result["loadings"]
fig_heat = go.Figure(go.Heatmap(
    z=loadings.values.T,
    x=loadings.index.tolist(),
    y=loadings.columns.tolist(),
    colorscale="RdBu",
    zmid=0,
    text=loadings.values.T.round(3),
    texttemplate="%{text}",
    textfont=dict(size=11),
))
fig_heat.update_layout(
    template=PLOTLY_THEME,
    xaxis_title="Tenor",
    yaxis_title="Principal Component",
    height=300,
    margin=dict(l=20, r=20, t=10, b=20),
)
st.plotly_chart(fig_heat, use_container_width=True)

st.divider()

# ── Factor scores over time ────────────────────────────────────────────────
st.subheader("📈 Factor Scores Over Time")

scores = pca_result["scores"]
colors = ["#00D4FF", "#FF6B6B", "#FFD93D", "#6BCB77", "#FF9F40"]

fig_scores = go.Figure()
for i, col in enumerate(scores.columns):
    fig_scores.add_trace(go.Scatter(
        x=scores.index, y=scores[col],
        mode="lines",
        name=col,
        line=dict(color=colors[i % len(colors)], width=1.5),
    ))
fig_scores.add_hline(y=0, line_dash="dot", line_color="white", opacity=0.3)
fig_scores.update_layout(
    template=PLOTLY_THEME,
    hovermode="x unified",
    xaxis_title="Date",
    yaxis_title="Factor Score",
    height=380,
    margin=dict(l=20, r=20, t=10, b=20),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)
st.plotly_chart(fig_scores, use_container_width=True)

st.divider()

# ── PC1 vs PC2 scatter ─────────────────────────────────────────────────────
st.subheader("🔵 PC1 vs PC2 Scatter (Level vs Slope)")
if len(scores.columns) >= 2:
    fig_scat = go.Figure(go.Scatter(
        x=scores.iloc[:, 0], y=scores.iloc[:, 1],
        mode="markers",
        marker=dict(
            color=list(range(len(scores))),
            colorscale="Viridis",
            size=4,
            opacity=0.7,
            showscale=True,
            colorbar=dict(title="Time →"),
        ),
        text=scores.index.strftime("%Y-%m-%d"),
        hovertemplate="<b>%{text}</b><br>PC1: %{x:.2f}<br>PC2: %{y:.2f}",
    ))
    fig_scat.update_layout(
        template=PLOTLY_THEME,
        xaxis_title=scores.columns[0],
        yaxis_title=scores.columns[1],
        height=420,
        margin=dict(l=20, r=20, t=10, b=20),
    )
    st.plotly_chart(fig_scat, use_container_width=True)
    st.caption("Colour gradient from dark (oldest) to bright (most recent).")

# ── Tutorial overlay (must be LAST) ────────────────────────────────────
from dashboard.tutorial import render_tutorial
render_tutorial(page="pca")
