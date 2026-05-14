"""Page 42 — Watchlist.

Pinned trades you want to track. Each pin captures the structure + the
level at pin time; the page computes live PnL since pin and renders
each as a signal card.

Pin a trade by typing it here directly, or via the Pin button on the
Scanner (when wired). Pins persist in data/watchlist.json.
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.components.signal_card import render_signal_card
from dashboard.components.watchlist import (
    list_pins, pin_trade, unpin, update_note,
)
from dashboard.state import get_master_df, init_session_state, password_gate

st.set_page_config(page_title="Watchlist", page_icon="📌", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Watchlist")

st.title("📌 Watchlist")
st.caption(
    "Pinned trades with live PnL since pin. Drop a trade in below or use "
    "the Pin button on the Scanner."
)
st.divider()

df = get_master_df()
if df.empty:
    st.error("No market data — refresh the cache.")
    st.stop()

ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]


# ── Helpers: parse trade str → level + name ──────────────────────────────
def _level_at(row, type_: str, tenors: list[str]) -> float | None:
    try:
        if type_ == "Outright":
            return float(row[tenors[0]])
        if type_ == "Curve":
            return float(row[tenors[1]] - row[tenors[0]])
        return float(2 * row[tenors[1]] - row[tenors[0]] - row[tenors[2]])
    except Exception:
        return None


def _level_history(df, type_: str, tenors: list[str]) -> pd.Series:
    if type_ == "Outright":
        return df[tenors[0]].dropna()
    if type_ == "Curve":
        return (df[tenors[1]] - df[tenors[0]]).dropna()
    return (2 * df[tenors[1]] - df[tenors[0]] - df[tenors[2]]).dropna()


def _tenors_from_trade(trade: str) -> list[str]:
    return re.findall(r"\d+[MY]", trade)


# ── Pin a new trade ───────────────────────────────────────────────────────
with st.expander("➕ Pin a new trade", expanded=False):
    pc1, pc2, pc3 = st.columns([1, 2, 1])
    with pc1:
        new_type = st.selectbox("Type", ["Outright", "Curve", "Fly"],
                                  key="pin_type")
    with pc2:
        if new_type == "Outright":
            new_tenors = [st.selectbox("Tenor", ALL_TENORS,
                                         index=ALL_TENORS.index("10Y"),
                                         key="pin_t1")]
        elif new_type == "Curve":
            ct1, ct2 = st.columns(2)
            t1 = ct1.selectbox("Short leg", ALL_TENORS,
                                index=ALL_TENORS.index("2Y"), key="pin_c1")
            t2 = ct2.selectbox("Long leg", ALL_TENORS,
                                index=ALL_TENORS.index("10Y"), key="pin_c2")
            new_tenors = [t1, t2]
        else:
            cw1, cb, cw2 = st.columns(3)
            w1 = cw1.selectbox("Front wing", ALL_TENORS,
                                index=ALL_TENORS.index("2Y"), key="pin_w1")
            b = cb.selectbox("Belly", ALL_TENORS,
                              index=ALL_TENORS.index("5Y"), key="pin_b")
            w2 = cw2.selectbox("Back wing", ALL_TENORS,
                                index=ALL_TENORS.index("10Y"), key="pin_w2")
            new_tenors = [w1, b, w2]
    with pc3:
        new_dir = st.selectbox("Direction", ["receive", "pay"],
                                key="pin_dir")
    new_note = st.text_input("Note (optional)",
                              placeholder="Why are you pinning this?",
                              key="pin_note")

    if st.button("📌 Pin", type="primary", use_container_width=True,
                  key="pin_btn"):
        last = df.dropna(how="all").iloc[-1]
        lvl = _level_at(last, new_type, new_tenors)
        if lvl is None:
            st.error("Couldn't read current level — tenor data missing.")
        else:
            prefix = "Rcv" if new_dir == "receive" else "Pay"
            trade_str = f"{prefix} {'/'.join(new_tenors)}"
            pin_trade(trade_str, new_type, new_dir, lvl, new_note)
            st.success(f"Pinned **{trade_str}** at level {lvl:.4f}.")
            st.rerun()


# ── Render existing pins ─────────────────────────────────────────────────
pins = list_pins()
if not pins:
    st.info("No pinned trades yet. Use the form above, or hit the Pin "
            "button on the Scanner (when wired).")
    st.stop()

st.subheader(f"📊 {len(pins)} pinned trade{'s' if len(pins) != 1 else ''}")

for p in sorted(pins, key=lambda x: x.get("pinned_at", ""), reverse=True):
    tenors = _tenors_from_trade(p["trade"])
    # PnL since pin
    hist = _level_history(df, p["type_"], tenors)
    if hist.empty:
        continue
    pin_date = pd.Timestamp(p["pinned_at"])
    since = hist.loc[pin_date:] if pin_date in hist.index or pin_date <= hist.index.max() else hist.tail(1)
    if since.empty:
        since = hist.tail(1)
    current_level = float(since.iloc[-1])
    sign = -1.0 if p["direction"] == "receive" else 1.0
    pnl_bps = sign * (current_level - p["pinned_level"]) * 100
    days_held = (pd.Timestamp(date.today()) - pin_date).days

    # Daily PnL for Sharpe / vol calc
    daily_pnl = sign * since.diff().dropna() * 100
    if len(daily_pnl) >= 5 and daily_pnl.std() > 0:
        sharpe = float(daily_pnl.mean() / daily_pnl.std() * (252 ** 0.5))
        vol_bps_yr = float(daily_pnl.std() * (252 ** 0.5))
        hit_rate = float((daily_pnl > 0).mean() * 100)
        cum = daily_pnl.cumsum()
        max_dd = float((cum - cum.cummax()).min())
    else:
        sharpe = vol_bps_yr = hit_rate = max_dd = 0.0

    note_html = (f"{p.get('note', '')}<br>"
                  f"<span style='color:#6a7e9e;font-size:11px'>"
                  f"Pinned at level {p['pinned_level']:.4f}  ·  "
                  f"Current {current_level:.4f}  ·  "
                  f"Δ {(current_level - p['pinned_level']) * 100:+.1f} bps</span>")

    render_signal_card(
        trade=p["trade"],
        type_=p["type_"],
        sharpe=sharpe,
        z=0.0,   # could compute regime-conditional but skip for now
        expected_return_bps_yr=pnl_bps * 365 / max(days_held, 1),
        risk_bps_yr=vol_bps_yr,
        hit_rate_pct=hit_rate,
        max_dd_bps=max_dd,
        days=days_held,
        direction=p["direction"],
        tags=[f"Pinned {p['pinned_at']}",
              f"PnL {pnl_bps:+.1f} bps",
              f"{days_held} days"],
        note=note_html,
    )

    # Unpin button
    uc1, uc2 = st.columns([4, 1])
    with uc2:
        if st.button("Unpin", key=f"unpin_{p['id']}", use_container_width=True):
            unpin(p["id"])
            st.rerun()

st.divider()
st.caption(
    "Watchlist is a personal file (data/watchlist.json) — pins persist "
    "across restarts but don't sync between users."
)
