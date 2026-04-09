"""Page 5 — Correlation Matrix (levels and changes)."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from analysis.regression import change_correlation_matrix, correlation_matrix
from config import PLOTLY_THEME, TENOR_LABELS
from dashboard.components.controls import render_sidebar_controls
from dashboard.state import get_master_df, init_session_state

st.set_page_config(page_title="Correlation", page_icon="🔗", layout="wide")
init_session_state()
render_sidebar_controls()

st.title("🔗 Correlation Matrix")
st.markdown(
    "Cross-asset correlation heatmap for rates, spreads, and macro variables. "
    "Prefer **changes** over levels to avoid spurious correlations in non-stationary data."
)
st.divider()

df = get_master_df()
if df.empty:
    st.error("No data available. Please refresh.")
    st.stop()

# Add spreads
if "10Y" in df.columns and "2Y" in df.columns:
    df["2s10s"] = df["10Y"] - df["2Y"]
if "30Y" in df.columns and "5Y" in df.columns:
    df["5s30s"] = df["30Y"] - df["5Y"]

# ── Column selector ────────────────────────────────────────────────────────
all_numeric = list(df.select_dtypes("number").columns)

# Sensible defaults
default_cols = (
    [c for c in ["1Y", "2Y", "5Y", "10Y", "30Y"] if c in all_numeric]
    + [c for c in ["SOFR_10Y", "2s10s", "5s30s"] if c in all_numeric]
    + [c for c in ["IG_OAS", "HY_OAS", "VIX"] if c in all_numeric]
)

selected_cols = st.multiselect(
    "Select series for correlation matrix",
    options=all_numeric,
    default=default_cols[:12],
)

if len(selected_cols) < 2:
    st.info("Select at least 2 series to compute correlations.")
    st.stop()

col1, col2, col3 = st.columns(3)
with col1:
    use_changes = st.radio("Data transformation", ["Changes (Δ)", "Levels"], index=0)
with col2:
    method = st.radio("Correlation method", ["pearson", "spearman"], index=0)
with col3:
    periods = st.select_slider("Change periods", options=[1, 5, 21], value=1,
                               format_func=lambda d: {1: "Daily", 5: "Weekly", 21: "Monthly"}[d])

sub = df[selected_cols]
if use_changes == "Changes (Δ)":
    corr = change_correlation_matrix(sub, periods=periods, method=method)
    title_suffix = f"({method.capitalize()} on {periods}d changes)"
else:
    corr = correlation_matrix(sub, method=method)
    title_suffix = f"({method.capitalize()} on levels)"

# ── Heatmap ────────────────────────────────────────────────────────────────
st.subheader(f"🔥 Correlation Heatmap {title_suffix}")

annotations = corr.round(2).values.astype(str)

fig = go.Figure(go.Heatmap(
    z=corr.values,
    x=corr.columns.tolist(),
    y=corr.index.tolist(),
    colorscale="RdBu",
    zmid=0,
    zmin=-1, zmax=1,
    text=annotations,
    texttemplate="%{text}",
    textfont=dict(size=10),
    colorbar=dict(title="Correlation"),
))

fig.update_layout(
    template=PLOTLY_THEME,
    height=max(400, 60 * len(selected_cols)),
    margin=dict(l=20, r=20, t=20, b=20),
)
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ── Top correlations table ─────────────────────────────────────────────────
st.subheader("📋 Top Correlations")

corr_pairs = (
    corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    .stack()
    .reset_index()
)
corr_pairs.columns = ["Series A", "Series B", "Correlation"]
corr_pairs["Abs Corr"] = corr_pairs["Correlation"].abs()
corr_pairs = corr_pairs.sort_values("Abs Corr", ascending=False).drop(columns="Abs Corr")

col_top, col_bot = st.columns(2)
with col_top:
    st.markdown("**Most Correlated (positive)**")
    top_pos = corr_pairs[corr_pairs["Correlation"] > 0].head(10)
    st.dataframe(top_pos.style.format({"Correlation": "{:.4f}"}), use_container_width=True)

with col_bot:
    st.markdown("**Most Negatively Correlated**")
    top_neg = corr_pairs[corr_pairs["Correlation"] < 0].head(10)
    st.dataframe(top_neg.style.format({"Correlation": "{:.4f}"}), use_container_width=True)
