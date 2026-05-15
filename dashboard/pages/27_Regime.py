"""Page 27 — Rates Regime Detector.

K-means clusters every historic day into one of four regimes based on:
  • level     (10Y nominal)
  • slope     (2s10s in bps)
  • curvature (5Y - 0.5*(2Y+10Y) — belly cheapness)
  • vol       (VIX z-score as a stand-in for rates-vol regime)

Renders a regime timeline + the current regime's label + within-regime
1Y Z-scores for the scanner's top trades — so you can see which trades
look cheap/rich CONDITIONAL on this regime, not against all-history.
"""

from __future__ import annotations  # PEP 604 unions on Python 3.9

import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    SKLEARN_OK = True
except ImportError:
    SKLEARN_OK = False

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import get_master_df, init_session_state, password_gate

st.set_page_config(page_title="Regime", page_icon="🧭", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Regime")

from dashboard.components.premium_gate import premium_gate
if not premium_gate("Regime"):
    st.stop()

st.title("🧭 Rates Regime Detector")
st.caption(
    "Daily clustering of curve state + vol into 4 regimes, with the current "
    "regime highlighted and scanner Z-scores recomputed conditional on it."
)
st.divider()

if not SKLEARN_OK:
    st.error("scikit-learn isn't installed in this environment. "
             "`pip install scikit-learn` to enable the regime detector.")
    st.stop()

df = get_master_df()
if df.empty:
    st.error("No master data — refresh the cache.")
    st.stop()

# ── Build feature matrix ──────────────────────────────────────────────────
needed = ["2Y", "5Y", "10Y"]
if any(c not in df.columns for c in needed):
    st.warning(f"Need {needed} in cache — missing some.")
    st.stop()

feat = pd.DataFrame(index=df.index)
feat["level"]     = df["10Y"]
feat["slope"]     = (df["10Y"] - df["2Y"]) * 100   # bps
# 5Y-bullet curvature (positive = belly cheap)
feat["curvature"] = (2 * df["5Y"] - df["2Y"] - df["10Y"]) * 100
if "VIX" in df.columns:
    vix = df["VIX"].dropna()
    if not vix.empty:
        # Use VIX z-score as vol regime proxy (rolling 252d)
        roll_mean = vix.rolling(252, min_periods=60).mean()
        roll_std  = vix.rolling(252, min_periods=60).std().replace(0, np.nan)
        feat["vol"] = ((vix - roll_mean) / roll_std).reindex(feat.index).ffill(limit=5)
    else:
        feat["vol"] = 0.0
else:
    feat["vol"] = 0.0

feat = feat.dropna()
if len(feat) < 60:
    st.warning("Not enough overlapping data to cluster — need 60+ days.")
    st.stop()

# ── Cluster ───────────────────────────────────────────────────────────────
n_clusters = st.slider("Number of regimes", 3, 5, 4, key="regime_k")

scaler = StandardScaler()
X      = scaler.fit_transform(feat.values)
km     = KMeans(n_clusters=n_clusters, n_init=10, random_state=42).fit(X)
labels = pd.Series(km.labels_, index=feat.index, name="cluster")

# Auto-label clusters by examining centroids in original space
centroids = pd.DataFrame(scaler.inverse_transform(km.cluster_centers_),
                         columns=feat.columns)

def _name_cluster(row):
    """Give each centroid a human-friendly label."""
    parts = []
    # Vol regime
    if "vol" in row.index:
        if row["vol"] > 0.7:    parts.append("High-vol")
        elif row["vol"] < -0.5: parts.append("Low-vol")
    # Curve shape
    if   row["slope"] < -10:  parts.append("inverted")
    elif row["slope"] > 100:  parts.append("steep")
    else:                     parts.append("mid-slope")
    # Belly tilt
    if   row["curvature"] >  20: parts.append("belly cheap")
    elif row["curvature"] < -20: parts.append("belly rich")
    return ", ".join(parts) if parts else "Mixed"

centroids["label"] = centroids.apply(_name_cluster, axis=1)


# ── Return-driver classification per regime ──────────────────────────────
# For each regime, compute Sharpe of two archetype trades:
#   • CARRY archetype     = receive 5Y outright (level / carry / roll)
#   • CONVEXITY archetype = receive 2Y/5Y/10Y belly fly (curvature / vol pickup)
# Combine with realised |daily Δ10Y| to pick a driver label.
def _regime_driver(regime_idx: int) -> dict:
    regime_dates = labels[labels == regime_idx].index
    out = {"driver": "—", "carry_sharpe": 0.0, "conv_sharpe": 0.0,
           "mean_abs_dy_bps": 0.0}
    if "5Y" not in df.columns: return out

    # Carry archetype — receive 5Y outright, daily PnL = -d(yield) * 100 (bps)
    carry_pnl = (-df["5Y"].diff() * 100).reindex(regime_dates).dropna()
    if len(carry_pnl) > 10 and carry_pnl.std() > 0:
        out["carry_sharpe"] = float(carry_pnl.mean() / carry_pnl.std() * np.sqrt(252))

    # Convexity archetype — receive 2Y/5Y/10Y belly fly
    if all(c in df.columns for c in ("2Y", "5Y", "10Y")):
        fly = 2 * df["5Y"] - df["2Y"] - df["10Y"]
        conv_pnl = (-fly.diff() * 100).reindex(regime_dates).dropna()
        if len(conv_pnl) > 10 and conv_pnl.std() > 0:
            out["conv_sharpe"] = float(conv_pnl.mean() / conv_pnl.std() * np.sqrt(252))

    # Realised vol of 10Y (mean abs daily change in bps)
    if "10Y" in df.columns:
        dy = df["10Y"].diff().reindex(regime_dates).dropna() * 100
        out["mean_abs_dy_bps"] = float(dy.abs().mean()) if len(dy) > 0 else 0.0

    # Classification rule:
    #   High realised vol (>= 5 bps/day mean abs) AND convexity Sharpe meaningful → Vol/convexity
    #   Otherwise look at which archetype Sharpe dominates
    abs_carry = abs(out["carry_sharpe"])
    abs_conv  = abs(out["conv_sharpe"])
    vol       = out["mean_abs_dy_bps"]

    if vol >= 5.0 and abs_conv >= 0.5:
        out["driver"] = "Vol / convexity"
    elif vol >= 5.0:
        out["driver"] = "Vol / directional"   # high vol but flies didn't pay
    elif abs_carry > abs_conv * 1.3:
        out["driver"] = "Carry / level"
    elif abs_conv > abs_carry * 1.3:
        out["driver"] = "Carry / curvature"
    else:
        out["driver"] = "Mixed (carry ≈ convexity)"
    return out


driver_info = {i: _regime_driver(i) for i in range(n_clusters)}
centroids["driver"]          = [driver_info[i]["driver"] for i in range(n_clusters)]
centroids["carry_sharpe"]    = [driver_info[i]["carry_sharpe"] for i in range(n_clusters)]
centroids["conv_sharpe"]     = [driver_info[i]["conv_sharpe"]  for i in range(n_clusters)]
centroids["mean_abs_dy_bps"] = [driver_info[i]["mean_abs_dy_bps"] for i in range(n_clusters)]


# ── Current regime ────────────────────────────────────────────────────────
current_cluster = int(labels.iloc[-1])
current_label   = centroids.loc[current_cluster, "label"]
current_centroid = centroids.iloc[current_cluster]
current_driver   = driver_info[current_cluster]

st.subheader(f"📍 Current regime — cluster {current_cluster}: **{current_label}**")

# Top metric strip
m1, m2, m3, m4 = st.columns(4)
m1.metric("10Y level",   f"{feat['level'].iloc[-1]:.2f}%",
          f"{feat['level'].iloc[-1] - current_centroid['level']:+.2f} vs centroid")
m2.metric("2s10s slope", f"{feat['slope'].iloc[-1]:+.0f} bps",
          f"{feat['slope'].iloc[-1] - current_centroid['slope']:+.0f} vs centroid")
m3.metric("Curvature",   f"{feat['curvature'].iloc[-1]:+.0f} bps",
          f"{feat['curvature'].iloc[-1] - current_centroid['curvature']:+.0f} vs centroid")
m4.metric("Vol z-score", f"{feat['vol'].iloc[-1]:+.2f}",
          f"{feat['vol'].iloc[-1] - current_centroid['vol']:+.2f} vs centroid")

# Driver callout — what's the dominant return source
driver_color = {
    "Vol / convexity":  "#a78bfa",
    "Vol / directional": "#f472b6",
    "Carry / level":    "#4ade80",
    "Carry / curvature":"#fbbf24",
    "Mixed (carry ≈ convexity)": "#94a8c9",
}.get(current_driver["driver"], "#94a8c9")

st.markdown(
    f"""
    <div style='background:#122340;border-left:4px solid {driver_color};
                padding:14px 18px;border-radius:6px;margin:12px 0 0'>
      <div style='color:#94a8c9;font-size:11px;letter-spacing:1.5px;
                  font-weight:700'>RETURN DRIVER</div>
      <div style='color:{driver_color};font-size:22px;font-weight:700;margin:4px 0'>
          {current_driver["driver"]}
      </div>
      <div style='color:#cbd5e1;font-size:13px;line-height:1.55'>
          Realised |Δ10Y|: <b>{current_driver["mean_abs_dy_bps"]:.1f} bps/day</b>
          &nbsp;·&nbsp;
          Carry-archetype Sharpe (Rcv 5Y): <b>{current_driver["carry_sharpe"]:+.2f}</b>
          &nbsp;·&nbsp;
          Convexity-archetype Sharpe (Rcv 2Y/5Y/10Y fly): <b>{current_driver["conv_sharpe"]:+.2f}</b>
      </div>
      <div style='color:#6a7e9e;font-size:11px;margin-top:6px'>
          {"Trade convexity here — flies and wings should outperform outrights." if "Vol / convexity" in current_driver["driver"]
           else "Vol but flies aren't paying — pick directional outrights with conviction." if "Vol / directional" in current_driver["driver"]
           else "Carry trade environment — receive level/curve, fade fly noise." if "Carry / level" in current_driver["driver"]
           else "Curvature carry — belly flies are quietly grinding while outrights are flat." if "Carry / curvature" in current_driver["driver"]
           else "No clear edge between carry and convexity — size down."}
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()

# ── Regime timeline ───────────────────────────────────────────────────────
st.subheader("📅 Regime timeline")
palette = ["#4fc3f7", "#a78bfa", "#fb923c", "#4ade80", "#f472b6"]

# Map each fine-grained driver to a 3-bucket super-group + chart colour
DRIVER_GROUP_COLOR = {
    "Carry":     ("rgba(74,222,128,0.10)",  "#4ade80"),   # green
    "Convexity": ("rgba(167,139,250,0.12)", "#a78bfa"),   # purple
    "Mixed":     ("rgba(148,168,201,0.08)", "#94a8c9"),   # grey
}

def _driver_group(driver_str: str) -> str:
    if driver_str.startswith("Vol"):   return "Convexity"
    if driver_str.startswith("Carry"): return "Carry"
    return "Mixed"

# Per-day driver group, using regime → driver lookup
day_driver = pd.Series(
    [_driver_group(driver_info[int(c)]["driver"]) for c in labels.values],
    index=labels.index,
    name="driver_group",
)

# Build contiguous (start, end, group) bands for vrect colouring
bands: list[tuple] = []
if len(day_driver) > 0:
    cur_group = day_driver.iloc[0]
    cur_start = day_driver.index[0]
    for i in range(1, len(day_driver)):
        if day_driver.iloc[i] != cur_group:
            bands.append((cur_start, day_driver.index[i - 1], cur_group))
            cur_group = day_driver.iloc[i]
            cur_start = day_driver.index[i]
    bands.append((cur_start, day_driver.index[-1], cur_group))

fig = make_subplots(
    rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04,
    row_heights=[0.50, 0.30, 0.20],
    subplot_titles=("10Y nominal — coloured by regime · background shaded by return driver",
                    "2s10s slope (bps)",
                    "Return driver per day"),
)

# Background bands — apply to ALL rows so the colour shows through
for start, end, grp in bands:
    fillcolor, _ = DRIVER_GROUP_COLOR[grp]
    fig.add_vrect(
        x0=start, x1=end, fillcolor=fillcolor, line_width=0,
        layer="below", row="all", col=1,
    )

# Plot 10Y level segmented by REGIME (row 1)
for c in range(n_clusters):
    mask = labels == c
    sub  = feat["level"][mask]
    fig.add_trace(go.Scatter(x=sub.index, y=sub.values,
                             mode="markers", marker=dict(size=4, color=palette[c]),
                             name=f"R{c}: {centroids.loc[c, 'label']}",
                             showlegend=True),
                  row=1, col=1)

# 2s10s slope line (row 2)
fig.add_trace(go.Scatter(x=feat.index, y=feat["slope"],
                         line=dict(color="#94a8c9", width=1.5),
                         showlegend=False, name="2s10s"),
              row=2, col=1)
fig.add_hline(y=0, line_dash="dot", line_color="#6a7e9e", row=2, col=1)

# Driver track (row 3) — solid line at +1/+0/-1 depending on driver group
group_y = {"Carry": 1, "Mixed": 0, "Convexity": -1}
for grp_name, (fillcolor, line_color) in DRIVER_GROUP_COLOR.items():
    mask = day_driver == grp_name
    sub_idx = day_driver.index[mask]
    if len(sub_idx) == 0: continue
    fig.add_trace(go.Scatter(
        x=sub_idx, y=[group_y[grp_name]] * len(sub_idx),
        mode="markers",
        marker=dict(size=8, color=line_color, symbol="square"),
        name=f"{grp_name}-driven",
        legendgroup="driver", showlegend=True,
    ), row=3, col=1)

# Force the driver row's y-axis to show all 3 categories
fig.update_yaxes(
    tickvals=[1, 0, -1],
    ticktext=["Carry", "Mixed", "Convexity"],
    range=[-1.5, 1.5],
    row=3, col=1,
)

fig.update_layout(template=PLOTLY_THEME, height=700,
                  margin=dict(l=10, r=10, t=50, b=10),
                  hovermode="x unified",
                  legend=dict(orientation="h", yanchor="bottom", y=1.06,
                              xanchor="right", x=1, font=dict(size=10)))
st.plotly_chart(fig, use_container_width=True)
st.caption(
    "**Background colour** — green when the dominant return driver in that regime "
    "was carry, purple when it was vol/convexity. The bottom **driver track** "
    "shows the per-day classification. Look for the moments the background changes "
    "colour — those are regime shifts that should change which structures you put on."
)

# ── Cluster cheat sheet ───────────────────────────────────────────────────
st.subheader("🧬 Cluster centroids — including return driver")
disp = centroids.copy()
disp["days_in_regime"]  = [int((labels == i).sum()) for i in range(n_clusters)]
disp["pct_of_history"]  = (disp["days_in_regime"] / len(labels) * 100).round(1)
disp["last_seen"]       = [labels[labels == i].index.max().date() if (labels == i).any() else None
                           for i in range(n_clusters)]

# Re-order columns to put driver + Sharpes adjacent to label
ordered = ["label", "driver", "mean_abs_dy_bps",
           "carry_sharpe", "conv_sharpe",
           "level", "slope", "curvature", "vol",
           "days_in_regime", "pct_of_history", "last_seen"]
disp = disp[[c for c in ordered if c in disp.columns]]

st.dataframe(
    disp.round(2),
    use_container_width=True,
    column_config={
        "label":           st.column_config.TextColumn("Centroid label", width="medium"),
        "driver":          st.column_config.TextColumn("Return driver", width="medium"),
        "mean_abs_dy_bps": st.column_config.NumberColumn("|Δ10Y| bps/day", format="%.1f"),
        "carry_sharpe":    st.column_config.NumberColumn("Carry Sharpe (Rcv 5Y)", format="%+.2f"),
        "conv_sharpe":     st.column_config.NumberColumn("Convexity Sharpe (Fly)", format="%+.2f"),
    },
)
st.caption(
    "**Return driver** is auto-derived per regime: realised |Δ10Y| ≥ 5 bps/day → "
    "vol regime (favours convexity / flies); otherwise carry dominates and we "
    "look at whether outrights (level) or flies (curvature) had better Sharpe. "
    "Carry-archetype = receive 5Y; convexity-archetype = receive 2Y/5Y/10Y belly fly."
)

st.divider()


# ── Empirical transition matrix ──────────────────────────────────────────
# Treat the K-means cluster sequence as a Markov chain and read off the
# 1-day transition probabilities from history. Not the same as a true
# Markov-switching state-space fit (which would estimate transitions
# jointly with regime means), but it's a real lookup at the data and
# gives the user "how persistent is this regime?" + "where would I go
# next if it ended?"
st.subheader("🔁 Regime transitions — empirical Markov chain")
st.caption(
    "1-day transition probabilities estimated by counting historical "
    "regime → regime moves. Diagonal = persistence (P stay one more day). "
    "Off-diagonal = where regimes tend to flip to."
)

# Count regime → next-regime occurrences
trans_counts = np.zeros((n_clusters, n_clusters), dtype=float)
for i in range(len(labels) - 1):
    src = int(labels.iloc[i])
    dst = int(labels.iloc[i + 1])
    trans_counts[src, dst] += 1
row_totals = trans_counts.sum(axis=1, keepdims=True)
trans_probs = np.where(row_totals > 0, trans_counts / row_totals, 0.0)

# Expected duration in each regime: if P(stay) = p, expected duration
# (in days) of a regime spell starting fresh = 1 / (1 - p)
expected_duration_days = np.where(
    trans_probs.diagonal() < 1.0,
    1.0 / (1.0 - trans_probs.diagonal()),
    float("inf"),
)

# Probability of *still being* in regime X after N days, starting from X:
# P_stay(N) = p^N
P_STAY_HORIZONS = [5, 21, 63]   # 1w, 1m, 3m

trans_rows = []
for c in range(n_clusters):
    row = {"Regime": f"R{c}: {centroids.loc[c, 'label']}"}
    row["Persistence (1d)"] = f"{trans_probs[c, c]:.3f}"
    row["Expected dur. (days)"] = (f"{expected_duration_days[c]:.0f}"
                                    if np.isfinite(expected_duration_days[c])
                                    else "∞")
    for h in P_STAY_HORIZONS:
        row[f"Still in @{h}d"] = f"{trans_probs[c, c]**h:.1%}"
    trans_rows.append(row)

st.dataframe(pd.DataFrame(trans_rows), use_container_width=True, hide_index=True)

# Transition heatmap
trans_fig = go.Figure(data=go.Heatmap(
    z=trans_probs,
    x=[f"R{c}" for c in range(n_clusters)],
    y=[f"R{c}: {centroids.loc[c, 'label'][:25]}" for c in range(n_clusters)],
    colorscale=[[0.0, "#0a1628"], [0.3, "#122340"], [0.6, "#1a3056"],
                 [0.85, "#4fc3f7"], [1.0, "#81d4fa"]],
    zmin=0, zmax=1,
    text=[[f"{p*100:.0f}%" for p in row] for row in trans_probs],
    texttemplate="%{text}", textfont={"color": "white", "size": 11},
    colorbar=dict(title="P(next)"),
    hovertemplate="From: %{y}<br>To: %{x}<br>P: %{z:.3f}<extra></extra>",
))
trans_fig.add_vline(x=current_cluster, line_color="#fbbf24", line_width=2,
                      annotation_text="Current", annotation_position="top",
                      annotation_font_color="#fbbf24")
trans_fig.update_layout(
    template=PLOTLY_THEME,
    height=300 + 40 * n_clusters,
    margin=dict(l=10, r=10, t=40, b=10),
    yaxis=dict(autorange="reversed"),
    xaxis=dict(title="To"),
)
st.plotly_chart(trans_fig, use_container_width=True)

# Current-regime forward-looking summary
current_persist = trans_probs[current_cluster, current_cluster]
current_destinations = sorted(
    [(j, trans_probs[current_cluster, j]) for j in range(n_clusters) if j != current_cluster],
    key=lambda x: -x[1],
)
top_dest, top_p = current_destinations[0] if current_destinations else (None, 0.0)

st.markdown(
    f"""
    <div style='background:#122340;border-left:4px solid #fbbf24;
                padding:14px 18px;border-radius:6px;margin:6px 0 0'>
      <div style='color:#94a8c9;font-size:11px;letter-spacing:1.5px;
                  font-weight:700'>FORWARD-LOOKING (FROM CURRENT REGIME)</div>
      <div style='color:#cbd5e1;font-size:13px;line-height:1.6;margin-top:6px'>
        • <b>P(stay tomorrow)</b>: {current_persist:.1%}  →
        <b>P(still here in 1m)</b>: {current_persist**21:.1%}  ·
        <b>3m</b>: {current_persist**63:.1%}<br>
        • <b>Most likely next regime if it flips</b>:
        {("R" + str(top_dest) + ": " + centroids.loc[top_dest, "label"]) if top_dest is not None else "—"}
        ({top_p:.1%} of off-diagonal flips)<br>
        • <b>Expected duration of this regime</b>:
        {(f"{expected_duration_days[current_cluster]:.0f} days") if np.isfinite(expected_duration_days[current_cluster]) else "≥ 1 year"}
      </div>
      <div style='color:#6a7e9e;font-size:11px;margin-top:8px;line-height:1.5'>
        These are empirical frequencies from the cluster sequence — they
        assume tomorrow's regime depends only on today's (Markov property).
        Real regime transitions cluster around macro inflection points
        (Fed pivots, CPI surprises) which the model can't see.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()

# ── Within-regime conditional Z-scores ────────────────────────────────────
st.subheader("📐 Within-regime Z-scores")
st.caption(
    "For the current regime only: which curves/flies are cheapest vs their "
    "history WITHIN this regime (not all-history). A trade can be 'unconditionally "
    "fair' but 'conditionally cheap' — that's the alpha you want to find."
)

regime_dates = labels[labels == current_cluster].index
ALL = ["2Y","3Y","5Y","7Y","10Y","20Y","30Y"]
present = [t for t in ALL if t in df.columns]

rows = []
for i in range(len(present)):
    for j in range(i + 1, len(present)):
        t1, t2 = present[i], present[j]
        spread = (df[t2] - df[t1]).dropna() * 100  # bps
        in_reg = spread.reindex(regime_dates).dropna()
        all_h  = spread.tail(252).dropna()
        if len(in_reg) < 20 or len(all_h) < 60: continue
        z_in   = (spread.iloc[-1] - in_reg.mean()) / in_reg.std() if in_reg.std() > 0 else 0
        z_all  = (spread.iloc[-1] - all_h.mean()) / all_h.std() if all_h.std() > 0 else 0
        rows.append({
            "Spread":      f"{t1}/{t2}",
            "Current bps": round(spread.iloc[-1], 1),
            "Z (1Y all)":  round(z_all, 2),
            "Z (in regime)": round(z_in, 2),
            "Cheap-by-regime": round(z_in - z_all, 2),  # negative = more cheap conditionally
            "Days in regime": len(in_reg),
        })
res = pd.DataFrame(rows).sort_values("Z (in regime)")
st.dataframe(res, use_container_width=True, hide_index=True)
st.caption(
    "**Cheap-by-regime** column: negative means *more dislocated within this "
    "regime than against full history* — those are the conditional opportunities."
)

st.divider()

# ── Regime-conditional expected-PnL & Sharpe ─────────────────────────────
st.subheader("📊 Expected PnL & Sharpe — by regime")
st.caption(
    "For each structure, daily PnL is computed assuming you held it on every "
    "day the regime was active, then annualised. Sharpe is signed — **positive "
    "= receive was the winning side, negative = pay was the winning side**. "
    "Magnitudes mean the same as on the Backtester page."
)

# Build a curated trade universe (simple spreads, non-DV01-weighted because we
# only need a stable signal — full DV01 sizing lives in the Backtester / Builder).
def _level_series(df, struct, tenors):
    if struct == "Outright":
        return df[tenors[0]].dropna()
    if struct == "Curve":
        t1, t2 = tenors
        return (df[t2] - df[t1]).dropna()
    # Fly: 2*belly - wing1 - wing2 (simple, equal-weight)
    w1, b, w2 = tenors
    return (2 * df[b] - df[w1] - df[w2]).dropna()


def _stats(level: pd.Series, regime_dates: pd.DatetimeIndex) -> dict | None:
    pnl_recv = -level.diff().dropna() * 100   # bps, receive PnL
    pnl_in   = pnl_recv.reindex(regime_dates).dropna()
    if len(pnl_in) < 20:
        return None
    mean_bps_d = float(pnl_in.mean())
    std_bps_d  = float(pnl_in.std())
    if std_bps_d == 0:
        return None
    cum = pnl_in.cumsum()
    drawdown = float((cum - cum.cummax()).min())  # most negative
    return {
        "days":       int(len(pnl_in)),
        "ann_bps":    round(mean_bps_d * 252, 0),       # bps/yr (signed)
        "vol_bps":    round(std_bps_d * np.sqrt(252), 0),
        "sharpe":     round(mean_bps_d / std_bps_d * np.sqrt(252), 2),
        "hit_rate":   round(float((pnl_in > 0).mean()) * 100, 0),
        "max_dd_bps": round(drawdown, 0),
    }


TRADE_UNIVERSE = [
    # Outrights
    *[("Outright", [t]) for t in present],
    # Curves
    ("Curve", ["2Y", "5Y"]),  ("Curve", ["2Y", "10Y"]), ("Curve", ["2Y", "30Y"]),
    ("Curve", ["5Y", "10Y"]), ("Curve", ["5Y", "30Y"]), ("Curve", ["10Y", "30Y"]),
    # Flies
    ("Fly", ["2Y", "5Y", "10Y"]),  ("Fly", ["2Y", "5Y", "30Y"]),
    ("Fly", ["2Y", "10Y", "30Y"]), ("Fly", ["5Y", "10Y", "30Y"]),
    ("Fly", ["3Y", "5Y", "7Y"]),   ("Fly", ["5Y", "7Y", "10Y"]),
]

# Filter universe to trades with all tenors in cache
universe = [
    (struct, tt) for struct, tt in TRADE_UNIVERSE
    if all(t in df.columns for t in tt)
]


def _trade_label(struct, tenors):
    if struct == "Outright": return tenors[0]
    if struct == "Curve":    return f"{tenors[0]}/{tenors[1]} curve"
    return f"{tenors[0]}{tenors[1]}{tenors[2]} fly"


# Compute stats for every (trade, regime) pair
matrix = []     # list of dicts for the dataframe
heat_z  = []    # rows = trades, cols = regimes; value = Sharpe
trade_labels = []
for struct, tt in universe:
    lvl = _level_series(df, struct, tt)
    label = _trade_label(struct, tt)
    trade_labels.append(label)
    row_sharpes = []
    for c in range(n_clusters):
        regime_dates = labels[labels == c].index
        s = _stats(lvl, regime_dates)
        sharpe = s["sharpe"] if s else np.nan
        row_sharpes.append(sharpe)
        if c == current_cluster and s is not None:
            matrix.append({
                "Trade":          label,
                "Type":           struct,
                "Direction":      "Receive" if s["sharpe"] > 0 else "Pay",
                "Sharpe":         abs(s["sharpe"]),
                "Sharpe (signed)": s["sharpe"],
                "Ann PnL (bps)":  s["ann_bps"] if s["sharpe"] > 0 else -s["ann_bps"],
                "Vol (bps)":      s["vol_bps"],
                "Hit rate %":     s["hit_rate"] if s["sharpe"] > 0 else 100 - s["hit_rate"],
                "Max DD (bps)":   s["max_dd_bps"],
                "Days":           s["days"],
            })
    heat_z.append(row_sharpes)

# ── 1. Top trades in current regime ──────────────────────────────────────
if matrix:
    st.markdown(
        f"**🎯 Top trades in current regime — {current_label}**  "
        f"<span style='color:#94a8c9'>(N = {(labels == current_cluster).sum()} days)</span>",
        unsafe_allow_html=True,
    )
    mdf = pd.DataFrame(matrix).sort_values("Sharpe", ascending=False)
    st.dataframe(
        mdf.head(15)[["Trade", "Type", "Direction", "Sharpe (signed)",
                       "Ann PnL (bps)", "Vol (bps)", "Hit rate %",
                       "Max DD (bps)", "Days"]],
        use_container_width=True, hide_index=True,
        column_config={
            "Sharpe (signed)": st.column_config.NumberColumn(format="%+.2f"),
            "Ann PnL (bps)":   st.column_config.NumberColumn(format="%+.0f"),
            "Max DD (bps)":    st.column_config.NumberColumn(format="%.0f"),
        },
    )
else:
    st.info("Not enough days in the current regime to compute conditional stats.")


# ── 2. Sharpe heatmap (trade × regime) ───────────────────────────────────
st.markdown("**🔥 Sharpe heatmap — trade × regime**")
st.caption(
    "Green cells = receive worked in this regime, red = pay worked. "
    "Magnitude = annualised Sharpe of the winning direction. "
    "Look for trades that are reliably profitable in the current regime "
    "(highlighted column header) but break down in others — those are your "
    "regime-specific edges."
)

regime_labels_pretty = [f"R{c}\n{centroids.loc[c,'label']}" for c in range(n_clusters)]
heat_z_arr = np.array(heat_z)
hm = go.Figure(data=go.Heatmap(
    z=heat_z_arr,
    x=regime_labels_pretty,
    y=trade_labels,
    colorscale=[
        [0.0, "#7f1d1d"], [0.25, "#431407"], [0.45, "#0a1628"],
        [0.55, "#0a1628"], [0.75, "#14532d"], [1.0, "#166534"],
    ],
    zmid=0,
    zmin=-2.5, zmax=2.5,
    colorbar=dict(title="Sharpe"),
    hovertemplate="Trade: %{y}<br>Regime: %{x}<br>Sharpe: %{z:+.2f}<extra></extra>",
))
# Highlight current regime column with a vertical line
hm.add_vline(x=current_cluster, line_color="#fbbf24", line_width=2,
              annotation_text="Current", annotation_position="top",
              annotation_font_color="#fbbf24")
hm.update_layout(template=PLOTLY_THEME,
                  height=max(420, 22 * len(trade_labels)),
                  margin=dict(l=10, r=10, t=40, b=10),
                  yaxis=dict(autorange="reversed"))
st.plotly_chart(hm, use_container_width=True)

# ── 3. Best 3 trades in current regime — signal cards ────────────────────
if matrix:
    st.markdown("**⚡ Quick pick — top 3 in current regime**")
    from dashboard.components.signal_card import (
        render_signal_grid, render_units_legend,
    )
    top3 = sorted(matrix, key=lambda r: -r["Sharpe"])[:3]
    # Resolve each row back to a structure type for the card
    # (matrix entries from the conditional Sharpe section already include
    # Direction, Sharpe (signed), Ann PnL (bps), Hit rate %, Days, Vol)
    cards = []
    for t in top3:
        # Find the trade's type from the universe so the badge is accurate
        t_type = t.get("Type", "Outright")
        # Find Z from the within-regime z-score table if available
        z_val = 0.0
        for r in rows if "rows" in dir() else []:
            if isinstance(r, dict) and r.get("Spread", "").replace("/", "") in t["Trade"].replace("/", ""):
                z_val = float(str(r.get("Z (in regime)", "0")).replace("+", ""))
                break
        cards.append(dict(
            trade=t["Trade"],
            type_=t_type,
            sharpe=float(t["Sharpe (signed)"]),
            z=z_val,
            expected_return_bps_yr=float(t["Ann PnL (bps)"]),
            risk_bps_yr=float(t["Vol (bps)"]),
            hit_rate_pct=float(t["Hit rate %"]),
            max_dd_bps=float(t.get("Max DD (bps)", 0)),
            days=int(t["Days"]),
            direction=t["Direction"].lower(),
        ))
    render_signal_grid(cards, n_cols=3, compact=True)

    with st.expander("Units key"):
        render_units_legend()
