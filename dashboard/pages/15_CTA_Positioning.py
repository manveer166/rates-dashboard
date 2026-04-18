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
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import get_master_df, init_session_state, is_admin, password_gate

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="CTA Positioning · Rates Dashboard",
                   page_icon="📊", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="CTA Positioning")

# ── Model constants ───────────────────────────────────────────────────────────
CTA_TOTAL_BN   = 300
CTA_MAX_BN     = 80
CTA_LOOKBACKS  = [21, 63, 252]
CTA_BLEND_WTS  = [0.40, 0.35, 0.25]
CTA_VOL_WIN    = 63
CTA_PROJ_DAYS  = 130
CTA_VOL_WIN_SC = 21
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
    s = d["Close"].squeeze().dropna()
    s.index = pd.to_datetime(s.index.date)
    return s

@st.cache_data(ttl=3600, show_spinner="Loading market data…")
def _load_markets():
    out = {}
    for name, (ticker, _) in MKTS.items():
        try:
            d = yf.download(ticker, start="2019-01-01", auto_adjust=True, progress=False)
            s = d["Close"].squeeze().dropna()
            s.index = pd.to_datetime(s.index.date)
            out[name] = s if len(s) > 100 else None
        except Exception:
            out[name] = None
    return out

@st.cache_data(ttl=3600, show_spinner="Loading risk parity data…")
def _load_rp():
    eq = yf.download("^GSPC", start="2017-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    bd = yf.download("TLT",   start="2017-01-01", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    eq.index = pd.to_datetime(eq.index.date)
    bd.index = pd.to_datetime(bd.index.date)
    return eq, bd

@st.cache_data(ttl=3600, show_spinner="Loading vol control data…")
def _load_vol_control():
    aum=300e9; target_vol=0.12; lambda_30=0.94; lambda_90=0.97
    periods_fwd=80; tdpy=252; forward_vols=[0.20, 0.18, 0.16, 0.14, 0.12]
    sp = yf.Ticker("^GSPC")
    df = sp.history(period="1y", auto_adjust=True)[["Close"]]
    df["Return"] = np.log(df["Close"] / df["Close"].shift(1))
    df = df.reset_index()

    def ewma_v(returns, decay, window):
        w = np.array([(1-decay)*decay**i for i in range(window)][::-1])
        w /= w.sum()
        out = []
        for i in range(window, len(returns)):
            out.append(np.sqrt(tdpy * np.sum(w * returns[i-window:i]**2)))
        return [np.nan]*window + out

    rets = df["Return"].fillna(0).values
    df["vol_30"]  = ewma_v(rets, lambda_30, 30)
    df["vol_90"]  = ewma_v(rets, lambda_90, 90)
    df["vol_used"] = df[["vol_30","vol_90"]].max(axis=1)

    tz    = df["Date"].dt.tz
    today = pd.Timestamp.now(tz=tz).normalize()

    def ewma_val(w_rets, decay):
        w = np.array([(1-decay)*decay**j for j in range(len(w_rets))][::-1])
        w /= w.sum()
        return np.sqrt(tdpy * np.sum(w * w_rets**2))

    results = []
    for fv in forward_vols:
        fdv = fv / np.sqrt(tdpy)
        future_dates = pd.date_range(df["Date"].iloc[-1] + pd.Timedelta(days=1), periods=periods_fwd, freq="B")
        sim  = np.full(periods_fwd, fdv)
        cr30 = np.concatenate([rets[-30:], sim])
        cr90 = np.concatenate([rets[-90:], sim])
        fv30 = [ewma_val(cr30[i-1:i-1+30], lambda_30) for i in range(1, periods_fwd+1)]
        fv90 = [ewma_val(cr90[i-1:i-1+90], lambda_90) for i in range(1, periods_fwd+1)]
        fvdf = pd.DataFrame({"Date": future_dates, "vol_30": fv30, "vol_90": fv90})
        fvdf["vol_used"] = fvdf[["vol_30","vol_90"]].max(axis=1)
        cdf  = pd.concat([df[["Date","vol_used"]], fvdf[["Date","vol_used"]]], ignore_index=True)
        cdf["equity_weight"]     = (target_vol / cdf["vol_used"]).clip(upper=1.5)
        cdf["vol_controlled_AUM"] = cdf["equity_weight"] * aum
        cdf2 = cdf[cdf["Date"].dt.normalize() >= today].copy()
        cdf2["daily_flow"]      = cdf2["vol_controlled_AUM"].diff()
        cdf2["cumulative_flow"] = cdf2["daily_flow"].cumsum()
        ft = cdf2[["Date","daily_flow","cumulative_flow"]].copy()
        ft["Date"] = ft["Date"].dt.date
        ft["daily_flow"]      = (ft["daily_flow"]/1e9).round(3)
        ft["cumulative_flow"] = (ft["cumulative_flow"]/1e9).round(3)
        ft.columns = ["Date", f"Daily Flow ({fv})", f"Cumulative Flow ({fv})"]
        results.append(ft.set_index("Date"))

    merged = reduce(lambda l, r: pd.merge(l, r, on="Date", how="outer"), results)
    return df, merged

# ══════════════════════════════════════════════════════════════════════════════
# CTA MODEL
# ══════════════════════════════════════════════════════════════════════════════
def _cta_signal(prices):
    lr = np.log(prices / prices.shift(1))
    rv = lr.rolling(CTA_VOL_WIN).std() * np.sqrt(252)
    b  = pd.Series(0.0, index=prices.index)
    for lb, w in zip(CTA_LOOKBACKS, CTA_BLEND_WTS):
        n = (np.log(prices / prices.shift(lb)) / np.sqrt(lb / 252)) / (rv + 1e-8)
        b += w * np.tanh(n / 2)
    return b

def _sig_to_pos(sig):
    return (sig * CTA_MAX_BN).clip(-CTA_MAX_BN * 0.75, CTA_MAX_BN)

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
        cur = float(_sig_to_pos(_cta_signal(p)).iloc[-1])
        old = float(_sig_to_pos(_cta_signal(p.iloc[:-hist_days])).iloc[-1])
        return round((cur - old) * 1000)
    cp  = float(_sig_to_pos(_cta_signal(p)).iloc[-1])
    dv  = rets.iloc[-CTA_VOL_WIN_SC:].std()
    pv  = p.iloc[-1] * np.exp(np.cumsum(np.full(fwd_days, z * dv)))
    pi  = pd.date_range(p.index[-1] + pd.Timedelta(days=1), periods=fwd_days, freq="B")
    ext = pd.concat([p, pd.Series(pv, index=pi)])
    pp  = float(_sig_to_pos(_cta_signal(ext)).iloc[-1])
    return round((pp - cp) * 1000)

@st.cache_data(ttl=3600, show_spinner="Computing CTA signals…")
def _compute_cta(_sp, _mkt_prices):
    pos_hist = _sig_to_pos(_cta_signal(_sp))
    rets     = np.log(_sp / _sp.shift(1)).dropna()
    sp_alloc = MKTS["S&P 500 E-mini"][1]
    sp_hist_w = (pos_hist * sp_alloc).iloc[-126:]

    proj = {}
    for name, z in CTA_SCENARIOS.items():
        ext = pd.concat([_sp, _project_price(_sp, rets, CTA_PROJ_DAYS, z)])
        proj[name] = (_sig_to_pos(_cta_signal(ext)) * sp_alloc).iloc[-CTA_PROJ_DAYS:]

    flow_cols = [
        ("1 Week","Flat",0), ("1 Week","Up 2 STD",2.0), ("1 Week","Down 2.5 STD",-2.5),
        ("1 Month","Flat",0), ("1 Month","Up 2 STD",2.0), ("1 Month","Down 2.5 STD",-2.5),
        ("Sim. Realized","Last Week",None), ("Sim. Realized","Last Month",None),
    ]
    days_m = {"1 Week": 5, "1 Month": 21}
    hist_m = {"Last Week": 5, "Last Month": 21}
    rows = []
    for mkt, (_, w) in MKTS.items():
        p   = _mkt_prices.get(mkt); abn = CTA_TOTAL_BN * w; row = {"Market": mkt}
        for period, label, z in flow_cols:
            key = f"{period}|{label}"
            row[key] = (_mkt_flow(p, abn, None, None, hist_days=hist_m[label])
                        if z is None else _mkt_flow(p, abn, days_m[period], z))
        rows.append(row)
    flows_df = pd.DataFrame(rows).set_index("Market")
    tot = flows_df.sum(numeric_only=True); tot.name = "Totals"
    flows_df = pd.concat([flows_df, tot.to_frame().T])

    sr_rows = []
    for mkt, (_, w) in MKTS.items():
        p = _mkt_prices.get(mkt)
        if p is None or len(p) < 100: continue
        r = np.log(p / p.shift(1)).dropna()
        sig     = float(_cta_signal(p).iloc[-1])
        f1w     = _mkt_flow(p, CTA_TOTAL_BN * w, 5, 0.0)
        ann_ret = float(np.log(p.iloc[-1] / p.iloc[-21]) * 12)
        ann_vol = float(r.iloc[-63:].std() * np.sqrt(252))
        sharpe  = ann_ret / (ann_vol + 1e-8)
        sr_rows.append({"Market": mkt, "Signal": sig, "AnnReturn": ann_ret,
                         "AnnVol": ann_vol, "Sharpe": sharpe,
                         "Flow1W": f1w if (f1w is not None and not np.isnan(f1w)) else 0})
    sr_df = pd.DataFrame(sr_rows)
    mxf   = sr_df["Flow1W"].abs().max()
    sr_df["BubbleSize"] = (sr_df["Flow1W"].abs() / (mxf + 1e-8)) * 50 + 8
    sr_df["Direction"]  = sr_df["Flow1W"].apply(lambda x: "Buying" if x >= 0 else "Selling")

    plot_start = pd.Timestamp("2019-01-01")
    syst       = pos_hist[pos_hist.index >= plot_start]

    return pos_hist, sp_hist_w, proj, flows_df, sr_df, syst

@st.cache_data(ttl=3600, show_spinner="Computing risk parity…")
def _compute_rp(_eq, _bd):
    ev  = np.log(_eq / _eq.shift(1)).rolling(63).std() * np.sqrt(252)
    bv  = np.log(_bd / _bd.shift(1)).rolling(63).std() * np.sqrt(252)
    idx = ev.dropna().index.intersection(bv.dropna().index)
    bond_exp = (0.10 * 2.5 / bv.loc[idx] * 100).clip(40, 170)
    eq_exp   = (0.10 / ev.loc[idx] * 100).clip(6, 60)
    def pr(s): return int(s.rank(pct=True).iloc[-1] * 100)
    cb, ce = float(bond_exp.iloc[-1]), float(eq_exp.iloc[-1])
    bond_lbl = f"Bnd Exp @ {cb:.0f}% or<br>{pr(bond_exp)}%-tile vs 1Y<br>{pr(bond_exp)}%-tile vs 5Y"
    eq_lbl   = f"Eq Exp @ {ce:.0f}% or<br>{pr(eq_exp)}%-tile vs 1Y<br>{pr(eq_exp)}%-tile vs 5Y"
    return bond_exp, eq_exp, cb, ce, bond_lbl, eq_lbl

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
        dc, cc = f"Daily Flow ({fv})", f"Cumulative Flow ({fv})"
        if dc in merged.columns:
            fig.add_trace(go.Scatter(x=merged.index, y=merged[dc], fill="tozeroy",
                fillcolor=cols[i], line=dict(color=cols[i]),
                name=f"Daily {fv}", legendgroup=f"g{i}"), row=1, col=1)
        if cc in merged.columns:
            fig.add_trace(go.Scatter(x=merged.index, y=merged[cc],
                line=dict(color=cols[i], width=2), name=f"Cum. {fv}",
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
# LOAD DATA
# ══════════════════════════════════════════════════════════════════════════════
sp      = _load_sp500()
mkt_p   = _load_markets()
rp_eq, rp_bd = _load_rp()
_, merged_vc  = _load_vol_control()

pos_hist, sp_hist_w, proj, flows_df, sr_df, syst = _compute_cta(sp, mkt_p)
bond_exp, eq_exp, curr_bond, curr_eq, bond_lbl, eq_lbl = _compute_rp(rp_eq, rp_bd)
ref_price = float(sp.iloc[-1])

# ══════════════════════════════════════════════════════════════════════════════
# PAGE HEADER + KPI ROW
# ══════════════════════════════════════════════════════════════════════════════
st.title("📊 CTA & Systematic Fund Positioning")
st.markdown(
    '<p style="color:var(--c-text-2);font-size:15px;margin-top:-4px;">'
    "CTA trend model · Risk parity exposures · Vol-controlled fund flows"
    "</p>",
    unsafe_allow_html=True,
)
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
tab_labels = ["📈 CTA Positioning", "⚙️ Vol Control Strategies"]
if is_admin():
    tab_labels.append("📧 Alert Settings")
tabs = st.tabs(tab_labels)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — CTA POSITIONING
# ─────────────────────────────────────────────────────────────────────────────
with tabs[0]:
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
with tabs[1]:
    st.subheader("⚙️ Vol-Controlled Fund Flows")
    st.caption("EWMA 30/90-day vol projections under different forward vol assumptions — $300bn AUM, 12% target vol.")

    vc1, vc2, vc3, vc4, vc5 = st.columns(5)
    fwd_sel = []
    for col, fv in zip([vc1, vc2, vc3, vc4, vc5], [0.20, 0.18, 0.16, 0.14, 0.12]):
        if col.checkbox(f"{int(fv*100)}% vol", value=True, key=f"vc_{fv}"):
            fwd_sel.append(fv)

    if fwd_sel:
        st.plotly_chart(_chart_vol_flows(merged_vc, fwd_sel), use_container_width=True)
    else:
        st.info("Select at least one vol scenario above.")

    st.markdown('<p class="section-header">Daily Flow Table</p>', unsafe_allow_html=True)
    daily_cols = [c for c in merged_vc.columns if c.startswith("Daily")]
    st.dataframe(
        merged_vc[daily_cols].style.background_gradient(cmap="RdYlGn", axis=None),
        use_container_width=True, height=280,
    )

    with st.expander("ℹ️ Methodology"):
        st.markdown("""
| Parameter | Value |
|---|---|
| AUM | $300bn (Reuters / DB estimate) |
| Target vol | 12% |
| EWMA 30-day decay (λ) | 0.94 |
| EWMA 90-day decay (λ) | 0.97 |
| Vol used | max(30d, 90d) |
| Equity weight | target_vol / vol_used, capped at 1.5× |
| Forward vol range | 12% – 20% in 2pp steps |
        """)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — ALERT SETTINGS  (admin only)
# ─────────────────────────────────────────────────────────────────────────────
if is_admin() and len(tabs) > 2:
    with tabs[2]:
        st.subheader("📧 CTA Alert Configuration")
        st.caption("Charts marked ⭐ are included by default.")

        cfg = _load_alert_cfg()
        acol1, acol2 = st.columns([1.3, 1])

        with acol1:
            st.markdown("**Recipients**")
            raw_recip = st.text_area("One email per line",
                                     value="\n".join(cfg["recipients"]), height=90,
                                     key="cta_recip")
            cfg["recipients"] = [r.strip() for r in raw_recip.splitlines() if r.strip()]

            st.markdown("**Charts to include**")
            new_charts = []
            left_col, right_col = st.columns(2)
            for j, (cid, label) in enumerate(AVAILABLE_CHARTS.items()):
                col = left_col if j % 2 == 0 else right_col
                if col.checkbox(label, value=(cid in cfg["charts"]), key=f"achart_{cid}"):
                    new_charts.append(cid)
            cfg["charts"] = new_charts

            st.markdown("**Schedule**")
            cfg["schedule"] = st.selectbox("Frequency", ["daily", "weekly", "off"],
                index=["daily","weekly","off"].index(cfg.get("schedule","daily")),
                key="cta_schedule")

        with acol2:
            st.markdown("**SMTP Settings**")
            st.caption("Uses existing SMTP_HOST / SMTP_USER / SMTP_PASS env vars by default.")
            smtp_host = st.text_input("Host",     value=os.getenv("SMTP_HOST", "smtp.gmail.com"), key="cta_smtp_host")
            smtp_port = st.number_input("Port",   value=int(os.getenv("SMTP_PORT", "587")), key="cta_smtp_port")
            smtp_user = st.text_input("User",     value=os.getenv("SMTP_USER", ""), key="cta_smtp_user")
            smtp_pass = st.text_input("Password", value=os.getenv("SMTP_PASS", ""),
                                      type="password", key="cta_smtp_pass")

            st.markdown(f"Last sent: `{cfg.get('last_sent') or 'Never'}`")
            st.divider()

            if st.button("💾 Save", use_container_width=True, type="primary", key="cta_save"):
                _save_alert_cfg(cfg)
                st.success("Saved!")

            if st.button("📤 Send Test Alert", use_container_width=True, key="cta_send"):
                if not cfg["recipients"]:
                    st.error("Add at least one recipient.")
                elif not smtp_user or not smtp_pass:
                    st.error("SMTP credentials required.")
                else:
                    with st.spinner("Generating charts and sending…"):
                        try:
                            imgs = {}
                            for cid in cfg["charts"]:
                                fn = MPL_BUILD_FNS.get(cid)
                                if fn:
                                    mf = fn(sr_df)
                                    imgs[cid] = _mpl_fig_bytes(mf)
                                    plt.close(mf)

                            html_parts = [
                                "<html><body style='font-family:Inter,Arial,sans-serif;"
                                "background:#0a1628;color:#e8eef9;padding:24px'>",
                                f"<h2 style='color:#4fc3f7'>📊 CTA Positioning Alert</h2>",
                                f"<p style='color:#94a8c9'>{datetime.now().strftime('%A, %d %B %Y %H:%M')}</p>"
                                f"<p>S&amp;P 500: <b>{ref_price:,.0f}</b> &nbsp;|&nbsp; "
                                f"CTA Position: <b>{pos_hist.iloc[-1]:.1f}bn</b></p><hr>",
                            ]
                            for cid in cfg["charts"]:
                                lbl = AVAILABLE_CHARTS.get(cid, cid).replace(" ⭐", "")
                                html_parts.append(f"<h3 style='color:#e8eef9'>{lbl}</h3>")
                                if cid in imgs:
                                    html_parts.append(f"<img src='cid:{cid}' "
                                                      f"style='max-width:680px;border-radius:8px'><br><br>")
                            html_parts.append("</body></html>")

                            msg = MIMEMultipart("related")
                            msg["Subject"] = f"📊 CTA Alert — {datetime.now().strftime('%d %b %Y')}"
                            msg["From"]    = smtp_user
                            msg["To"]      = ", ".join(cfg["recipients"])
                            msg.attach(MIMEText("".join(html_parts), "html"))
                            for cid, img_b in imgs.items():
                                img = MIMEImage(img_b)
                                img.add_header("Content-ID", f"<{cid}>")
                                msg.attach(img)

                            with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
                                server.starttls()
                                server.login(smtp_user, smtp_pass)
                                server.sendmail(smtp_user, cfg["recipients"], msg.as_string())

                            cfg["last_sent"] = datetime.now().isoformat()
                            _save_alert_cfg(cfg)
                            st.success(f"Sent to {', '.join(cfg['recipients'])}")
                        except Exception as e:
                            st.error(f"Send failed: {e}")

            st.divider()
            st.markdown("**Preview default charts**")
            for cid in DEFAULT_ALERT_CHARTS:
                fn = MPL_BUILD_FNS.get(cid)
                if fn:
                    with st.expander(AVAILABLE_CHARTS.get(cid, cid)):
                        mf = fn(sr_df)
                        st.pyplot(mf)
                        plt.close(mf)
