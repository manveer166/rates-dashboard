"""Page 2 — Yield Curve Spreads and Swap Spreads."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from analysis.spreads import compute_spreads, spread_summary
from config import PLOTLY_THEME, SPREAD_DEFINITIONS
from dashboard.components.controls import render_sidebar_controls
from dashboard.state import get_master_df, init_session_state

st.set_page_config(page_title="Spreads", page_icon="📊", layout="wide")
init_session_state()
render_sidebar_controls()

st.title("📊 Spread Analysis")
st.markdown("2s10s, 5s30s, swap spreads, and credit spreads with z-score overlays.")
st.divider()

df      = get_master_df()
if df.empty:
    st.error("No data available. Please refresh.")
    st.stop()

spreads = compute_spreads(df)

if spreads.empty:
    st.warning("No spreads could be computed — some tenor data may be missing.")
    st.stop()

# ── Summary table ──────────────────────────────────────────────────────────
st.subheader("📋 Spread Summary")
summary = spread_summary(spreads)
st.dataframe(
    summary.style.format("{:.3f}", na_rep="—"),
    use_container_width=True,
)

st.divider()

# ── Main spread chart ──────────────────────────────────────────────────────
st.subheader("📉 Spread History")

spread_choice = st.multiselect(
    "Select spreads to plot",
    options=list(spreads.columns),
    default=["2s10s", "5s30s"] if all(s in spreads.columns for s in ["2s10s", "5s30s"]) else list(spreads.columns)[:2],
)

if spread_choice:
    fig = go.Figure()
    colors = px.colors.qualitative.Plotly

    for i, spread in enumerate(spread_choice):
        s = spreads[spread].dropna()
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values,
            mode="lines",
            name=spread,
            line=dict(color=colors[i % len(colors)], width=1.8),
        ))
        # Zero line
    fig.add_hline(y=0, line_dash="dot", line_color="white", opacity=0.4)

    fig.update_layout(
        template=PLOTLY_THEME,
        hovermode="x unified",
        xaxis_title="Date",
        yaxis_title="Spread (percentage points)",
        height=380,
        margin=dict(l=20, r=20, t=10, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ── Z-Score chart ──────────────────────────────────────────────────────────
st.subheader("📐 Rolling Z-Score (1Y window)")

from analysis.spreads import compute_zscore

if spread_choice:
    fig_z = go.Figure()
    for i, spread in enumerate(spread_choice):
        s = spreads[spread].dropna()
        if len(s) >= 252:
            z = compute_zscore(s, window=252).dropna()
            fig_z.add_trace(go.Scatter(
                x=z.index, y=z.values,
                mode="lines",
                name=f"{spread} Z",
                line=dict(color=colors[i % len(colors)], width=1.8),
            ))

    fig_z.add_hline(y=2,  line_dash="dash", line_color="red",   opacity=0.6, annotation_text="+2σ")
    fig_z.add_hline(y=-2, line_dash="dash", line_color="green", opacity=0.6, annotation_text="-2σ")
    fig_z.add_hline(y=0,  line_dash="dot",  line_color="white", opacity=0.3)

    fig_z.update_layout(
        template=PLOTLY_THEME,
        hovermode="x unified",
        xaxis_title="Date",
        yaxis_title="Z-Score",
        height=320,
        margin=dict(l=20, r=20, t=10, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig_z, use_container_width=True)

st.divider()

# ── Credit spreads ──────────────────────────────────────────────────────────
from config import CORP_SPREAD_SERIES

st.subheader("💳 Credit Spreads (ICE BofA OAS)")

credit_cols = [c for c in CORP_SPREAD_SERIES.keys() if c in df.columns]
if credit_cols:
    credit_choice = st.multiselect(
        "Select credit spread series",
        options=credit_cols,
        default=["IG_OAS", "HY_OAS", "BBB_OAS"] if all(c in credit_cols for c in ["IG_OAS", "HY_OAS", "BBB_OAS"]) else credit_cols[:3],
    )

    if credit_choice:
        fig_c = go.Figure()
        for i, col in enumerate(credit_choice):
            s = df[col].dropna()
            fig_c.add_trace(go.Scatter(
                x=s.index, y=s.values,
                mode="lines",
                name=col.replace("_OAS", " OAS"),
                line=dict(color=colors[i % len(colors)], width=1.8),
            ))
        fig_c.update_layout(
            template=PLOTLY_THEME,
            hovermode="x unified",
            xaxis_title="Date",
            yaxis_title="OAS (basis points)",
            height=360,
            margin=dict(l=20, r=20, t=10, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_c, use_container_width=True)
else:
    st.info("Credit spread data not available. Add a FRED API key to .env for best results.")

# ── Tutorial overlay (must be LAST) ────────────────────────────────────
from dashboard.tutorial import render_tutorial
render_tutorial(page="spreads")
