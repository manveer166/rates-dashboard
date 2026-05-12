"""
15_CTA_Positioning.py — CTA & Systematic Fund Positioning

Two tabs:
  • 📈 CTA Positioning  — historical, projection scenarios, flows table,
                           systematic positioning, risk parity, sharpe bubble,
                           expected return, top/bottom 3 sharpe
  • ⚙️ Vol Control      — EWMA vol projections + daily/cumulative flows
                           under multiple forward-vol assumptions
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import warnings; warnings.filterwarnings("ignore")
import io
import json
import os
import smtplib
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import reduce

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from analysis.vol_control import (
    MARKETS as VC_MARKETS,
    build_forward_flows,
    build_flows_table,
    ewma_vol_series,
    vol_used_series,
    ewma_variance_series,
    project_ewma_state,
    exposure_series,
    TDPY as VC_TDPY,
    MAX_LEV as VC_MAX_LEV,
)
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import _secret, get_master_df, init_session_state, is_admin, password_gate

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="CTA Positioning · Rates Dashboard",
                   page_icon="📊", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="CTA Positioning")

# ── Model constants ───────────────────────────────────────────────────────────
CTA_TOTAL_BN      = 300     # assumed CTA AUM ($bn) — anchors all flow numbers
CTA_MAX_BN        = 80      # max per-market allocation ($bn)
CTA_LOOKBACKS     = [21, 63, 252]     # short / medium / slow trend windows (days)
CTA_BLEND_WTS     = [0.30, 0.40, 0.30]  # horizon weights (must sum to 1)
CTA_VOL_WIN       = 63      # EWMA span for vol normalisation
CTA_INERTIA_ALPHA = 0.15    # daily position adjustment speed toward target (0=frozen, 1=instant)
CTA_TARGET_VOL    = 0.12    # annualised target vol per position (for leverage scaling)
CTA_MAX_LEVERAGE  = 1.5     # max vol-targeting leverage multiplier
CTA_PROJ_DAYS     = 130
CTA_VOL_WIN_SC    = 21
CTA_SCENARIOS  = {
    "+2 Std Dev":      +2.0,
    "+1 Std Dev":      +1.0,
    "Flat Baseline":    0.0,
    "Down 1 Std Dev":  -1.0,
    "Down >2 Std Dev": -2.5,
}
CTA_COLORS = ["red", "#e57373", "#e8eef9", "#90caf9", "gold"]

MKTS = {
    "S&P 500 E-mini":      ("^GSPC",      0.28),
    "TOPIX":               ("^N225",      0.05),
    "DAX 30":              ("^GDAXI",     0.07),
    "DJ Euro Stoxx 50":    ("^STOXX50E",  0.07),
    "FTSE 100":            ("^FTSE",      0.05),
    "Nasdaq 100 E-mini":   ("^NDX",       0.11),
    "Russell 2000 E-mini": ("^RUT",       0.05),
    "Hang Seng":           ("^HSI",       0.04),
    "SPI 200":             ("^AXJO",      0.04),
    "CAC 40":              ("^FCHI",      0.04),
    "Kospi 200":           ("^KS11",      0.03),
    "AEX":                 ("^AEX",       0.03),
    "MSCIEM (NYL)":        ("EEM",        0.03),
    "IBEX 35":             ("^IBEX",      0.02),
    "S&P/MIB":             ("FTSEMIB.MI", 0.02),
    "SMI":                 ("^SSMI",      0.02),
}

ALERT_CFG_PATH = Path(__file__).parent.parent.parent / "data" / "cta_alert_config.json"
DEFAULT_ALERT_CHARTS = ["expected_sharpe", "expected_return", "top_bottom_sharpe"]
AVAILABLE_CHARTS = {
    "cta_historical":    "CTA Historical Positioning",
    "cta_projection":    "CTA Projection Scenarios",
    "expected_flows":    "Expected Flows Table",
    "systematic_pos":    "Systematic Positioning",
    "rp_bond":           "Risk Parity Bond Exposure",
    "rp_equity":         "Risk Parity Equity Exposure",
    "expected_sharpe":   "Expected Sharpe Bubble ⭐",
    "expected_return":   "Expected Return by Market ⭐",
    "top_bottom_sharpe": "Top / Bottom 3 Sharpe ⭐",
    "vol_daily_flow":    "Vol Control — Daily Flows",
    "vol_cumulative":    "Vol Control — Cumulative",
}

# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADERS
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner="Loading S&P 500 history…")
def _load_sp500():
    d = yf.download("^GSPC", start="2012-01-01", auto_adjust=True, progress=False)
    if d is None or d.empty:
        return pd.Series(dtype=float)
    s = d["Close"].squeeze().dropna()
    s.index = pd.to_datetime(s.index.date)
    return s

@st.cache_data(ttl=3600, show_spinner="Loading market data…")
def _load_markets():
    out = {}
    for name, (ticker, _) in MKTS.items():
        try:
            d = yf.download(ticker, start="2019-01-01", auto_adjust=True, progress=False)
            if d is None or d.empty:
                out[name] = None
                continue
            s = d["Close"].squeeze().dropna()
            s.index = pd.to_datetime(s.index.date)
            out[name] = s if len(s) > 100 else None
        except Exception:
            out[name] = None
    return out

@st.cache_data(ttl=3600, show_spinner="Loading risk parity data…")
def _load_rp():
    eq_d = yf.download("^GSPC", start="2017-01-01", auto_adjust=True, progress=False)
    bd_d = yf.download("TLT",   start="2017-01-01", auto_adjust=True, progress=False)
    if eq_d is None or eq_d.empty:
        eq = pd.Series(dtype=float)
    else:
        eq = eq_d["Close"].squeeze().dropna()
        eq.index = pd.to_datetime(eq.index.date)
    if bd_d is None or bd_d.empty:
        bd = pd.Series(dtype=float)
    else:
        bd = bd_d["Close"].squeeze().dropna()
        bd.index = pd.to_datetime(bd.index.date)
    return eq, bd

@st.cache_data(ttl=3600, show_spinner="Loading CFTC COT data…")
def _load_cot_data() -> "pd.DataFrame":
    """
    Fetch CFTC TFF Leveraged Funds + Asset Manager net positioning directly
    from the Socrata API (no API key required).  Cached for 1 hour.

    Calls CFTCFetcher which handles its own parquet cache in data/cache/.

    Columns returned (weekly cadence, forward-filled to daily):
        COT_{tenor}_NET_LEV  — Leveraged Money net (long − short), contracts
        COT_{tenor}_NET_AM   — Asset Manager net  (long − short), contracts
    where tenor ∈ {2Y, 5Y, 10Y, 30Y}.
    """
    try:
        from data.fetchers.cftc import CFTCFetcher
        from datetime import date
        fetcher = CFTCFetcher(
            start_date="2020-01-01",
            end_date=date.today().isoformat(),
        )
        df = fetcher.fetch()
        if df is None or df.empty:
            return pd.DataFrame()
        # Deduplicate forward-filled rows — keep only actual report dates
        df = df[~df.eq(df.shift(1)).all(axis=1)]
        return df
    except Exception as _e:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner="Loading market data for vol-control…")
def _load_vc_market_prices():
    """
    Fetch all market prices for the vol-control engine.
    Cached separately so the slow fetch doesn't block other tabs.
    Downloads from 2012 for adequate EWMA warm-up.
    """
    from analysis.vol_control import load_market_prices, MARKETS as _VC_MKTS
    return load_market_prices(_VC_MKTS, start="2012-01-01")


@st.cache_data(ttl=3600, show_spinner="Computing vol-control model…")
def _load_vol_control(
    aum: float = 300e9,
    target_vol: float = 0.12,
    lambda_30: float = 0.94,
    lambda_90: float = 0.97,
    forward_vols: tuple = (0.20, 0.18, 0.16, 0.14, 0.12),
    periods_fwd: int = 80,
):
    """
    Institutional vol-control flow model using proper recursive EWMA.

    Replaces the old normalised-window approximation with the correct
    RiskMetrics formulation:  var_t = (1−λ)·r_t² + λ·var_{t-1}

    Forward projection propagates the EWMA *state* — vol converges
    gradually to σ_fwd, NOT an instant jump.

    Returns
    -------
    hist_df   : historical vol/exposure DataFrame (S&P)
    merged    : forward flow projections ($bn) — Daily & Cumulative cols
    flows_tbl : multi-market scenario flows table ($MM)
    """
    mkt_prices = _load_vc_market_prices()
    sp_prices  = mkt_prices.get("S&P 500 E-mini")

    # ── Historical vol diagnostics (S&P proxy) ────────────────────────────
    if sp_prices is None or len(sp_prices) < 252:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    sp_rets   = np.log(sp_prices / sp_prices.shift(1)).dropna()
    v30_hist  = ewma_vol_series(sp_rets, lambda_30)
    v90_hist  = ewma_vol_series(sp_rets, lambda_90)
    vu_hist   = vol_used_series(v30_hist, v90_hist)
    exp_hist  = exposure_series(vu_hist, target_vol)

    hist_df = pd.DataFrame({
        "Date":           sp_rets.index,   # returns index (prices - 1 row)
        "vol_30":         v30_hist.values,
        "vol_90":         v90_hist.values,
        "vol_used":       vu_hist.values,
        "equity_weight":  exp_hist.values,
    }).set_index("Date").dropna().iloc[-504:]  # last 2 years for display

    # ── Forward flow projections (S&P, aggregate AUM) ─────────────────────
    sp_weight = VC_MARKETS.get("S&P 500 E-mini", ("", 0.28))[1]
    merged = build_forward_flows(
        prices      = sp_prices,
        total_aum   = aum,
        mkt_weight  = sp_weight,
        target_vol  = target_vol,
        lambda_30   = lambda_30,
        lambda_90   = lambda_90,
        forward_vols= forward_vols,
        periods_fwd = periods_fwd,
    )

    # ── Multi-market scenario flows table ($MM) ───────────────────────────
    weights = {n: v[1] for n, v in VC_MARKETS.items()}
    flows_tbl = build_flows_table(
        mkt_prices  = mkt_prices,
        mkt_weights = weights,
        total_aum   = aum,
        target_vol  = target_vol,
        lambda_30   = lambda_30,
        lambda_90   = lambda_90,
    )

    return hist_df, merged, flows_tbl

# ══════════════════════════════════════════════════════════════════════════════
# CTA MODEL
# ══════════════════════════════════════════════════════════════════════════════
def _cta_signal(prices: pd.Series) -> pd.Series:
    """
    Institutional-style multi-horizon CTA signal.

    Step 1 — Per-horizon momentum (annualised, vol-normalised):
        mom_h = log(P_t / P_{t-h}) / sqrt(h/252)
        signal_h = tanh( mom_h / (2 * ewma_vol) )   → bounded in [-1, +1]

    Step 2 — Blend three horizons (fast/medium/slow):
        raw = 0.30 * signal_21 + 0.40 * signal_63 + 0.30 * signal_252

    Step 3 — Position inertia (partial adjustment each day):
        pos_t = pos_{t-1} + α * (raw_t - pos_{t-1})
        α = CTA_INERTIA_ALPHA (default 0.15)

    Using EWMA vol (span=63) rather than rolling std gives earlier
    regime-transition detection. Inertia prevents the model from
    flipping positions instantly — real CTAs rebalance gradually.
    """
    lr       = np.log(prices / prices.shift(1))
    ewma_vol = lr.ewm(span=CTA_VOL_WIN).std() * np.sqrt(252)

    raw = pd.Series(0.0, index=prices.index)
    for lb, w in zip(CTA_LOOKBACKS, CTA_BLEND_WTS):
        mom = np.log(prices / prices.shift(lb)) / np.sqrt(lb / 252)
        raw += w * np.tanh(mom / (2 * ewma_vol + 1e-8))

    # Position inertia — slow drift toward target, not instant flip
    smoothed = raw.copy() * np.nan
    prev = 0.0
    for i, v in enumerate(raw.values):
        if np.isnan(v):
            smoothed.iloc[i] = np.nan
        else:
            smoothed.iloc[i] = prev + CTA_INERTIA_ALPHA * (v - prev)
            prev = smoothed.iloc[i]
    return smoothed


def _sig_to_pos(sig: pd.Series, prices: pd.Series = None) -> pd.Series:
    """
    Vol-targeted position sizing.

    Without prices: simple signal × MAX_BN (used in projections where vol
    is already baked into the scenario).

    With prices: vol-targeting scales leverage inversely with realised vol —
    positions shrink when vol spikes, expand when vol is subdued.
        leverage = (target_vol / ewma_vol).clip(max=MAX_LEVERAGE)
        position = signal × leverage × MAX_BN
    """
    if prices is None or len(prices) < CTA_VOL_WIN + 5:
        return (sig * CTA_MAX_BN).clip(-CTA_MAX_BN, CTA_MAX_BN)
    lr       = np.log(prices / prices.shift(1))
    ewma_vol = lr.ewm(span=CTA_VOL_WIN).std() * np.sqrt(252)
    lev      = (CTA_TARGET_VOL / (ewma_vol + 1e-8)).clip(upper=CTA_MAX_LEVERAGE)
    lev      = lev.reindex(sig.index).fillna(1.0)
    max_pos  = CTA_MAX_BN * CTA_MAX_LEVERAGE
    return (sig * lev * CTA_MAX_BN).clip(-max_pos, max_pos)

def _project_price(hist, rets, fwd, z):
    dv   = rets.iloc[-CTA_VOL_WIN_SC:].std()
    vals = hist.iloc[-1] * np.exp(np.cumsum(np.full(fwd, z * dv)))
    idx  = pd.date_range(hist.index[-1] + pd.Timedelta(days=1), periods=fwd, freq="B")
    return pd.Series(vals, index=idx)

def _mkt_flow(p, abn, fwd_days, z, hist_days=None):
    if p is None or len(p) < max(CTA_LOOKBACKS) + CTA_VOL_WIN + 10:
        return np.nan
    rets = np.log(p / p.shift(1)).dropna()
    if hist_days is not None:
        cur = float(_sig_to_pos(_cta_signal(p),           prices=p).iloc[-1])
        old = float(_sig_to_pos(_cta_signal(p.iloc[:-hist_days]), prices=p.iloc[:-hist_days]).iloc[-1])
        return round((cur - old) * 1000)
    cp  = float(_sig_to_pos(_cta_signal(p), prices=p).iloc[-1])
    dv  = rets.iloc[-CTA_VOL_WIN_SC:].std()
    pv  = p.iloc[-1] * np.exp(np.cumsum(np.full(fwd_days, z * dv)))
    pi  = pd.date_range(p.index[-1] + pd.Timedelta(days=1), periods=fwd_days, freq="B")
    ext = pd.concat([p, pd.Series(pv, index=pi)])
    pp  = float(_sig_to_pos(_cta_signal(ext), prices=ext).iloc[-1])
    return round((pp - cp) * 1000)

@st.cache_data(ttl=3600, show_spinner="Computing CTA signals…")
def _compute_cta(sp_data, mkt_prices):
    pos_hist  = _sig_to_pos(_cta_signal(sp_data), prices=sp_data)
    rets      = np.log(sp_data / sp_data.shift(1)).dropna()
    sp_alloc  = MKTS["S&P 500 E-mini"][1]
    sp_hist_w = (pos_hist * sp_alloc).iloc[-126:]

    # Projection scenarios — vol-targeting applied to extended price series
    proj = {}
    for name, z in CTA_SCENARIOS.items():
        ext      = pd.concat([sp_data, _project_price(sp_data, rets, CTA_PROJ_DAYS, z)])
        proj[name] = (_sig_to_pos(_cta_signal(ext), prices=ext) * sp_alloc).iloc[-CTA_PROJ_DAYS:]

    # Flow table
    flow_cols = [
        ("1 Week", "Flat", 0), ("1 Week", "Up 2 STD", 2.0), ("1 Week", "Down 2.5 STD", -2.5),
        ("1 Month", "Flat", 0), ("1 Month", "Up 2 STD", 2.0), ("1 Month", "Down 2.5 STD", -2.5),
        ("Sim. Realized", "Last Week", None), ("Sim. Realized", "Last Month", None),
    ]
    days_m = {"1 Week": 5, "1 Month": 21}
    hist_m = {"Last Week": 5, "Last Month": 21}
    rows = []
    for mkt, (_, w) in MKTS.items():
        p   = mkt_prices.get(mkt); abn = CTA_TOTAL_BN * w; row = {"Market": mkt}
        for period, label, z in flow_cols:
            key = f"{period}|{label}"
            row[key] = (_mkt_flow(p, abn, None, None, hist_days=hist_m[label])
                        if z is None else _mkt_flow(p, abn, days_m[period], z))
        rows.append(row)
    flows_df = pd.DataFrame(rows).set_index("Market")
    tot = flows_df.sum(numeric_only=True); tot.name = "Totals"
    flows_df = pd.concat([flows_df, tot.to_frame().T])

    # Per-market signal stats — use STRATEGY returns (signal × price return)
    # This gives economically meaningful Sharpe / expected return.
    # Raw price returns (old approach) produce 150%+ annualised numbers
    # because they annualise a 1-month window — not what we want.
    sr_rows = []
    for mkt, (_, w) in MKTS.items():
        p = mkt_prices.get(mkt)
        if p is None or len(p) < 300:
            continue
        r         = np.log(p / p.shift(1)).dropna()
        sig_ser   = _cta_signal(p).reindex(r.index).fillna(0)
        # Strategy P&L: yesterday's signal × today's return
        strat_r   = sig_ser.shift(1) * r
        lookback  = min(252, len(strat_r))
        ann_ret   = float(strat_r.iloc[-lookback:].mean() * 252)
        ann_vol   = float(strat_r.iloc[-lookback:].std() * np.sqrt(252))
        sharpe    = ann_ret / (ann_vol + 1e-8)
        sig_now   = float(sig_ser.iloc[-1])
        f1w       = _mkt_flow(p, CTA_TOTAL_BN * w, 5, 0.0)
        sr_rows.append({
            "Market":    mkt,
            "Signal":    sig_now,
            "AnnReturn": ann_ret,
            "AnnVol":    ann_vol,
            "Sharpe":    sharpe,
            "Flow1W":    f1w if (f1w is not None and not np.isnan(f1w)) else 0,
        })
    sr_df = pd.DataFrame(sr_rows)
    mxf   = sr_df["Flow1W"].abs().max()
    sr_df["BubbleSize"] = (sr_df["Flow1W"].abs() / (mxf + 1e-8)) * 50 + 8
    sr_df["Direction"]  = sr_df["Flow1W"].apply(lambda x: "Buying" if x >= 0 else "Selling")

    plot_start = pd.Timestamp("2019-01-01")
    syst       = pos_hist[pos_hist.index >= plot_start]

    return pos_hist, sp_hist_w, proj, flows_df, sr_df, syst

@st.cache_data(ttl=3600, show_spinner="Computing risk parity…")
def _compute_rp(eq_data, bd_data):
    ev  = np.log(eq_data / eq_data.shift(1)).rolling(63).std() * np.sqrt(252)
    bv  = np.log(bd_data / bd_data.shift(1)).rolling(63).std() * np.sqrt(252)
    idx = ev.dropna().index.intersection(bv.dropna().index)
    bond_exp = (0.10 * 2.5 / bv.loc[idx] * 100).clip(40, 170)
    eq_exp   = (0.10 / ev.loc[idx] * 100).clip(6, 60)
    def pr(s): return int(s.rank(pct=True).iloc[-1] * 100)
    cb, ce   = float(bond_exp.iloc[-1]), float(eq_exp.iloc[-1])
    bond_lbl = f"Bnd Exp @ {cb:.0f}% or<br>{pr(bond_exp)}%-tile vs 1Y<br>{pr(bond_exp)}%-tile vs 5Y"
    eq_lbl   = f"Eq Exp @ {ce:.0f}% or<br>{pr(eq_exp)}%-tile vs 1Y<br>{pr(eq_exp)}%-tile vs 5Y"
    return bond_exp, eq_exp, cb, ce, bond_lbl, eq_lbl

# ══════════════════════════════════════════════════════════════════════════════
# COT CHART BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

# Display metadata for each tenor
_COT_TENORS = [
    ("2Y",  "2Y Treasury",  "#4fc3f7"),
    ("5Y",  "5Y Treasury",  "#f59e0b"),
    ("10Y", "10Y Treasury", "#a78bfa"),
    ("30Y", "30Y Bond",     "#f87171"),
]

def _cot_summary(cot_df: "pd.DataFrame") -> "pd.DataFrame":
    """
    Build a per-tenor summary DataFrame with current value, 1W / 1M change,
    and z-scores vs 1Y and 3Y history for both Leveraged Funds and Asset Managers.
    """
    rows = []
    for key, label, _ in _COT_TENORS:
        col_lev = f"COT_{key}_NET_LEV"
        col_am  = f"COT_{key}_NET_AM"
        if col_lev not in cot_df.columns:
            continue
        s = cot_df[col_lev].dropna()
        if len(s) < 4:
            continue

        curr   = float(s.iloc[-1])
        prev1w = float(s.iloc[-2]) if len(s) >= 2 else float("nan")
        prev1m = float(s.iloc[-5]) if len(s) >= 5 else float("nan")

        hist1y = s.tail(52)
        hist3y = s.tail(156)

        z1y = (curr - hist1y.mean()) / (hist1y.std() + 1e-9)
        z3y = (curr - hist3y.mean()) / (hist3y.std() + 1e-9)

        pct1y = int(round((hist1y <= curr).mean() * 100))
        pct3y = int(round((hist3y <= curr).mean() * 100))

        chg1w = curr - prev1w
        chg1m = curr - prev1m

        am_curr = float(cot_df[col_am].dropna().iloc[-1]) if col_am in cot_df.columns else float("nan")

        rows.append({
            "Tenor":   label,
            "Net Lev (K)":  round(curr / 1000, 1),
            "ΔW (K)":       round(chg1w / 1000, 1),
            "Δ4W (K)":      round(chg1m / 1000, 1),
            "Z (1Y)":       round(z1y, 2),
            "Z (3Y)":       round(z3y, 2),
            "Pct 1Y":       pct1y,
            "Pct 3Y":       pct3y,
            "AM Net (K)":   round(am_curr / 1000, 1),
        })
    return pd.DataFrame(rows)


def _chart_cot_history(cot_df: "pd.DataFrame") -> "go.Figure":
    """Multi-line time series of Leveraged Funds net positioning (last 2Y)."""
    margin = dict(l=60, r=20, t=44, b=36)
    fig = go.Figure()
    window = cot_df.tail(104)  # ~2 years of weekly data
    any_data = False
    for key, label, color in _COT_TENORS:
        col = f"COT_{key}_NET_LEV"
        if col not in window.columns:
            continue
        s = window[col].dropna()
        if s.empty:
            continue
        any_data = True
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values / 1000,
            name=label, line=dict(color=color, width=1.8),
            hovertemplate=f"<b>{label}</b><br>%{{x|%d %b %Y}}<br>Net: %{{y:.1f}}K contracts<extra></extra>",
        ))
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.15)", line_dash="dash", line_width=1)
    fig.update_layout(
        template=PLOTLY_THEME, height=360, margin=margin,
        title=dict(text="CFTC COT — Leveraged Funds Net Positioning (contracts, 000s)", font=dict(size=13)),
        yaxis_title="Net Contracts (K)",
        legend=dict(orientation="h", y=-0.22, font=dict(size=10)),
    )
    if not any_data:
        fig.add_annotation(text="No CFTC data available yet — run data pipeline to fetch",
                           xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                           font=dict(color="#94a8c9", size=13))
    return fig


def _chart_cot_zscore(cot_df: "pd.DataFrame") -> "go.Figure":
    """Grouped bar chart: Z-score of current positioning vs 1Y and 3Y history."""
    margin = dict(l=60, r=20, t=44, b=80)
    summary = _cot_summary(cot_df)
    if summary.empty:
        fig = go.Figure()
        fig.update_layout(template=PLOTLY_THEME, height=320, margin=margin,
                          title="CFTC COT — Z-Score vs History")
        return fig

    labels = summary["Tenor"].tolist()
    z1y    = summary["Z (1Y)"].tolist()
    z3y    = summary["Z (3Y)"].tolist()

    def _bar_color(vals):
        return ["#4ade80" if v > 0 else "#f87171" for v in vals]

    fig = go.Figure([
        go.Bar(name="vs 1Y",  x=labels, y=z1y, marker_color=_bar_color(z1y),
               opacity=0.9,
               hovertemplate="<b>%{x}</b><br>Z-score vs 1Y: %{y:.2f}<extra></extra>"),
        go.Bar(name="vs 3Y",  x=labels, y=z3y, marker_color=_bar_color(z3y),
               opacity=0.55,
               hovertemplate="<b>%{x}</b><br>Z-score vs 3Y: %{y:.2f}<extra></extra>"),
    ])
    for lvl, dash in [(1, "dot"), (-1, "dot"), (2, "dash"), (-2, "dash")]:
        fig.add_hline(y=lvl, line_color="rgba(255,255,255,0.12)",
                      line_dash=dash, line_width=1)
    fig.update_layout(
        template=PLOTLY_THEME, height=320, margin=margin,
        barmode="group",
        title=dict(text="CFTC COT — Positioning Z-Score (Leveraged Funds)", font=dict(size=13)),
        yaxis_title="Z-score",
        legend=dict(orientation="h", y=-0.30, font=dict(size=10)),
    )
    return fig


def _chart_cot_changes(cot_df: "pd.DataFrame") -> "go.Figure":
    """Grouped bar: week-over-week and 4-week change in net LEV positioning."""
    margin = dict(l=60, r=20, t=44, b=80)
    summary = _cot_summary(cot_df)
    if summary.empty:
        fig = go.Figure()
        fig.update_layout(template=PLOTLY_THEME, height=320, margin=margin,
                          title="CFTC COT — Positioning Changes")
        return fig

    labels = summary["Tenor"].tolist()
    d1w = summary["ΔW (K)"].tolist()
    d4w = summary["Δ4W (K)"].tolist()

    def _bar_color(vals):
        return ["#4ade80" if v > 0 else "#f87171" for v in vals]

    fig = go.Figure([
        go.Bar(name="1W Change",  x=labels, y=d1w, marker_color=_bar_color(d1w),
               hovertemplate="<b>%{x}</b><br>1W Δ: %{y:.1f}K contracts<extra></extra>"),
        go.Bar(name="4W Change",  x=labels, y=d4w, marker_color=_bar_color(d4w),
               opacity=0.6,
               hovertemplate="<b>%{x}</b><br>4W Δ: %{y:.1f}K contracts<extra></extra>"),
    ])
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.2)", line_width=1)
    fig.update_layout(
        template=PLOTLY_THEME, height=320, margin=margin,
        barmode="group",
        title=dict(text="CFTC COT — Positioning Changes (K contracts)", font=dict(size=13)),
        yaxis_title="Change (K contracts)",
        legend=dict(orientation="h", y=-0.30, font=dict(size=10)),
    )
    return fig


def _chart_cot_am_vs_lev(cot_df: "pd.DataFrame", tenor: str = "10Y") -> "go.Figure":
    """
    Overlay Asset Manager vs Leveraged Funds net positioning for a single tenor.
    Both shown as area fills so the structural divergence is clear.
    """
    margin = dict(l=60, r=20, t=44, b=36)
    col_lev = f"COT_{tenor}_NET_LEV"
    col_am  = f"COT_{tenor}_NET_AM"
    _cot_label_map = {k: lbl for k, lbl, _ in _COT_TENORS}
    label   = _cot_label_map.get(tenor, tenor)
    window = cot_df.tail(104)
    fig = go.Figure()
    if col_lev in window.columns:
        s = window[col_lev].dropna()
        fig.add_trace(go.Scatter(
            x=s.index, y=s / 1000, name="Leveraged Funds",
            fill="tozeroy", fillcolor="rgba(248,113,113,0.18)",
            line=dict(color="#f87171", width=1.8),
            hovertemplate="%{x|%d %b %Y}<br>Lev: %{y:.1f}K<extra></extra>",
        ))
    if col_am in window.columns:
        s = window[col_am].dropna()
        fig.add_trace(go.Scatter(
            x=s.index, y=s / 1000, name="Asset Managers",
            fill="tozeroy", fillcolor="rgba(79,195,247,0.15)",
            line=dict(color="#4fc3f7", width=1.8),
            hovertemplate="%{x|%d %b %Y}<br>AM: %{y:.1f}K<extra></extra>",
        ))
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.2)", line_dash="dash", line_width=1)
    fig.update_layout(
        template=PLOTLY_THEME, height=340, margin=margin,
        title=dict(text=f"CFTC COT — {label}: Leveraged Funds vs Asset Managers", font=dict(size=13)),
        yaxis_title="Net (K contracts)",
        legend=dict(orientation="h", y=-0.22, font=dict(size=10)),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# PLOTLY CHART BUILDERS  (using existing app's PLOTLY_THEME = "plotly_dark")
# ══════════════════════════════════════════════════════════════════════════════
_MARGIN = dict(l=50, r=20, t=44, b=36)

def _chart_cta_hist(pos_hist):
    fig = go.Figure(go.Scatter(
        x=pos_hist.index, y=pos_hist.values,
        fill="tozeroy", fillcolor="rgba(79,195,247,0.25)",
        line=dict(color="#4fc3f7", width=1),
        name="CTA Position",
        hovertemplate="%{x|%d %b %Y}<br><b>%{y:.1f}bn</b><extra></extra>",
    ))
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.2)", line_dash="dash", line_width=1)
    start_lbl = pos_hist.index[0].strftime("%d%b%Y")
    end_lbl   = pos_hist.index[-1].strftime("%d%b%Y")
    for x, txt, anchor in [(pos_hist.index[0], f"—{start_lbl}—", "left"),
                            (pos_hist.index[-1], f"—{end_lbl}—", "right")]:
        fig.add_annotation(x=x, y=1, xref="x", yref="paper", text=txt,
                           showarrow=False, font=dict(size=9, color="#94a8c9"), xanchor=anchor)
    fig.update_layout(template=PLOTLY_THEME, height=360, margin=_MARGIN,
        title=dict(text="CTA Historical Realized Positioning in U.S. Equities (Histogram)",
                   font=dict(size=13)),
        yaxis_title="CTA Positioning ($bn)")
    return fig

def _chart_cta_proj(sp_hist_w, proj_results, ref_price):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sp_hist_w.index, y=sp_hist_w.values,
        line=dict(color="#4fc3f7", width=2.5), name="Realized",
        hovertemplate="%{x|%d %b %Y}<br><b>%{y:.2f}b</b><extra></extra>"))
    for (name, _), col in zip(CTA_SCENARIOS.items(), CTA_COLORS):
        p = proj_results[name]
        x = [sp_hist_w.index[-1]] + list(p.index)
        y = [float(sp_hist_w.iloc[-1])] + list(p.values)
        fig.add_trace(go.Scatter(x=x, y=y, line=dict(color=col, width=1.8),
            name=name, opacity=0.9,
            hovertemplate="%{x|%d %b %Y}<br><b>%{y:.2f}b</b><extra></extra>"))
    fig.add_annotation(x=sp_hist_w.index[-1], y=float(sp_hist_w.iloc[-1]),
        text=f"Ref. Price: {ref_price:,.0f}", showarrow=True, arrowhead=2,
        bgcolor="#233e6e", bordercolor="#4fc3f7",
        font=dict(color="#e8eef9", size=10), ax=40, ay=-30)
    fig.update_layout(template=PLOTLY_THEME, height=360, margin=_MARGIN,
        title="Projection Estimates — Up / Down / Flat Scenarios (S&P 500)",
        yaxis_title="CTA Positioning ($B)",
        legend=dict(orientation="h", y=-0.22, font=dict(size=10)))
    return fig

def _chart_flows_table(flows_df):
    flat_cols = [f"{p}|{l}" for p, subs in [
        ("1 Week",        ["Flat", "Up 2 STD", "Down 2.5 STD"]),
        ("1 Month",       ["Flat", "Up 2 STD", "Down 2.5 STD"]),
        ("Sim. Realized", ["Last Week", "Last Month"]),
    ] for l in subs]
    col_labels = [l for _, subs in [
        ("1 Week",        ["Flat", "Up 2 STD", "Down 2.5 STD"]),
        ("1 Month",       ["Flat", "Up 2 STD", "Down 2.5 STD"]),
        ("Sim. Realized", ["Last Week", "Last Month"]),
    ] for l in subs]

    def fmt(v):
        return f"{int(v):,}" if isinstance(v, (int, float, np.floating)) and not np.isnan(v) else "N/A"
    def cc(v):
        if not isinstance(v, (int, float, np.floating)) or np.isnan(v): return "#555577"
        if v < 0:
            i = min(abs(v) / 15000, 1.0); r = int(130 + 80 * i); return f"rgb({r},50,60)"
        return "#1a3056"

    cell_text   = [[fmt(flows_df.loc[m, c]) if c in flows_df.columns else "N/A" for c in flat_cols]
                   for m in flows_df.index]
    cell_colors = [[cc(flows_df.loc[m, c]) if c in flows_df.columns else "#555577" for c in flat_cols]
                   for m in flows_df.index]
    ct_T = list(zip(*cell_text))   if cell_text   else []
    cc_T = list(zip(*cell_colors)) if cell_colors else []

    fig = go.Figure(go.Table(
        header=dict(values=["Market"] + col_labels,
                    fill_color="#0d47a1", font=dict(color="#e8eef9", size=10),
                    align="center", height=26),
        cells=dict(
            values=[[m for m in flows_df.index]] + [list(c) for c in ct_T],
            fill_color=[["#0a1628"] * len(flows_df)] + [list(c) for c in cc_T],
            font=dict(color=["#e8eef9"] * len(flows_df), size=9),
            align=["left"] + ["right"] * len(col_labels),
            height=21,
        ),
    ))
    fig.update_layout(height=520, margin=dict(l=0, r=0, t=36, b=0),
        title=dict(text="Expected Flows in Different Scenarios by Market ($MM)",
                   font=dict(color="#e8eef9", size=13)))
    return fig

def _chart_systematic(syst):
    fig = go.Figure(go.Scatter(
        x=syst.index, y=syst.values,
        fill="tozeroy", fillcolor="rgba(79,195,247,0.12)",
        line=dict(color="#4fc3f7", width=1.5), name="Systematic"))
    fig.add_hline(y=float(syst.mean()), line_color="rgba(255,255,255,0.25)",
                  line_dash="dash", line_width=1, annotation_text="Mean",
                  annotation_font_color="#94a8c9")
    fig.update_layout(template=PLOTLY_THEME, height=360, margin=_MARGIN,
        title="Systematic Aggregated Positioning — CTAs + Risk Parity + Vol Ctrl",
        yaxis_title="Positioning ($bn)",
        annotations=[dict(x=0.5, y=0.04, xref="paper", yref="paper",
            text="CTAs + Risk Parity + Vol Controlled Funds",
            showarrow=False, font=dict(color="#6a7e9e", size=10))])
    return fig

def _chart_rp(bond_exp, eq_exp, cb, ce, bond_lbl, eq_lbl):
    fig = make_subplots(rows=1, cols=2,
        subplot_titles=("UBS Risk Parity Bond Exposure", "UBS Risk Parity Equity Exposure"))
    fig.add_trace(go.Scatter(x=bond_exp.index, y=bond_exp.values,
        line=dict(color="orange", width=1.5), name="Bond Exp"), row=1, col=1)
    fig.add_hline(y=cb, line_color="#f87171", line_width=1.5, row=1, col=1)
    fig.add_annotation(x=bond_exp.index[-1], y=cb, text=bond_lbl, showarrow=False,
        bgcolor="#122340", bordercolor="#4fc3f7", font=dict(color="#4fc3f7", size=9),
        xanchor="right", row=1, col=1)
    fig.add_trace(go.Scatter(x=eq_exp.index, y=eq_exp.values,
        line=dict(color="#4fc3f7", width=1.5), name="Equity Exp"), row=1, col=2)
    fig.add_hline(y=ce, line_color="#f87171", line_width=1.5, row=1, col=2)
    fig.add_annotation(x=eq_exp.index[-1], y=ce, text=eq_lbl, showarrow=False,
        bgcolor="#122340", bordercolor="#4fc3f7", font=dict(color="#4fc3f7", size=9),
        xanchor="right", row=1, col=2)
    fig.update_yaxes(ticksuffix="%")
    fig.update_layout(template=PLOTLY_THEME, height=360, margin=_MARGIN,
        showlegend=False, title="UBS Risk Parity Exposures")
    return fig

def _chart_exp_sharpe(sr_df):
    fig = px.scatter(sr_df, x="Signal", y="Sharpe",
        size="BubbleSize", color="Direction",
        color_discrete_map={"Buying": "#4fc3f7", "Selling": "#f87171"},
        text="Market",
        hover_data={"BubbleSize": False, "Direction": False,
                    "Flow1W": ":.0f", "AnnReturn": ":.2%", "AnnVol": ":.2%"},
        size_max=52)
    fig.update_traces(textposition="top center", textfont_size=9,
                      textfont_color="#e8eef9")
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.2)", line_dash="dash", line_width=1)
    fig.add_vline(x=0, line_color="rgba(255,255,255,0.2)", line_dash="dash", line_width=1)
    fig.update_layout(template=PLOTLY_THEME, height=500, margin=_MARGIN,
        title=dict(text="Expected Sharpe by Market — bubble size = 1-week CTA flow ($MM)",
                   font=dict(size=13)),
        xaxis_title="CTA Signal  (← short | 0=neutral | long →)",
        yaxis_title="Expected Sharpe  (1M ann. return ÷ 63-day vol)",
        legend=dict(title="Direction", orientation="h", y=-0.14))
    return fig

def _chart_exp_return(sr_df):
    df_s = sr_df.sort_values("AnnReturn", ascending=True)
    fig  = go.Figure(go.Bar(
        x=(df_s["AnnReturn"] * 100).round(1), y=df_s["Market"],
        orientation="h",
        marker_color=["#f87171" if v < 0 else "#4fc3f7" for v in df_s["AnnReturn"]],
        text=(df_s["AnnReturn"] * 100).round(1).astype(str) + "%",
        textposition="auto",
        hovertemplate="%{y}<br><b>%{x:.1f}%</b><extra></extra>",
    ))
    fig.add_vline(x=0, line_color="rgba(255,255,255,0.2)", line_width=1)
    fig.update_layout(template=PLOTLY_THEME, height=420, margin=_MARGIN,
        title="Expected Annualised Return by Market (1M rolling, annualised)",
        xaxis_title="Annualised Return (%)")
    return fig

def _chart_top_bottom(sr_df):
    s    = sr_df.sort_values("Sharpe", ascending=False)
    comb = pd.concat([s.head(3), s.tail(3)])
    fig  = go.Figure(go.Bar(
        x=comb["Sharpe"].round(2), y=comb["Market"],
        orientation="h",
        marker_color=["#4ade80" if v > 0 else "#f87171" for v in comb["Sharpe"]],
        text=comb["Sharpe"].round(2), textposition="auto",
        hovertemplate="%{y}<br>Sharpe: <b>%{x:.2f}</b><extra></extra>",
    ))
    fig.add_vline(x=0, line_color="rgba(255,255,255,0.2)", line_width=1)
    fig.update_layout(template=PLOTLY_THEME, height=340, margin=_MARGIN,
        title="Top 3 & Bottom 3 Markets by Expected Sharpe")
    return fig

def _chart_vol_flows(merged, fwd_vols):
    import matplotlib.cm as _cm
    cols = [f"rgba({int(c[0]*255)},{int(c[1]*255)},{int(c[2]*255)},0.7)"
            for c in [_cm.viridis(i / max(len(fwd_vols)-1, 1)) for i in range(len(fwd_vols))]]
    fig = make_subplots(rows=2, cols=1,
        subplot_titles=("Daily Flow (USD bn)", "Cumulative Flow (USD bn)"),
        shared_xaxes=True, vertical_spacing=0.10)
    for i, fv in enumerate(fwd_vols):
        # Support both old float-keyed columns and new %-keyed columns
        lbl = f"{fv:.0%}" if fv < 1 else str(fv)
        dc  = f"Daily Flow ({lbl})"
        cc  = f"Cumulative Flow ({lbl})"
        if dc not in merged.columns:
            dc = f"Daily Flow ({fv})"
            cc = f"Cumulative Flow ({fv})"
        if dc in merged.columns:
            fig.add_trace(go.Scatter(x=merged.index, y=merged[dc], fill="tozeroy",
                fillcolor=cols[i], line=dict(color=cols[i]),
                name=f"Daily {lbl}", legendgroup=f"g{i}"), row=1, col=1)
        if cc in merged.columns:
            fig.add_trace(go.Scatter(x=merged.index, y=merged[cc],
                line=dict(color=cols[i], width=2), name=f"Cum. {lbl}",
                legendgroup=f"g{i}", showlegend=False), row=2, col=1)
    fig.update_layout(template=PLOTLY_THEME, height=500,
        margin=dict(l=50, r=20, t=44, b=80),
        title="Vol-Controlled Fund Flows Under Different Forward Vol Assumptions",
        legend=dict(orientation="h", y=-0.16, font=dict(size=10)))
    return fig

# ══════════════════════════════════════════════════════════════════════════════
# ALERT HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _load_alert_cfg():
    default = {"recipients": [], "charts": DEFAULT_ALERT_CHARTS, "schedule": "daily",
               "last_sent": None}
    if ALERT_CFG_PATH.exists():
        return {**default, **json.loads(ALERT_CFG_PATH.read_text())}
    return default

def _save_alert_cfg(cfg):
    ALERT_CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERT_CFG_PATH.write_text(json.dumps(cfg, indent=2))

def _mpl_fig_bytes(mpl_fig):
    buf = io.BytesIO()
    mpl_fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                    facecolor="#0a1628")
    buf.seek(0)
    return buf.read()

def _build_mpl_expected_sharpe(sr_df):
    fig, ax = plt.subplots(figsize=(12, 6), facecolor="#0a1628")
    ax.set_facecolor("#0a1628")
    mxf = sr_df["Flow1W"].abs().max()
    sizes  = (sr_df["Flow1W"].abs() / (mxf + 1e-8)) * 1200 + 60
    colors = ["#4fc3f7" if d == "Buying" else "#f87171" for d in sr_df["Direction"]]
    ax.scatter(sr_df["Signal"], sr_df["Sharpe"], s=sizes, c=colors,
               alpha=0.7, edgecolors="white", linewidths=0.8, zorder=3)
    for _, r in sr_df.iterrows():
        ax.annotate(r["Market"], xy=(r["Signal"], r["Sharpe"]),
                    fontsize=7.5, ha="center", va="bottom", color="#e8eef9",
                    xytext=(0, 7), textcoords="offset points")
    ax.axhline(0, color="white", lw=0.5, ls="--", alpha=0.3)
    ax.axvline(0, color="white", lw=0.5, ls="--", alpha=0.3)
    ref_flows = [500, 2000, max(int(mxf * 0.8), 3000)]
    ref_sizes = [(v / (mxf + 1e-8)) * 1200 + 60 for v in ref_flows]
    handles = [ax.scatter([], [], s=s, color="#888", alpha=0.6, ec="white",
                          label=f"${v:,}MM/wk") for s, v in zip(ref_sizes, ref_flows)]
    handles += [ax.scatter([], [], s=140, color="#4fc3f7", ec="white", label="Buying"),
                ax.scatter([], [], s=140, color="#f87171", ec="white", label="Selling")]
    leg = ax.legend(handles=handles, title="Bubble = 1-week flow",
                    title_fontsize=8, fontsize=8, loc="lower right",
                    framealpha=0.4, edgecolor="#233e6e",
                    labelcolor="#e8eef9", facecolor="#122340")
    leg.get_title().set_color("#94a8c9")
    ax.set_title("Expected Sharpe by Market", color="#e8eef9", fontsize=12, fontweight="bold")
    ax.set_xlabel("CTA Signal", color="#94a8c9", fontsize=9)
    ax.set_ylabel("Expected Sharpe", color="#94a8c9", fontsize=9)
    ax.tick_params(colors="#94a8c9")
    for sp in ax.spines.values(): sp.set_color("#233e6e")
    ax.grid(True, color="#1a3056", alpha=0.5, ls="--")
    plt.tight_layout()
    return fig

def _build_mpl_expected_return(sr_df):
    df_s = sr_df.sort_values("AnnReturn", ascending=True)
    fig, ax = plt.subplots(figsize=(10, 6), facecolor="#0a1628")
    ax.set_facecolor("#0a1628")
    ax.barh(df_s["Market"], df_s["AnnReturn"] * 100,
            color=["#f87171" if v < 0 else "#4fc3f7" for v in df_s["AnnReturn"]])
    ax.axvline(0, color="white", lw=0.5, alpha=0.3)
    ax.set_title("Expected Annualised Return by Market", color="#e8eef9", fontsize=12, fontweight="bold")
    ax.set_xlabel("Annualised Return (%)", color="#94a8c9")
    ax.tick_params(colors="#94a8c9")
    for sp in ax.spines.values(): sp.set_color("#233e6e")
    ax.grid(True, color="#1a3056", alpha=0.5, axis="x", ls="--")
    plt.tight_layout()
    return fig

def _build_mpl_top_bottom(sr_df):
    s    = sr_df.sort_values("Sharpe", ascending=False)
    comb = pd.concat([s.head(3), s.tail(3)])
    fig, ax = plt.subplots(figsize=(8, 5), facecolor="#0a1628")
    ax.set_facecolor("#0a1628")
    ax.barh(comb["Market"], comb["Sharpe"],
            color=["#4ade80" if v > 0 else "#f87171" for v in comb["Sharpe"]])
    ax.axvline(0, color="white", lw=0.5, alpha=0.3)
    ax.set_title("Top 3 & Bottom 3 Markets by Expected Sharpe",
                 color="#e8eef9", fontsize=12, fontweight="bold")
    ax.tick_params(colors="#94a8c9")
    for sp in ax.spines.values(): sp.set_color("#233e6e")
    ax.grid(True, color="#1a3056", alpha=0.5, axis="x", ls="--")
    plt.tight_layout()
    return fig

MPL_BUILD_FNS = {
    "expected_sharpe":   _build_mpl_expected_sharpe,
    "expected_return":   _build_mpl_expected_return,
    "top_bottom_sharpe": _build_mpl_top_bottom,
}

# ══════════════════════════════════════════════════════════════════════════════
# WEEKLY EMAIL BODY BUILDERS
# Monday = Week Ahead (forward-looking setup)
# Friday = Week in Review (recap, signal scorecard, what we got right/wrong)
# ══════════════════════════════════════════════════════════════════════════════

def _signal_scorecard(mkt_prices_dict: dict) -> pd.DataFrame:
    """Compare each market's Monday signal direction vs actual WTD return."""
    rows = []
    for mkt in MKTS:
        p = mkt_prices_dict.get(mkt)
        if p is None or len(p) < 260:
            continue
        try:
            sig_5d  = float(_cta_signal(p.iloc[:-5]).iloc[-1])
            sig_now = float(_cta_signal(p).iloc[-1])
            ret_5d  = float(np.log(p.iloc[-1] / p.iloc[-6]))
            bias    = "Long" if sig_5d > 0.1 else ("Short" if sig_5d < -0.1 else "Neutral")
            actual  = "↑ Up" if ret_5d > 0 else "↓ Down"
            hit = (
                (bias == "Long"    and ret_5d > 0) or
                (bias == "Short"   and ret_5d < 0) or
                (bias == "Neutral")
            )
            rows.append({
                "Market":    mkt,
                "Mon Signal": f"{sig_5d:+.3f}",
                "Bias":      bias,
                "Actual":    actual,
                "WTD":       f"{ret_5d * 100:+.1f}%",
                "Now":       f"{sig_now:+.3f}",
                "✓/✗":       "✓" if hit else "✗",
            })
        except Exception:
            continue
    return pd.DataFrame(rows)


def _kpi_html(label: str, value: str, color: str = "#e8eef9") -> str:
    return (
        f"<div style='min-width:130px'>"
        f"<div style='color:#94a8c9;font-size:11px;text-transform:uppercase;letter-spacing:.05em'>{label}</div>"
        f"<div style='font-size:20px;font-weight:700;color:{color}'>{value}</div></div>"
    )


def _df_html(df: pd.DataFrame, cell_color_fn=None) -> str:
    """Dark-themed HTML table from a DataFrame."""
    if df.empty:
        return "<p style='color:#94a8c9;font-size:12px'>No data</p>"
    hdr = "".join(
        f"<th style='padding:5px 10px;color:#94a8c9;font-weight:500;text-align:left"
        f";border-bottom:1px solid #233e6e'>{c}</th>"
        for c in df.columns
    )
    body_rows = []
    for _, row in df.iterrows():
        cells = []
        for col in df.columns:
            val = str(row[col])
            col_str = "color:#e8eef9;"
            if cell_color_fn:
                c = cell_color_fn(col, row[col])
                if c:
                    col_str = f"color:{c};"
            cells.append(
                f"<td style='padding:5px 10px;{col_str}border-bottom:1px solid #1a3056'>{val}</td>"
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:12px'>"
        f"<thead><tr>{hdr}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    )


def _card(title: str, body: str) -> str:
    return (
        f"<div style='background:#122340;border-radius:8px;padding:16px;margin:12px 0'>"
        f"<h3 style='color:#e8eef9;margin:0 0 12px;font-size:14px'>{title}</h3>{body}</div>"
    )


def _build_monday_html(sr_df, flows_df, pos_hist, ref_price) -> str:
    """Monday 'Week Ahead' email — forward-looking setup."""
    from datetime import date, timedelta
    today   = date.today()
    fri_d   = today + timedelta(days=4 - today.weekday())
    cur_pos = float(pos_hist.iloc[-1])
    pos_col = "#4ade80" if cur_pos > 0 else "#f87171"

    spx = sr_df[sr_df["Market"] == "S&P 500 E-mini"]
    spx_sig = float(spx["Signal"].iloc[0]) if not spx.empty else 0.0
    spx_dir = "🟢 Long" if spx_sig > 0.1 else ("🔴 Short" if spx_sig < -0.1 else "⬜ Neutral")

    # Top 5 signals
    top5 = sr_df.nlargest(5, "Sharpe")[["Market", "Signal", "Sharpe", "AnnReturn"]].copy()
    top5.rename(columns={"AnnReturn": "Ann Ret"}, inplace=True)
    top5["Signal"]  = top5["Signal"].map(lambda x: f"{x:+.3f}")
    top5["Sharpe"]  = top5["Sharpe"].map(lambda x: f"{x:+.2f}")
    top5["Ann Ret"] = top5["Ann Ret"].map(lambda x: f"{x:.1%}")

    # Flow table — 1W scenarios, top 8 markets
    flow_rename = {
        "1 Week|Flat":            "1W Flat",
        "1 Week|Up 2 STD":        "1W +2σ",
        "1 Week|Down 2.5 STD":    "1W -2.5σ",
        "Sim. Realized|Last Week": "Realized LW",
    }
    _fc = [c for c in flow_rename if c in flows_df.columns]
    flow_tbl = flows_df[_fc].rename(columns=flow_rename).head(8).reset_index()

    kpis = "".join([
        _kpi_html("S&P 500", f"{ref_price:,.0f}"),
        _kpi_html("CTA Position", f"{cur_pos:+.1f}bn", pos_col),
        _kpi_html("S&P Signal", f"{spx_dir}"),
    ])

    return "".join([
        "<html><body style=\"font-family:'Inter',Arial,sans-serif;background:#0a1628;"
        "color:#e8eef9;padding:24px;max-width:720px;margin:0 auto\">",

        f"<div style='border-left:4px solid #4fc3f7;padding-left:16px;margin-bottom:20px'>"
        f"<h2 style='color:#4fc3f7;margin:0'>📊 Week Ahead Setup</h2>"
        f"<p style='color:#94a8c9;margin:4px 0 0'>{today.strftime('%-d %b %Y')}"
        f" — what to watch through {fri_d.strftime('%-d %b')}</p></div>",

        _card("Market Snapshot",
              f"<div style='display:flex;gap:24px;flex-wrap:wrap'>{kpis}</div>"),

        _card("⭐ Top 5 Signals — Highest Risk-Adjusted Return", _df_html(top5)),

        _card("📋 Expected CTA Flow Scenarios ($MM)",
              _df_html(flow_tbl) +
              "<p style='color:#6a7e9e;font-size:11px;margin-top:8px'>"
              "CTA rebalancing flows under different weekly price paths. "
              "Positive = buying pressure, negative = selling pressure.</p>"),

        "<hr style='border-color:#233e6e;margin:20px 0'>",
        "<p style='color:#6a7e9e;font-size:11px'>Macro Manv Rates Dashboard &nbsp;·&nbsp; "
        "Model estimates from price momentum — not actual fund positioning data</p>",
        "</body></html>",
    ])


def _build_friday_html(sr_df, mkt_prices_dict, pos_hist, ref_price) -> str:
    """Friday 'Week in Review' email — recap, signal scorecard, what we got right/wrong."""
    from datetime import date, timedelta
    today   = date.today()
    mon_d   = today - timedelta(days=today.weekday())
    cur_pos = float(pos_hist.iloc[-1])
    pos_col = "#4ade80" if cur_pos > 0 else "#f87171"

    sc = _signal_scorecard(mkt_prices_dict)

    n_hits = n_total = 0
    hit_rate = 0.0
    if not sc.empty:
        directional = sc[sc["Bias"] != "Neutral"]
        n_hits  = int((directional["✓/✗"] == "✓").sum())
        n_total = len(directional)
        hit_rate = n_hits / n_total if n_total > 0 else 0.0

    hit_col = "#4ade80" if hit_rate >= 0.65 else ("#f59e0b" if hit_rate >= 0.45 else "#f87171")
    verdict = (
        "Strong week — signals were largely directionally correct."
        if hit_rate >= 0.65 else
        "Mixed signals — roughly half the directional calls were correct."
        if hit_rate >= 0.45 else
        "Challenging week — model struggled with direction. Worth reviewing macro context."
    )

    def _sc_color(col, val):
        if col == "✓/✗":
            return "#4ade80" if val == "✓" else "#f87171"
        if col == "WTD":
            try:
                return "#4ade80" if float(str(val).replace("%", "")) > 0 else "#f87171"
            except Exception:
                pass
        if col == "Bias":
            return {"Long": "#4fc3f7", "Short": "#f87171", "Neutral": "#94a8c9"}.get(str(val), None)
        return None

    # Sort by absolute WTD move for the recap
    if not sc.empty:
        _sc2 = sc.copy()
        _sc2["_abs"] = _sc2["WTD"].str.replace("%", "").astype(float).abs()
        top_movers = _sc2.nlargest(8, "_abs")[["Market", "Bias", "Actual", "WTD", "✓/✗"]]
    else:
        top_movers = pd.DataFrame()

    # Signal standings going into next week
    nw = sr_df.nlargest(6, "Sharpe")[["Market", "Signal", "Sharpe"]].copy()
    nw["Signal"] = nw["Signal"].map(lambda x: f"{x:+.3f}")
    nw["Sharpe"] = nw["Sharpe"].map(lambda x: f"{x:+.2f}")

    def _nw_color(col, val):
        if col == "Signal":
            try:
                return "#4ade80" if float(val) > 0 else "#f87171"
            except Exception:
                pass
        return None

    kpis = "".join([
        _kpi_html("S&P 500", f"{ref_price:,.0f}"),
        _kpi_html("CTA Position", f"{cur_pos:+.1f}bn", pos_col),
        _kpi_html(f"Hit Rate ({n_hits}/{n_total})", f"{hit_rate:.0%}", hit_col),
    ])

    return "".join([
        "<html><body style=\"font-family:'Inter',Arial,sans-serif;background:#0a1628;"
        "color:#e8eef9;padding:24px;max-width:720px;margin:0 auto\">",

        f"<div style='border-left:4px solid #4ade80;padding-left:16px;margin-bottom:20px'>"
        f"<h2 style='color:#4ade80;margin:0'>📊 Week in Review</h2>"
        f"<p style='color:#94a8c9;margin:4px 0 0'>{today.strftime('%-d %b %Y')}"
        f" — week of {mon_d.strftime('%-d %b')}</p></div>",

        _card("Weekly Summary",
              f"<div style='display:flex;gap:24px;flex-wrap:wrap;margin-bottom:12px'>{kpis}</div>"
              f"<p style='color:#94a8c9;font-size:13px;margin:0'>Verdict: "
              f"<b style='color:{hit_col}'>{verdict}</b></p>"),

        _card(
            "🎯 Signal Scorecard — Did the Model Get Direction Right?",
            _df_html(top_movers, cell_color_fn=_sc_color)
            + f"<p style='color:#6a7e9e;font-size:11px;margin-top:8px'>"
              f"Monday signal bias vs actual WTD price move · "
              f"<b style='color:{hit_col}'>{n_hits}/{n_total} directional calls correct</b>. "
              "Neutral signals (|signal| ≤ 0.1) are not counted as hits or misses.</p>"
            if not top_movers.empty else "<p style='color:#94a8c9'>Insufficient data</p>",
        ),

        _card(
            "🔮 Signal Standings Going Into Next Week",
            _df_html(nw, cell_color_fn=_nw_color)
            + "<p style='color:#6a7e9e;font-size:11px;margin-top:8px'>"
              "Top 6 markets by current Sharpe — these are the setups to watch Monday.</p>",
        ),

        "<hr style='border-color:#233e6e;margin:20px 0'>",
        "<p style='color:#6a7e9e;font-size:11px'>Macro Manv Rates Dashboard &nbsp;·&nbsp; "
        "Model estimates from price momentum — not actual fund positioning data</p>",
        "</body></html>",
    ])

# ══════════════════════════════════════════════════════════════════════════════
# LOAD DATA
# ══════════════════════════════════════════════════════════════════════════════
try:
    sp           = _load_sp500()
    mkt_p        = _load_markets()
    rp_eq, rp_bd = _load_rp()
except Exception as _load_err:
    st.error(f"Failed to load market data from yfinance: {_load_err}")
    st.info("This page requires an internet connection to fetch equity index data from Yahoo Finance. Please try again later.")
    st.stop()

if sp.empty:
    st.error("Could not load S&P 500 data from Yahoo Finance. The service may be temporarily unavailable.")
    st.stop()

pos_hist, sp_hist_w, proj, flows_df, sr_df, syst = _compute_cta(sp, mkt_p)
bond_exp, eq_exp, curr_bond, curr_eq, bond_lbl, eq_lbl = _compute_rp(rp_eq, rp_bd)
ref_price = float(sp.iloc[-1])
cot_df    = _load_cot_data()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE HEADER + KPI ROW
# ══════════════════════════════════════════════════════════════════════════════
st.title("📊 CTA & Systematic Fund Positioning (Model Estimate)")
st.markdown(
    '<p style="color:var(--c-text-2);font-size:15px;margin-top:-4px;">'
    "Model-derived estimate from price momentum — not actual fund positioning or CFTC COT data. "
    "CTA trend model · Risk parity exposures · Vol-controlled fund flows"
    "</p>",
    unsafe_allow_html=True,
)

with st.expander("ℹ️ About this page — data sources & methodology"):
    st.markdown("""
**All data is fetched live from Yahoo Finance** via the `yfinance` library. No actual fund
positioning data is used — these are *model estimates* derived from price momentum.

| Section | Data source | What's modelled |
|---|---|---|
| **CTA Historical / Projection** | `^GSPC` (S&P 500) via Yahoo Finance | Blended 21/63/252-day momentum signal, scaled to ±$80bn notional |
| **Expected Flows Table** | 16 global equity indices via Yahoo Finance | Per-market flow estimates under flat / +2σ / −2.5σ price scenarios |
| **Systematic Positioning** | Same S&P 500 signal | Aggregate proxy for CTAs + Risk Parity + Vol Control |
| **Risk Parity** | `^GSPC` + `TLT` via Yahoo Finance | EWMA 63-day vol → UBS-style bond & equity exposure estimate |
| **Vol Control (Tab 2)** | `^GSPC` 1-year history via Yahoo Finance | EWMA 30/90-day vol → equity weight = target_vol ÷ realised_vol |

**Key model parameters (CTA):**
- Lookbacks: 21d (40% weight), 63d (35%), 252d (25%)
- Signal: normalised log-return ÷ realised vol, squashed via tanh
- Max position: ±$80bn, total universe: $300bn

These are rule-based model estimates. They track the *direction and magnitude* CTAs would likely
be positioned based on price momentum, but will not match actual fund data exactly.
""")

st.divider()

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("CTA Position ($bn)",  f"{pos_hist.iloc[-1]:.1f}")
m2.metric("CTA Signal",          f"{_cta_signal(sp).iloc[-1]:.3f}")
m3.metric("Bond Exposure (RP)",  f"{curr_bond:.0f}%")
m4.metric("Equity Exposure (RP)",f"{curr_eq:.0f}%")
m5.metric("S&P 500",             f"{ref_price:,.0f}")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab_labels = ["📋 CFTC Real Data", "📈 CTA Model (Estimate)", "⚙️ Vol Control Strategies"]
if is_admin():
    tab_labels.append("📧 Alert Settings")
tabs = st.tabs(tab_labels)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 0 — CFTC REAL DATA
# ─────────────────────────────────────────────────────────────────────────────
with tabs[0]:
    st.subheader("CFTC Commitment of Traders — Rates Futures (Leveraged Funds)")
    st.caption(
        "Source: CFTC Traders in Financial Futures (TFF) report, published every Friday. "
        "**Leveraged Funds** = CTAs, hedge funds, and other leveraged money. "
        "**Asset Managers** = pension funds, mutual funds, and real-money buyers. "
        "Net = Long − Short, in thousands of contracts. Weekly data, ~3-day reporting lag."
    )

    if cot_df.empty:
        st.warning(
            "No CFTC COT data found in the master dataset. "
            "Make sure the data pipeline has run (the CFTCFetcher hits the CFTC Socrata API — "
            "no API key required). Try refreshing data from the sidebar or "
            "running `python -m data.pipeline` from the project root."
        )
    else:
        # ── Latest report date ────────────────────────────────────────────
        latest_date = cot_df.index.max()
        st.caption(f"Latest CFTC report date in cache: **{latest_date.strftime('%d %b %Y')}**")

        # ── Summary metrics row ───────────────────────────────────────────
        summary = _cot_summary(cot_df)
        if not summary.empty:
            met_cols = st.columns(len(summary))
            for col_ui, (_, row) in zip(met_cols, summary.iterrows()):
                net  = row["Net Lev (K)"]
                chg  = row["ΔW (K)"]
                z1y  = row["Z (1Y)"]
                pct  = row["Pct 1Y"]
                icon = "🟢" if net > 0 else "🔴"
                col_ui.metric(
                    label=f"{icon} {row['Tenor']}",
                    value=f"{net:+.0f}K",
                    delta=f"{chg:+.1f}K WoW",
                    help=f"Z-score vs 1Y: {z1y:.2f}  |  {pct}th pct vs 1Y history",
                )

            st.divider()

        # ── Row 1: History + Z-score ──────────────────────────────────────
        r1a, r1b = st.columns(2)
        with r1a:
            st.plotly_chart(_chart_cot_history(cot_df), use_container_width=True)
        with r1b:
            st.plotly_chart(_chart_cot_zscore(cot_df),  use_container_width=True)

        # ── Row 2: Changes + AM vs Lev tenor selector ─────────────────────
        r2a, r2b = st.columns(2)
        with r2a:
            st.plotly_chart(_chart_cot_changes(cot_df), use_container_width=True)
        with r2b:
            tenor_opt = st.selectbox(
                "Tenor for AM vs Lev chart",
                options=["2Y", "5Y", "10Y", "30Y"],
                index=2,  # default: 10Y
                key="cot_tenor_sel",
            )
            st.plotly_chart(_chart_cot_am_vs_lev(cot_df, tenor_opt),
                            use_container_width=True)

        # ── Summary table ─────────────────────────────────────────────────
        st.divider()
        st.subheader("📋 COT Summary Table")
        if not summary.empty:
            def _color_z(val):
                try:
                    v = float(val)
                    if v >= 1.5:   return "background-color:#14532d;color:#fff"
                    if v <= -1.5:  return "background-color:#7f1d1d;color:#fff"
                    if v >= 0.75:  return "background-color:#166534;color:#fff"
                    if v <= -0.75: return "background-color:#991b1b;color:#fff"
                except Exception:
                    pass
                return ""

            def _color_chg(val):
                try:
                    v = float(val)
                    if v > 0:  return "color:#4ade80"
                    if v < 0:  return "color:#f87171"
                except Exception:
                    pass
                return ""

            styled = (
                summary.style
                .map(_color_z,  subset=["Z (1Y)", "Z (3Y)"])
                .map(_color_chg, subset=["ΔW (K)", "Δ4W (K)"])
                .format({
                    "Net Lev (K)": "{:+.1f}",
                    "ΔW (K)":      "{:+.1f}",
                    "Δ4W (K)":     "{:+.1f}",
                    "Z (1Y)":      "{:+.2f}",
                    "Z (3Y)":      "{:+.2f}",
                    "Pct 1Y":      "{}th",
                    "Pct 3Y":      "{}th",
                    "AM Net (K)":  "{:+.1f}",
                })
            )
            st.dataframe(styled, hide_index=True, use_container_width=True)

        st.caption(
            "**Net Lev (K)**: Leveraged Funds net position in thousands of contracts. "
            "**Z (1Y/3Y)**: how many standard deviations from mean over that window — >2 = extreme long, <−2 = extreme short. "
            "**AM Net**: Asset Manager net position (structural buyers, typically opposite side). "
            "Data published weekly by CFTC, ~3-day lag."
        )

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — CTA MODEL (formerly Tab 0)
# ─────────────────────────────────────────────────────────────────────────────
with tabs[1]:
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(_chart_cta_hist(pos_hist),         use_container_width=True)
    with c2:
        st.plotly_chart(_chart_cta_proj(sp_hist_w, proj, ref_price), use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(_chart_systematic(syst),           use_container_width=True)
    with c4:
        st.plotly_chart(_chart_flows_table(flows_df),      use_container_width=True)

    st.plotly_chart(_chart_rp(bond_exp, eq_exp, curr_bond, curr_eq, bond_lbl, eq_lbl),
                    use_container_width=True)

    st.markdown('<p class="section-header">Market Analytics</p>', unsafe_allow_html=True)
    ca, cb_ = st.columns(2)
    with ca:
        st.plotly_chart(_chart_exp_sharpe(sr_df),  use_container_width=True)
    with cb_:
        st.plotly_chart(_chart_exp_return(sr_df),  use_container_width=True)

    st.plotly_chart(_chart_top_bottom(sr_df), use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — VOL CONTROL
# ─────────────────────────────────────────────────────────────────────────────
with tabs[2]:
    st.subheader("⚙️ Vol-Controlled Fund Flows")
    st.caption(
        "EWMA 30/90-day realised vol → equity weight = target_vol ÷ vol_used (capped 1.5×). "
        "Adjust parameters below to run your own assumptions."
    )

    # ── Model parameter inputs ────────────────────────────────────────────
    with st.expander("⚙️ Model Parameters", expanded=True):
        _pc1, _pc2, _pc3, _pc4 = st.columns(4)
        _vc_aum   = _pc1.number_input(
            "AUM ($bn)", min_value=10.0, max_value=5000.0, value=300.0,
            step=25.0, key="vc_aum",
            help="Total assets under management of vol-controlled strategies (Reuters / DB estimate: ~$300bn)"
        ) * 1e9
        _vc_tvol  = _pc2.number_input(
            "Target vol (%)", min_value=1.0, max_value=30.0, value=12.0,
            step=0.5, key="vc_tvol",
            help="Annualised volatility target. Equity weight = target_vol ÷ realised_vol"
        ) / 100.0
        _vc_lam30 = _pc3.number_input(
            "EWMA λ (30d)", min_value=0.80, max_value=0.99, value=0.94,
            step=0.01, key="vc_lam30",
            help="Exponential decay factor for the 30-day EWMA variance estimator. Higher = more weight on recent moves"
        )
        _vc_lam90 = _pc4.number_input(
            "EWMA λ (90d)", min_value=0.80, max_value=0.99, value=0.97,
            step=0.01, key="vc_lam90",
            help="Exponential decay factor for the 90-day EWMA variance estimator"
        )

        st.markdown("**Forward vol scenarios** — one per column (%):")
        _fvc = st.columns(5)
        _fv_defaults = [20.0, 18.0, 16.0, 14.0, 12.0]
        _fv_vals = []
        for _i, (_c, _def) in enumerate(zip(_fvc, _fv_defaults)):
            _v = _c.number_input(
                f"Scen {_i+1}", min_value=1.0, max_value=60.0,
                value=_def, step=1.0, key=f"vc_fv{_i}",
            )
            _fv_vals.append(_v / 100.0)
        _fwd_vols_input = tuple(sorted(set(_fv_vals), reverse=True))

        _vc_fwd_days = st.slider(
            "Projection horizon (business days)", min_value=20, max_value=252,
            value=80, step=5, key="vc_fwd_days",
            help="How many business days forward to project the flow estimates"
        )

    # ── Compute with chosen parameters ────────────────────────────────────
    with st.spinner("Computing vol-control model across all markets…"):
        _hist_vc, _merged_vc, _flows_tbl_vc = _load_vol_control(
            aum         = _vc_aum,
            target_vol  = _vc_tvol,
            lambda_30   = _vc_lam30,
            lambda_90   = _vc_lam90,
            forward_vols= _fwd_vols_input,
            periods_fwd = _vc_fwd_days,
        )

    st.divider()

    # ── Current vol diagnostics (S&P) ────────────────────────────────────
    if not _hist_vc.empty:
        _last = _hist_vc.iloc[-1]
        _dc1, _dc2, _dc3, _dc4 = st.columns(4)
        _dc1.metric("30d EWMA Vol",    f"{_last['vol_30']:.1%}")
        _dc2.metric("90d EWMA Vol",    f"{_last['vol_90']:.1%}")
        _dc3.metric("Vol Used (max)",  f"{_last['vol_used']:.1%}")
        _dc4.metric("Current Exposure",f"{_last['equity_weight']:.2f}×",
                    help="Equity allocation as a fraction of AUM. 1.0 = fully invested.")
        _half30 = f"{-np.log(2)/np.log(_vc_lam30):.0f}d"
        _half90 = f"{-np.log(2)/np.log(_vc_lam90):.0f}d"
        st.caption(
            f"EWMA half-lives: λ₃₀={_vc_lam30} → ~{_half30} · "
            f"λ₉₀={_vc_lam90} → ~{_half90}. "
            "Longer half-life = slower re-risking after a vol spike."
        )
        st.divider()

    # ── Forward flow projection chart ─────────────────────────────────────
    st.markdown("#### Forward Flow Projections — S&P 500 (AUM-weighted)")
    _sel_cols = st.columns(len(_fwd_vols_input))
    _fwd_sel  = []
    for _c, _fv in zip(_sel_cols, _fwd_vols_input):
        if _c.checkbox(f"{_fv:.0%}", value=True, key=f"vc_show_{_fv}"):
            _fwd_sel.append(_fv)

    if not _merged_vc.empty and _fwd_sel:
        st.plotly_chart(_chart_vol_flows(_merged_vc, _fwd_sel), use_container_width=True)
    elif _merged_vc.empty:
        st.warning("Could not load market history for vol-control computation.")
    else:
        st.info("Select at least one vol scenario above.")

    st.divider()

    # ── Multi-market scenario flows table ─────────────────────────────────
    st.markdown("#### Expected Vol-Control Flows by Market — Scenario Table ($MM)")
    st.caption(
        "Flow = change in equity allocation × market AUM weight. "
        "Positive = buying / re-risking. Negative = selling / de-risking. "
        "**Flat** = 5 days of zero returns (vol decays → re-risk). "
        "**Up/Down** = 5-day ±Nσ shock then EWMA recomputed."
    )

    if not _flows_tbl_vc.empty:
        def _color_flow(val):
            try:
                v = float(val)
                if v > 50:   return "background-color:#14532d;color:#bbf7d0"
                if v > 0:    return "background-color:#052e16;color:#86efac"
                if v < -50:  return "background-color:#7f1d1d;color:#fecaca"
                if v < 0:    return "background-color:#431407;color:#fca5a5"
            except Exception:
                pass
            return ""

        _tbl_disp = _flows_tbl_vc.copy()
        for _col in _tbl_disp.columns:
            _tbl_disp[_col] = _tbl_disp[_col].map(
                lambda x: f"{int(x):+,d}" if pd.notna(x) and x != 0 else "—"
            )
        st.dataframe(
            _flows_tbl_vc.style.map(_color_flow),
            use_container_width=True,
        )

        with st.expander("📖 Why flows differ across markets"):
            st.markdown("""
Each market has its own:
- **Realised volatility** (EWMA 30d + 90d) — higher-vol markets have lower exposure
- **Current exposure** — exposure = target_vol / vol_used, capped at 1.5×
- **AUM weight** — flows scale with the assumed allocation weight

**Scenario mechanics:**

| Scenario | What happens to vol | Direction |
|---|---|---|
| **Flat** | Old spikes roll out of EWMA → vol decays slowly | Buying (small) |
| **Up +2σ** | Large positive return raises EWMA variance | De-risk (selling) |
| **Down −2.5σ** | Large negative return spikes EWMA variance sharply | Heavy de-risk |
| **Last Week** | Realised change in exposure over past 5 days | Actual realized |
| **Last Month** | Realised change in exposure over past 21 days | Actual realized |

**Key insight:** Down moves cause *more* de-risking than up moves of equal size.
A −2.5σ shock raises the EWMA variance ~2.5× more than a +2σ shock because
the vol spike (r²) enters symmetrically, but the signal that the fund was already
short risk asymmetrically amplifies the rebalancing.
""")
    else:
        st.warning("Market data not available — check network connection.")

    st.divider()

    # ── Daily flow table (forward projections) ────────────────────────────
    if not _merged_vc.empty:
        st.markdown("#### Daily Flow Table — Forward Projections ($bn, S&P weight)")
        _daily_cols = [c for c in _merged_vc.columns if c.startswith("Daily")]
        if _daily_cols:
            st.dataframe(
                _merged_vc[_daily_cols].round(3).style.background_gradient(
                    cmap="RdYlGn", axis=None
                ),
                use_container_width=True, height=300,
            )

    # ── Methodology reference ─────────────────────────────────────────────
    with st.expander("ℹ️ Methodology — Institutional EWMA vol-control"):
        _half30_m = f"{-np.log(2)/np.log(_vc_lam30):.1f}"
        _half90_m = f"{-np.log(2)/np.log(_vc_lam90):.1f}"
        st.markdown(f"""
**Core model** *(RiskMetrics EWMA — correct recursive formulation)*

```
var_t  = (1 − λ) · r_t²  +  λ · var_{{t-1}}   ← recursive, NOT windowed
vol_t  = sqrt(var_t × 252)
vol_used = max(vol_30d, vol_90d)               ← conservative: highest wins
exposure = (target_vol / vol_used).clip(1.5×)
flow_t   = Δ(exposure × AUM)
```

**Forward projection** *(gradual convergence, not instant jump)*

```
var_{{T+k}} = (1 − λ) · (σ_fwd/√252)²  +  λ · var_{{T+k-1}}
```

Vol converges to σ_fwd at rate (1−λ) per day. Half-lives: λ₃₀={_vc_lam30} → **{_half30_m}d**, λ₉₀={_vc_lam90} → **{_half90_m}d**.

**What was wrong before:** The previous implementation used `w /= w.sum()` to normalise
EWMA weights over a fixed window. This is a *weighted moving average*, not a true EWMA —
it changes the effective λ and destroys the convergence property of forward projections.

**Data:** Yahoo Finance equity indices (cash) as futures proxies.
Institutional deployment would use CME/Eurex front-month futures via Bloomberg or Databento.

| Parameter | Value |
|---|---|
| AUM | ${_vc_aum/1e9:.0f}bn |
| Target vol | {_vc_tvol:.1%} |
| EWMA λ (30d) | {_vc_lam30} → half-life {_half30_m}d |
| EWMA λ (90d) | {_vc_lam90} → half-life {_half90_m}d |
| Vol used | max(30d EWMA, 90d EWMA) |
| Max leverage | {VC_MAX_LEV}× |
| Forward scenarios | {", ".join(f"{v:.0%}" for v in _fwd_vols_input)} |
| Horizon | {_vc_fwd_days} business days |
        """)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — ALERT SETTINGS  (admin only)
# ─────────────────────────────────────────────────────────────────────────────
if is_admin() and len(tabs) > 3:
    with tabs[3]:
        st.subheader("📧 CTA Alert Configuration")
        st.caption(
            "**Mon/Fri** schedule: Monday = Week Ahead setup · Friday = Week in Review scorecard. "
            "Charts marked ⭐ are always included."
        )

        cfg = _load_alert_cfg()
        acol1, acol2 = st.columns([1.3, 1])

        with acol1:
            st.markdown("**Recipients**")
            raw_recip = st.text_area("One email per line",
                                     value="\n".join(cfg["recipients"]), height=90,
                                     key="cta_recip")
            cfg["recipients"] = [r.strip() for r in raw_recip.splitlines() if r.strip()]

            st.markdown("**Charts to attach** (appended after the weekly narrative)")
            new_charts = []
            left_col, right_col = st.columns(2)
            for j, (cid, label) in enumerate(AVAILABLE_CHARTS.items()):
                col = left_col if j % 2 == 0 else right_col
                if col.checkbox(label, value=(cid in cfg["charts"]), key=f"achart_{cid}"):
                    new_charts.append(cid)
            cfg["charts"] = new_charts

            st.markdown("**Schedule**")
            _freq_opts = ["mon_fri", "daily", "weekly", "off"]
            cfg["schedule"] = st.selectbox(
                "Frequency",
                _freq_opts,
                index=_freq_opts.index(cfg.get("schedule", "mon_fri"))
                      if cfg.get("schedule", "mon_fri") in _freq_opts else 0,
                key="cta_schedule",
                help="mon_fri: Monday = Week Ahead · Friday = Week Recap",
            )

        with acol2:
            st.markdown("**Gmail credentials**")
            st.caption("Uses GMAIL_USER / GMAIL_APP_PASSWORD from secrets.toml by default.")
            _def_user = _secret("GMAIL_USER", os.getenv("SMTP_USER", ""))
            _def_pass = _secret("GMAIL_APP_PASSWORD", os.getenv("SMTP_PASS", ""))
            smtp_user = st.text_input("Gmail user", value=_def_user, key="cta_smtp_user")
            smtp_pass = st.text_input("Gmail app password", value=_def_pass,
                                      type="password", key="cta_smtp_pass",
                                      help="Use an App Password, not your Google account password")

            st.markdown(f"Last sent: `{cfg.get('last_sent') or 'Never'}`")
            st.divider()

            if st.button("💾 Save", use_container_width=True, type="primary", key="cta_save"):
                _save_alert_cfg(cfg)
                st.success("Saved!")

            # ── Determine which body to preview / send ────────────────────
            _today_wd = datetime.now().weekday()  # 0=Mon … 4=Fri
            _is_friday = _today_wd == 4
            _email_type = "Friday Recap" if _is_friday else "Monday Setup"

            if st.button(f"📤 Send {_email_type}", use_container_width=True, key="cta_send",
                         help="Sends Monday Week Ahead on Mon–Thu; Friday Week Recap on Fri"):
                if not cfg["recipients"]:
                    st.error("Add at least one recipient.")
                elif not smtp_user or not smtp_pass:
                    st.error("Gmail credentials required (use an App Password).")
                else:
                    with st.spinner(f"Building {_email_type} and sending…"):
                        try:
                            # Build the narrative HTML
                            if _is_friday:
                                html_narrative = _build_friday_html(
                                    sr_df, mkt_p, pos_hist, ref_price)
                                subj_label = "Week Recap"
                            else:
                                html_narrative = _build_monday_html(
                                    sr_df, flows_df, pos_hist, ref_price)
                                subj_label = "Week Ahead"

                            from datetime import date as _date, timedelta as _td
                            _mon = _date.today() - _td(days=_date.today().weekday())
                            subject = (
                                f"📊 CTA Positioning — Macro Manv · "
                                f"{_mon.strftime('%-d %b %Y')} · {subj_label}"
                            )

                            # Build charts (MPL)
                            imgs = {}
                            for cid in cfg["charts"]:
                                fn = MPL_BUILD_FNS.get(cid)
                                if fn:
                                    mf = fn(sr_df)
                                    imgs[cid] = _mpl_fig_bytes(mf)
                                    plt.close(mf)

                            # Append chart images to the HTML
                            if imgs:
                                chart_html = "".join(
                                    f"<h3 style='color:#e8eef9;font-size:13px'>"
                                    f"{AVAILABLE_CHARTS.get(cid,'').replace(' ⭐','')}</h3>"
                                    f"<img src='cid:{cid}' style='max-width:680px;border-radius:8px'><br>"
                                    for cid in imgs
                                )
                                # Inject before </body>
                                html_narrative = html_narrative.replace(
                                    "</body></html>",
                                    chart_html + "</body></html>",
                                )

                            msg = MIMEMultipart("related")
                            msg["Subject"] = subject
                            msg["From"]    = smtp_user
                            msg["To"]      = ", ".join(cfg["recipients"])
                            msg.attach(MIMEText(html_narrative, "html"))
                            for cid, img_b in imgs.items():
                                img = MIMEImage(img_b)
                                img.add_header("Content-ID", f"<{cid}>")
                                msg.attach(img)

                            # Use SSL on 465 (same as main alerts page)
                            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
                                server.login(smtp_user, smtp_pass)
                                server.sendmail(smtp_user, cfg["recipients"], msg.as_string())

                            cfg["last_sent"] = datetime.now().isoformat()
                            _save_alert_cfg(cfg)
                            st.success(f"✅ Sent {_email_type} to {', '.join(cfg['recipients'])}")
                        except Exception as e:
                            st.error(f"Send failed: {e}")

            st.divider()
            st.markdown("**Preview email**")
            _prev_col1, _prev_col2 = st.columns(2)
            if _prev_col1.button("📋 Preview Monday Setup", use_container_width=True, key="prev_mon"):
                html_preview = _build_monday_html(sr_df, flows_df, pos_hist, ref_price)
                st.components.v1.html(html_preview, height=600, scrolling=True)
            if _prev_col2.button("📋 Preview Friday Recap", use_container_width=True, key="prev_fri"):
                html_preview = _build_friday_html(sr_df, mkt_p, pos_hist, ref_price)
                st.components.v1.html(html_preview, height=600, scrolling=True)

            st.markdown("**Chart previews**")
            for cid in DEFAULT_ALERT_CHARTS:
                fn = MPL_BUILD_FNS.get(cid)
                if fn:
                    with st.expander(AVAILABLE_CHARTS.get(cid, cid)):
                        mf = fn(sr_df)
                        st.pyplot(mf)
                        plt.close(mf)
