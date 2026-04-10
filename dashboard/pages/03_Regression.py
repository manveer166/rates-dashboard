"""Page 3 — OLS Regression and Rolling Beta Analysis."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from analysis.regression import run_ols, run_rolling_regression
from config import PLOTLY_THEME, TENOR_LABELS, CORP_SPREAD_SERIES, MACRO_SERIES
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import get_master_df, init_session_state

st.set_page_config(page_title="Regression", page_icon="🔬", layout="wide")
init_session_state()
render_sidebar_controls()
render_page_header(current="Regression")

st.title("🔬 Regression Analysis")
st.markdown("OLS and rolling regression between rates, spreads, and macro variables.")
st.divider()

df = get_master_df()
if df.empty:
    st.error("No data available. Please refresh.")
    st.stop()

# Add derived columns
if "10Y" in df.columns and "2Y" in df.columns:
    df["2s10s"] = df["10Y"] - df["2Y"]
if "30Y" in df.columns and "5Y" in df.columns:
    df["5s30s"] = df["30Y"] - df["5Y"]

# Columns available for regression
numeric_cols = [c for c in df.select_dtypes("number").columns]

# ── OLS Setup ──────────────────────────────────────────────────────────────
st.subheader("📐 OLS Regression")

col1, col2 = st.columns(2)
with col1:
    y_col = st.selectbox(
        "Dependent variable (Y)",
        options=numeric_cols,
        index=numeric_cols.index("10Y") if "10Y" in numeric_cols else 0,
    )
with col2:
    x_cols = st.multiselect(
        "Independent variable(s) (X)",
        options=[c for c in numeric_cols if c != y_col],
        default=["2Y"] if "2Y" in numeric_cols else numeric_cols[:1],
    )

use_changes = st.checkbox(
    "Use first differences (changes) instead of levels",
    value=True,
    help="Recommended for non-stationary rate series to avoid spurious regression.",
)
add_const = st.checkbox("Include constant (intercept)", value=True)

if x_cols and st.button("▶️ Run OLS", type="primary"):
    y_series = df[y_col].diff() if use_changes else df[y_col]
    X_frame  = df[x_cols].diff() if use_changes else df[x_cols]
    y_series.name = f"Δ{y_col}" if use_changes else y_col

    result = run_ols(y_series, X_frame, add_const=add_const)

    if result:
        # KPIs
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("R²",      f"{result['r2']:.4f}")
        c2.metric("Adj. R²", f"{result['adj_r2']:.4f}")
        c3.metric("N obs.",  f"{result['nobs']:,}")
        c4.metric("AIC",     f"{result['aic']:.1f}")

        # Coefficients table
        st.subheader("📊 Coefficients")
        import pandas as pd
        coef_df = pd.DataFrame({
            "Coefficient": result["params"].round(6),
            "P-Value":     result["pvalues"].round(4),
            "Sig.":        result["pvalues"].apply(
                lambda p: "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else ""))
            ),
            "95% CI Low":  result["conf_int"].iloc[:, 0].round(6),
            "95% CI High": result["conf_int"].iloc[:, 1].round(6),
        })
        st.dataframe(coef_df.style.format({
            "Coefficient": "{:.6f}",
            "P-Value":     "{:.4f}",
            "95% CI Low":  "{:.6f}",
            "95% CI High": "{:.6f}",
        }), use_container_width=True)

        # Actual vs Fitted
        st.subheader("📈 Actual vs Fitted")
        fig_avf = go.Figure()
        fig_avf.add_trace(go.Scatter(
            x=result["fitted"].index, y=result["fitted"].values,
            mode="lines", name="Fitted",
            line=dict(color="#FFD93D", width=1.5),
        ))
        y_clean = y_series.loc[result["fitted"].index]
        fig_avf.add_trace(go.Scatter(
            x=y_clean.index, y=y_clean.values,
            mode="lines", name="Actual",
            line=dict(color="#00D4FF", width=1),
            opacity=0.7,
        ))
        fig_avf.update_layout(
            template=PLOTLY_THEME, hovermode="x unified",
            height=300, margin=dict(l=20, r=20, t=10, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_avf, use_container_width=True)

        # Residuals
        st.subheader("📉 Residuals")
        fig_res = go.Figure()
        fig_res.add_trace(go.Scatter(
            x=result["residuals"].index, y=result["residuals"].values,
            mode="lines", name="Residuals",
            line=dict(color="#FF6B6B", width=1),
        ))
        fig_res.add_hline(y=0, line_dash="dot", line_color="white", opacity=0.4)
        fig_res.update_layout(
            template=PLOTLY_THEME, hovermode="x unified",
            height=250, margin=dict(l=20, r=20, t=10, b=20),
        )
        st.plotly_chart(fig_res, use_container_width=True)

        # Full statsmodels summary
        with st.expander("📄 Full Statsmodels Summary"):
            components.html(result["summary_html"], height=450, scrolling=True)
    else:
        st.error("Regression failed. Check that your selected series have sufficient overlapping data.")

st.divider()

# ── Rolling Regression ─────────────────────────────────────────────────────
st.subheader("🔄 Rolling Regression (Single X)")

col1, col2, col3 = st.columns(3)
with col1:
    roll_y = st.selectbox("Y variable", options=numeric_cols,
                          index=numeric_cols.index("10Y") if "10Y" in numeric_cols else 0,
                          key="roll_y")
with col2:
    roll_x = st.selectbox("X variable", options=[c for c in numeric_cols if c != roll_y],
                          index=0, key="roll_x")
with col3:
    window = st.select_slider(
        "Window (trading days)",
        options=[21, 42, 63, 126, 252],
        value=63,
        format_func=lambda d: {21: "1M", 42: "2M", 63: "3M", 126: "6M", 252: "1Y"}[d],
    )

roll_changes = st.checkbox("Use changes for rolling regression", value=True, key="roll_changes")

if st.button("▶️ Run Rolling Regression", type="primary"):
    y_s = df[roll_y].diff().dropna() if roll_changes else df[roll_y]
    x_s = df[roll_x].diff().dropna() if roll_changes else df[roll_x]
    y_s.name = roll_y
    x_s.name = roll_x

    rr = run_rolling_regression(y_s, x_s, window=window)

    if not rr.empty:
        fig_rr = go.Figure()
        fig_rr.add_trace(go.Scatter(
            x=rr.index, y=rr["beta"],
            mode="lines",
            name=f"Rolling Beta ({roll_x} → {roll_y})",
            line=dict(color="#FFD93D", width=2),
        ))
        fig_rr.add_hline(y=0, line_dash="dot", line_color="white", opacity=0.4)
        fig_rr.add_hline(y=rr["beta"].mean(), line_dash="dash", line_color="#00D4FF",
                         opacity=0.6, annotation_text="Mean Beta")
        fig_rr.update_layout(
            template=PLOTLY_THEME, hovermode="x unified",
            xaxis_title="Date", yaxis_title="Beta",
            height=350, margin=dict(l=20, r=20, t=10, b=20),
        )
        st.plotly_chart(fig_rr, use_container_width=True)

        fig_alpha = go.Figure()
        fig_alpha.add_trace(go.Scatter(
            x=rr.index, y=rr["alpha"],
            mode="lines", name="Rolling Alpha",
            line=dict(color="#6BCB77", width=1.5),
        ))
        fig_alpha.add_hline(y=0, line_dash="dot", line_color="white", opacity=0.4)
        fig_alpha.update_layout(
            template=PLOTLY_THEME, hovermode="x unified",
            xaxis_title="Date", yaxis_title="Alpha",
            height=250, margin=dict(l=20, r=20, t=10, b=20),
        )
        st.plotly_chart(fig_alpha, use_container_width=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("Current Beta",  f"{rr['beta'].iloc[-1]:.4f}")
        c2.metric("Mean Beta",     f"{rr['beta'].mean():.4f}")
        c3.metric("Beta Std Dev",  f"{rr['beta'].std():.4f}")
    else:
        st.warning("Not enough data for rolling regression with the selected window.")

# ── Tutorial overlay (must be LAST) ────────────────────────────────────
from dashboard.tutorial import render_tutorial
render_tutorial(page="regression")
