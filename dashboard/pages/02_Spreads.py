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
from dashboard.components.header import render_page_header
from dashboard.state import get_master_df, init_session_state

st.set_page_config(page_title="Spreads", page_icon="📊", layout="wide")
init_session_state()
render_sidebar_controls()
render_page_header(current="Spreads")

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

# ── Funding & Plumbing ────────────────────────────────────────────────
st.divider()
st.subheader("🏦 Funding & Plumbing")
st.caption("Repo rates, SOFR-EFFR spread, MOVE index, and ON RRP usage. Key stress indicators for the rates market.")

import numpy as np

funding_cols = {
    "SOFR": "SOFR (O/N)",
    "EFFR": "EFFR",
    "TGCR": "Tri-Party GC Rate",
    "BGCR": "Broad GC Rate",
}
avail_funding = {k: v for k, v in funding_cols.items() if k in df.columns}

# SOFR-EFFR spread (primary funding stress indicator)
if "SOFR" in df.columns and "EFFR" in df.columns:
    sofr_effr = (df["SOFR"] - df["EFFR"]).dropna()
    if len(sofr_effr) > 10:
        fc1, fc2, fc3, fc4 = st.columns(4)
        latest_sofr_effr = sofr_effr.iloc[-1]
        fc1.metric("SOFR-EFFR Spread",
                   f"{latest_sofr_effr*100:+.1f} bps",
                   help="Positive = SOFR above EFFR, signals repo stress")
        if "SOFR" in df.columns:
            fc2.metric("SOFR", f"{df['SOFR'].dropna().iloc[-1]:.2f}%")
        if "EFFR" in df.columns:
            fc3.metric("EFFR", f"{df['EFFR'].dropna().iloc[-1]:.2f}%")
        if "MOVE" in df.columns:
            move_s = df["MOVE"].dropna()
            if len(move_s) > 1:
                fc4.metric("MOVE Index",
                           f"{move_s.iloc[-1]:.0f}",
                           delta=f"{move_s.iloc[-1] - move_s.iloc[-2]:+.1f}",
                           delta_color="inverse")

        # SOFR-EFFR spread chart
        fig_se = go.Figure()
        fig_se.add_trace(go.Scatter(
            x=sofr_effr.index, y=sofr_effr.values * 100,
            mode="lines", name="SOFR - EFFR (bps)",
            line=dict(color="#4fc3f7", width=1.5),
            fill="tozeroy", fillcolor="rgba(79,195,247,0.08)",
        ))
        fig_se.add_hline(y=0, line_dash="dot", line_color="white", opacity=0.3)
        fig_se.update_layout(
            template=PLOTLY_THEME, height=280,
            hovermode="x unified",
            xaxis_title="Date", yaxis_title="SOFR - EFFR (bps)",
            margin=dict(l=20, r=20, t=10, b=20),
        )
        st.plotly_chart(fig_se, use_container_width=True)

# MOVE Index chart
if "MOVE" in df.columns:
    move_s = df["MOVE"].dropna()
    if len(move_s) > 20:
        st.markdown("**MOVE Index** — ICE BofA rates implied vol benchmark")
        fig_mv = go.Figure()
        fig_mv.add_trace(go.Scatter(
            x=move_s.index, y=move_s.values,
            mode="lines", name="MOVE",
            line=dict(color="#fbbf24", width=1.5),
        ))
        # Add 1Y rolling average
        if len(move_s) > 252:
            ma = move_s.rolling(252).mean().dropna()
            fig_mv.add_trace(go.Scatter(
                x=ma.index, y=ma.values,
                mode="lines", name="1Y Avg",
                line=dict(color="#94a8c9", width=1, dash="dash"),
            ))
        fig_mv.update_layout(
            template=PLOTLY_THEME, height=280,
            hovermode="x unified",
            xaxis_title="Date", yaxis_title="MOVE Index",
            margin=dict(l=20, r=20, t=10, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_mv, use_container_width=True)

# ON RRP usage
if "ON_RRP" in df.columns:
    rrp_s = df["ON_RRP"].dropna()
    if len(rrp_s) > 20:
        st.markdown("**ON RRP Usage** — Fed overnight reverse repo facility ($bn)")
        fig_rrp = go.Figure()
        fig_rrp.add_trace(go.Scatter(
            x=rrp_s.index, y=rrp_s.values / 1e3,
            mode="lines", name="ON RRP ($tn)",
            line=dict(color="#4ade80", width=1.5),
            fill="tozeroy", fillcolor="rgba(74,222,128,0.08)",
        ))
        fig_rrp.update_layout(
            template=PLOTLY_THEME, height=280,
            hovermode="x unified",
            xaxis_title="Date", yaxis_title="ON RRP ($tn)",
            margin=dict(l=20, r=20, t=10, b=20),
        )
        st.plotly_chart(fig_rrp, use_container_width=True)

# Repo rate panel (TGCR / BGCR if available from NY Fed)
repo_avail = [c for c in ["TGCR", "BGCR"] if c in df.columns]
if repo_avail:
    st.markdown("**Repo Rates** — Tri-Party GC Rate / Broad GC Rate")
    fig_repo = go.Figure()
    repo_colors = {"TGCR": "#81d4fa", "BGCR": "#ce93d8"}
    for col in repo_avail:
        s = df[col].dropna()
        fig_repo.add_trace(go.Scatter(
            x=s.index, y=s.values,
            mode="lines", name=col,
            line=dict(color=repo_colors.get(col, "#4fc3f7"), width=1.5),
        ))
    if "SOFR" in df.columns:
        sofr_s = df["SOFR"].dropna()
        fig_repo.add_trace(go.Scatter(
            x=sofr_s.index, y=sofr_s.values,
            mode="lines", name="SOFR",
            line=dict(color="#fbbf24", width=1, dash="dot"),
        ))
    fig_repo.update_layout(
        template=PLOTLY_THEME, height=280,
        hovermode="x unified",
        xaxis_title="Date", yaxis_title="Rate (%)",
        margin=dict(l=20, r=20, t=10, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig_repo, use_container_width=True)

# COT Positioning (if available from CFTC fetcher)
cot_cols = [c for c in df.columns if c.startswith("COT_") and "NET_LEV" in c]
if cot_cols:
    st.divider()
    st.subheader("📊 Futures Positioning (CFTC COT)")
    st.caption("Net speculative (leveraged money) positioning in Treasury and SOFR futures. Weekly data, forward-filled.")

    fig_cot = go.Figure()
    cot_colors = ["#4fc3f7", "#81d4fa", "#ce93d8", "#f48fb1", "#fbbf24"]
    for i, col in enumerate(sorted(cot_cols)):
        s = df[col].dropna()
        if len(s) > 2:
            label = col.replace("COT_", "").replace("_NET_LEV", "")
            fig_cot.add_trace(go.Bar(
                x=s.index, y=s.values,
                name=label,
                marker_color=cot_colors[i % len(cot_colors)],
                opacity=0.7,
            ))
    fig_cot.add_hline(y=0, line_dash="dot", line_color="white", opacity=0.3)
    fig_cot.update_layout(
        template=PLOTLY_THEME, height=380,
        hovermode="x unified", barmode="group",
        xaxis_title="Date", yaxis_title="Net Contracts (thousands)",
        margin=dict(l=20, r=20, t=10, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig_cot, use_container_width=True)

# ── Tutorial overlay (must be LAST) ────────────────────────────────────
from dashboard.tutorial import render_tutorial
render_tutorial(page="spreads")
