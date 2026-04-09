"""
13_Trade_Tracker.py — Historical trade idea tracker with P&L tracking.

Log trade ideas from the scanner, track entry/exit levels, and compute P&L.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import csv
import json
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import PLOTLY_THEME
from dashboard.state import password_gate, get_master_df, init_session_state
from dashboard.components.controls import render_sidebar_controls

st.set_page_config(page_title="Trade Tracker", page_icon="📋", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()

st.title("📋 Trade Tracker")
st.caption("Log trade ideas, track P&L, and build your track record.")

TRADES_FILE = Path(__file__).parent.parent.parent / "data" / "trade_log.csv"
TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)

# ── Load / save trades ────────────────────────────────────────────────────

def _load_trades():
    if not TRADES_FILE.exists():
        return pd.DataFrame(columns=[
            "id", "date", "trade", "type", "direction", "entry_level",
            "exit_level", "exit_date", "status", "pnl_bps", "notes",
        ])
    return pd.read_csv(TRADES_FILE, dtype={"id": str})


def _save_trades(df):
    df.to_csv(TRADES_FILE, index=False)


def _next_id(df):
    if df.empty:
        return "T001"
    nums = df["id"].str.extract(r"T(\d+)").astype(float).max().values[0]
    return f"T{int(nums)+1:03d}"


trades = _load_trades()

# ── Build trade catalog with current levels from market data ──────────────
fi = __import__("fixed_income")
TY = fi.TENOR_YEARS
_mdf = get_master_df()
ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
_avail = [t for t in ALL_TENORS if t in _mdf.columns]
_rdf = _mdf[_avail].ffill(limit=3).dropna(how="all") if _avail else pd.DataFrame()
_curve = {}
if not _rdf.empty:
    _last = _rdf.iloc[-1]
    for t in _avail:
        if not pd.isna(_last[t]):
            _curve[t] = float(_last[t])

def _dv01_local(t):
    return fi.approx_dv01(TY.get(t, 10.0), _curve.get(t, 4.0))

# Build all trade names + current levels
_trade_catalog = {}  # name -> {"type": ..., "level": ...}

# Outrights
for t in _avail:
    if t in _curve:
        _trade_catalog[f"Rcv {t}"] = {"type": "Outright", "level": round(_curve[t], 4)}

# Curves
for i, t1 in enumerate(_avail):
    for t2 in _avail[i+1:]:
        if t1 in _curve and t2 in _curve:
            d1, d2 = _dv01_local(t1), _dv01_local(t2)
            ratio = d2 / d1 if d1 > 0 else 1.0
            if not _rdf.empty:
                lvl = float((_rdf[t2].iloc[-1] - ratio * _rdf[t1].iloc[-1]) * 100)
                _trade_catalog[f"Rcv {t1}/{t2}"] = {"type": "Curve", "level": round(lvl, 2)}

# Flies
for i, w1 in enumerate(_avail):
    for j, belly in enumerate(_avail[i+1:], i+1):
        for w2 in _avail[j+1:]:
            if all(x in _curve for x in [w1, belly, w2]):
                dw1, db, dw2 = _dv01_local(w1), _dv01_local(belly), _dv01_local(w2)
                wb = 2.0 * (dw1/db) if db > 0 else 2.0
                ww2 = dw1/dw2 if dw2 > 0 else 1.0
                if not _rdf.empty:
                    lvl = float((wb * _rdf[belly].iloc[-1] - _rdf[w1].iloc[-1] - ww2 * _rdf[w2].iloc[-1]) * 100)
                    _trade_catalog[f"Rcv {w1}/{belly}/{w2}"] = {"type": "Fly", "level": round(lvl, 2)}

_catalog_names = ["(custom)"] + sorted(_trade_catalog.keys())

st.divider()

# ── New trade entry ───────────────────────────────────────────────────────
st.subheader("Log New Trade")

# Trade picker (outside form so it can update the level dynamically)
pick_col1, pick_col2 = st.columns([2, 1])
with pick_col1:
    selected_trade = st.selectbox("Pick a trade", _catalog_names, key="trade_picker")
with pick_col2:
    direction = st.selectbox("Direction", ["Receive", "Pay"], key="trade_dir")

# Resolve defaults from catalog
if selected_trade != "(custom)" and selected_trade in _trade_catalog:
    _info = _trade_catalog[selected_trade]
    _default_name = selected_trade
    _default_type = _info["type"]
    _default_level = _info["level"]
else:
    _default_name = ""
    _default_type = "Outright"
    _default_level = 0.0

with st.form("new_trade", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        trade_name = st.text_input("Trade", value=_default_name,
                                    placeholder="e.g. Rcv 2Y/10Y")
        type_options = ["Outright", "Curve", "Curve*", "Fly", "Fly*"]
        type_idx = type_options.index(_default_type) if _default_type in type_options else 0
        trade_type = st.selectbox("Type", type_options, index=type_idx)
    with c2:
        entry_level = st.number_input("Entry Level (current shown, editable)",
                                       value=_default_level, format="%.4f", step=0.01)
    with c3:
        entry_date = st.date_input("Entry Date", value=datetime.today())
        notes = st.text_input("Notes", placeholder="Rationale, target, stop...")

    if st.form_submit_button("Add Trade", use_container_width=True):
        final_name = trade_name.strip() or selected_trade
        if final_name and final_name != "(custom)":
            new_row = pd.DataFrame([{
                "id": _next_id(trades),
                "date": str(entry_date),
                "trade": final_name,
                "type": trade_type,
                "direction": direction,
                "entry_level": entry_level,
                "exit_level": np.nan,
                "exit_date": "",
                "status": "Open",
                "pnl_bps": np.nan,
                "notes": notes,
            }])
            trades = pd.concat([trades, new_row], ignore_index=True)
            _save_trades(trades)
            st.success(f"Trade {new_row['id'].iloc[0]} logged: {direction} {final_name} @ {entry_level:.4f}")
            st.rerun()
        else:
            st.error("Select a trade or type a custom name.")

st.divider()

# ── Open trades ───────────────────────────────────────────────────────────
st.subheader("Open Trades")

open_trades = trades[trades["status"] == "Open"]
if not open_trades.empty:
    display_rows = []
    for _, t in open_trades.iterrows():
        row = t.to_dict()
        # Look up current level from catalog
        trade_key = row["trade"]
        if trade_key in _trade_catalog:
            curr = _trade_catalog[trade_key]["level"]
            row["current"] = curr
            entry = float(row["entry_level"]) if not pd.isna(row["entry_level"]) else 0
            d_mult = 1.0 if row["direction"] == "Receive" else -1.0
            row["unreal_bps"] = round((entry - curr) * 100 * d_mult, 1) if row["type"] == "Outright" \
                else round((entry - curr) * d_mult, 1)
        else:
            row["current"] = np.nan
            row["unreal_bps"] = np.nan
        display_rows.append(row)

    open_df = pd.DataFrame(display_rows)
    display_cols = ["id", "date", "trade", "type", "direction", "entry_level", "current", "unreal_bps", "notes"]
    display_cols = [c for c in display_cols if c in open_df.columns]
    st.dataframe(open_df[display_cols], use_container_width=True, hide_index=True)

    # Close trade form
    with st.expander("Close a Trade"):
        if not open_df.empty:
            with st.form("close_trade"):
                close_id = st.selectbox("Trade ID", open_df["id"].tolist())
                exit_level = st.number_input("Exit Level", format="%.4f", step=0.01, key="exit_lvl")
                exit_date = st.date_input("Exit Date", value=datetime.today(), key="exit_dt")
                if st.form_submit_button("Close Trade"):
                    idx = trades[trades["id"] == close_id].index
                    if len(idx):
                        i = idx[0]
                        entry = float(trades.loc[i, "entry_level"])
                        direction_mult = 1.0 if trades.loc[i, "direction"] == "Receive" else -1.0
                        # For outrights: P&L in bps = (entry - exit) * 100 * direction
                        # (receiver profits when rates fall)
                        pnl = (entry - exit_level) * 100 * direction_mult
                        trades.loc[i, "exit_level"] = exit_level
                        trades.loc[i, "exit_date"] = str(exit_date)
                        trades.loc[i, "status"] = "Closed"
                        trades.loc[i, "pnl_bps"] = round(pnl, 1)
                        _save_trades(trades)
                        st.success(f"Closed {close_id}: P&L = {pnl:+.1f} bps")
                        st.rerun()
else:
    st.info("No open trades. Use the form above to log a trade idea.")

st.divider()

# ── Closed trades & P&L ──────────────────────────────────────────────────
st.subheader("Closed Trades & Track Record")

closed = trades[trades["status"] == "Closed"].copy()
if not closed.empty:
    closed["pnl_bps"] = pd.to_numeric(closed["pnl_bps"], errors="coerce")

    # Summary metrics
    m1, m2, m3, m4 = st.columns(4)
    total_pnl = closed["pnl_bps"].sum()
    win_rate = (closed["pnl_bps"] > 0).mean() * 100
    avg_pnl = closed["pnl_bps"].mean()
    best = closed["pnl_bps"].max()
    worst = closed["pnl_bps"].min()

    m1.metric("Total P&L", f"{total_pnl:+.0f} bps")
    m2.metric("Win Rate", f"{win_rate:.0f}%")
    m3.metric("Avg P&L", f"{avg_pnl:+.1f} bps")
    m4.metric("Best / Worst", f"{best:+.0f} / {worst:+.0f}")

    # P&L chart
    closed_sorted = closed.sort_values("exit_date")
    closed_sorted["cumulative_pnl"] = closed_sorted["pnl_bps"].cumsum()

    fig = go.Figure()
    # Bar chart of individual P&L
    colors = ["#66bb6a" if v > 0 else "#ef5350" for v in closed_sorted["pnl_bps"]]
    fig.add_trace(go.Bar(
        x=closed_sorted["trade"] + " (" + closed_sorted["id"] + ")",
        y=closed_sorted["pnl_bps"],
        marker_color=colors,
        name="P&L",
        opacity=0.7,
    ))
    # Cumulative line
    fig.add_trace(go.Scatter(
        x=closed_sorted["trade"] + " (" + closed_sorted["id"] + ")",
        y=closed_sorted["cumulative_pnl"],
        mode="lines+markers",
        line=dict(color="#4fc3f7", width=2.5),
        marker=dict(size=6),
        name="Cumulative",
        yaxis="y2",
    ))
    fig.update_layout(
        template=PLOTLY_THEME,
        title="Trade P&L History",
        yaxis_title="P&L (bps)",
        yaxis2=dict(title="Cumulative (bps)", overlaying="y", side="right"),
        height=400,
        showlegend=True,
        legend=dict(orientation="h", y=1.1),
        margin=dict(l=50, r=50, t=60, b=80),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Full table
    show_cols = ["id", "date", "exit_date", "trade", "type", "direction",
                 "entry_level", "exit_level", "pnl_bps", "notes"]
    disp = closed[show_cols].copy()
    styler = disp.style.format({"entry_level": "{:.4f}", "exit_level": "{:.4f}", "pnl_bps": "{:+.1f}"},
                                na_rep="—")
    st.dataframe(styler, use_container_width=True, hide_index=True)

    # CSV export
    csv_data = closed.to_csv(index=False).encode("utf-8")
    st.download_button("Export Trade Log (CSV)", csv_data, "trade_log_export.csv", "text/csv")
else:
    st.info("No closed trades yet. Close an open trade to start building your track record.")
