"""
14_Vol_Surface.py — Swaption implied volatility surface visualisation.

Builds a synthetic vol surface from realised vols when no market data is available,
or loads actual swaption vol data from CSV/API if configured.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import PLOTLY_THEME
from dashboard.state import password_gate, get_master_df, init_session_state
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header

st.set_page_config(page_title="Vol Surface", page_icon="🌊", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Vol Surface")

st.title("🌊 Volatility Surface (Realised Vol Proxy)")
st.caption("Synthetic surface built from realised vols at different rolling windows. Not market-implied — connect live swaption data for true implied vol.")

# ── Load vol data (or build synthetic) ────────────────────────────────────

@st.cache_resource
def _load_fi():
    import fixed_income as fi
    return fi

fi = _load_fi()
df = get_master_df()

ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
EXPIRIES = ["1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y"]
EXPIRY_DAYS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252, "2Y": 504, "5Y": 1260, "10Y": 2520}

avail = [t for t in ALL_TENORS if t in df.columns]
rdf = df[avail].ffill(limit=3).dropna(how="all")

st.divider()

# ── Controls ──────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns(3)
with c1:
    vol_type = st.selectbox("Volatility Type", ["Normal (bps)", "Lognormal (%)"], key="vol_type_sel")
with c2:
    surface_style = st.selectbox("Surface Style", ["3D Surface", "Heatmap", "Term Structure"], key="surf_style")
with c3:
    rv_window = st.selectbox("Realised Vol Base Window", [21, 42, 63, 126], index=2,
                              format_func=lambda x: f"{x}d", key="rv_base")

st.divider()

# ── Build realised vol surface ────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner="Building vol surface...")
def build_vol_surface(_rdf_hash, avail_tenors, rv_base, vol_is_normal):
    """Build a synthetic vol surface from realised vols at different windows.
    Rows = expiry (option maturity), Cols = underlying swap tenor."""
    surface = np.full((len(EXPIRIES), len(avail_tenors)), np.nan)

    for j, tenor in enumerate(avail_tenors):
        s = rdf[tenor].dropna()
        if len(s) < 60:
            continue
        daily_chg = s.diff().dropna() * 100  # bps

        for i, expiry in enumerate(EXPIRIES):
            window = EXPIRY_DAYS.get(expiry, rv_base)
            window = min(window, len(daily_chg))
            if window < 15:
                continue

            rv = float(daily_chg.tail(window).std() * np.sqrt(252))

            if not vol_is_normal:
                # Convert to lognormal: log_vol ≈ normal_vol / rate_level
                rate = float(s.iloc[-1])
                if rate > 0:
                    rv = rv / (rate * 100) * 100  # percent

            # Apply a simple term structure adjustment:
            # shorter expiries have slightly higher vol (mean reversion),
            # longer expiries slightly lower
            expiry_years = EXPIRY_DAYS[expiry] / 252
            term_adj = 1.0 + 0.05 * (1.0 - expiry_years) if expiry_years < 1 else \
                       1.0 - 0.02 * np.log(expiry_years)
            surface[i, j] = rv * max(0.7, term_adj)

    return surface


is_normal = vol_type.startswith("Normal")
rdf_hash = hash(rdf.index[-1].isoformat() + str(len(rdf)))
surface = build_vol_surface(rdf_hash, avail, rv_window, is_normal)

vol_unit = "bps/yr" if is_normal else "%"

# ── Create surface DataFrame ──────────────────────────────────────────────
surf_df = pd.DataFrame(surface, index=EXPIRIES, columns=avail)
surf_df.index.name = "Expiry"

# ── Visualisation ─────────────────────────────────────────────────────────

if surface_style == "3D Surface":
    fig = go.Figure(data=[go.Surface(
        z=surface,
        x=list(range(len(avail))),
        y=list(range(len(EXPIRIES))),
        colorscale="Viridis",
        colorbar=dict(title=vol_unit),
        hovertemplate=(
            "Tenor: %{customdata[0]}<br>"
            "Expiry: %{customdata[1]}<br>"
            "Vol: %{z:.1f} " + vol_unit +
            "<extra></extra>"
        ),
        customdata=[[(avail[j], EXPIRIES[i]) for j in range(len(avail))] for i in range(len(EXPIRIES))],
    )])
    fig.update_layout(
        template=PLOTLY_THEME,
        title=f"Swaption Vol Surface ({vol_type})",
        scene=dict(
            xaxis=dict(title="Swap Tenor", ticktext=avail, tickvals=list(range(len(avail)))),
            yaxis=dict(title="Expiry", ticktext=EXPIRIES, tickvals=list(range(len(EXPIRIES)))),
            zaxis=dict(title=f"Vol ({vol_unit})"),
            camera=dict(eye=dict(x=1.5, y=-1.5, z=0.8)),
        ),
        height=600,
        margin=dict(l=0, r=0, t=50, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

elif surface_style == "Heatmap":
    fig = go.Figure(data=go.Heatmap(
        z=surface,
        x=avail,
        y=EXPIRIES,
        colorscale="Viridis",
        colorbar=dict(title=vol_unit),
        hovertemplate="Tenor: %{x}<br>Expiry: %{y}<br>Vol: %{z:.1f} " + vol_unit + "<extra></extra>",
    ))
    fig.update_layout(
        template=PLOTLY_THEME,
        title=f"Swaption Vol Heatmap ({vol_type})",
        xaxis_title="Swap Tenor",
        yaxis_title="Option Expiry",
        height=500,
        margin=dict(l=60, r=20, t=50, b=50),
    )
    st.plotly_chart(fig, use_container_width=True)

elif surface_style == "Term Structure":
    # Plot vol term structure for each tenor
    fig = go.Figure()
    colors = ["#4fc3f7", "#ff8a65", "#66bb6a", "#ab47bc", "#ffca28", "#ef5350", "#26a69a"]
    for j, tenor in enumerate(avail):
        vols = surface[:, j]
        fig.add_trace(go.Scatter(
            x=EXPIRIES,
            y=vols,
            mode="lines+markers",
            name=tenor,
            line=dict(color=colors[j % len(colors)], width=2),
            marker=dict(size=6),
        ))
    fig.update_layout(
        template=PLOTLY_THEME,
        title=f"Vol Term Structure by Tenor ({vol_type})",
        xaxis_title="Expiry",
        yaxis_title=f"Vol ({vol_unit})",
        height=500,
        showlegend=True,
        legend=dict(orientation="h", y=1.1),
        margin=dict(l=50, r=20, t=60, b=50),
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Data table ────────────────────────────────────────────────────────────
with st.expander("Vol Surface Data"):
    fmt_df = surf_df.style.format("{:.1f}", na_rep="—").background_gradient(cmap="YlOrRd", axis=None)
    st.dataframe(fmt_df, use_container_width=True)

st.divider()

# ── Smile / Skew section ─────────────────────────────────────────────────
st.subheader("Volatility Smile (SABR Estimate)")
st.caption("Estimated normal vol smile using SABR-like parameterisation.")

smile_cols = st.columns(3)
with smile_cols[0]:
    smile_tenor = st.selectbox("Underlying Tenor", avail,
                                index=avail.index("10Y") if "10Y" in avail else 0, key="smile_t")
with smile_cols[1]:
    smile_expiry = st.selectbox("Expiry", EXPIRIES, index=3, key="smile_e")
with smile_cols[2]:
    sabr_rho = st.slider("Rho (skew)", -0.8, 0.2, -0.3, 0.05, key="sabr_rho")

# Get ATM vol
exp_idx = EXPIRIES.index(smile_expiry)
ten_idx = avail.index(smile_tenor)
atm_vol = surface[exp_idx, ten_idx] if not np.isnan(surface[exp_idx, ten_idx]) else 60.0

# Build a simple SABR-like smile
strikes_offset = np.arange(-200, 205, 5)  # bps from ATM
alpha = atm_vol
nu = 0.4  # vol of vol
beta = 0.5

# Simplified SABR normal vol smile approximation
smile_vols = []
for dk in strikes_offset:
    dk_dec = dk / 10000.0
    # Hagan SABR approximation (simplified for normal model)
    skew_adj = 1.0 + sabr_rho * nu * dk_dec / alpha * 10000
    convex_adj = 1.0 + (2 - 3 * sabr_rho**2) / 24 * nu**2 * (EXPIRY_DAYS[smile_expiry] / 252)
    vol = atm_vol * skew_adj * convex_adj
    smile_vols.append(max(vol, 5.0))

fig_smile = go.Figure()
fig_smile.add_trace(go.Scatter(
    x=strikes_offset,
    y=smile_vols,
    mode="lines",
    line=dict(color="#4fc3f7", width=2.5),
    name="SABR Smile",
    fill="tozeroy",
    fillcolor="rgba(79,195,247,0.08)",
))
fig_smile.add_vline(x=0, line_dash="dot", line_color="white", opacity=0.5)
fig_smile.update_layout(
    template=PLOTLY_THEME,
    title=f"{smile_expiry}x{smile_tenor} Normal Vol Smile",
    xaxis_title="Strike Offset from ATM (bps)",
    yaxis_title=f"Normal Vol ({vol_unit})",
    height=400,
    margin=dict(l=50, r=20, t=50, b=50),
)
st.plotly_chart(fig_smile, use_container_width=True)

st.divider()
st.caption("Volatility surface built from realised vols. Connect live swaption data for market-implied surface.")

# ── Tutorial overlay (must be LAST) ────────────────────────────────────
from dashboard.tutorial import render_tutorial
render_tutorial(page="vol_surface")
