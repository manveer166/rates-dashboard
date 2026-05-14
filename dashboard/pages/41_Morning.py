"""Page 41 — Morning Briefing.

Curated single-screen "you've just sat down at the desk, here's the day"
view. Pulls together everything important across the dashboard:

  • Top-line market state (10Y, 2s10s, VIX)
  • Signal card for today's #1 RV trade
  • Yield curve snapshot vs 1w/1m ago
  • Latest headlines + central-bank items in last 24h
  • Today's calendar events (auctions / data releases / FOMC)
  • Regime driver classification
  • Scanner top 3 in a compact card row

Designed to be the one page you check before doing anything else.
"""

from __future__ import annotations

import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import get_master_df, init_session_state, password_gate

st.set_page_config(page_title="Morning Briefing", page_icon="🌅", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Morning")

# Greeting that's hour-aware
hour = datetime.now().hour
if hour < 5:    greeting = "🌙 Working late"
elif hour < 12: greeting = "🌅 Good morning"
elif hour < 17: greeting = "☀️ Good afternoon"
else:           greeting = "🌆 Good evening"

st.title(f"{greeting} — {datetime.now().strftime('%A %d %b %Y')}")
st.caption(
    "Single-screen morning briefing: top trade, curve, headlines, calendar, "
    "and regime — pulled from across the dashboard."
)
st.divider()

df = get_master_df()
if df.empty:
    st.error("No market data — refresh the cache.")
    st.stop()


# ── Top-line metric strip ────────────────────────────────────────────────
def _delta_bps(col, days=22):
    if col not in df.columns: return None
    s = df[col].dropna()
    if len(s) < days + 1: return None
    return float(s.iloc[-1] - s.iloc[-days - 1]) * 100

def _last(col):
    if col not in df.columns: return None
    s = df[col].dropna()
    return float(s.iloc[-1]) if len(s) else None


cols = st.columns(5)
specs = [
    ("10Y UST",    "10Y",          "{:.2f}%",    "1m"),
    ("2Y UST",     "2Y",           "{:.2f}%",    "1m"),
    ("2s10s",      None,           None,         None),
    ("VIX",        "VIX",          "{:.1f}",     "1w"),
    ("HY OAS",     "HY_OAS",       "{:.2f}%",    "1m"),
]
for i, (label, col, fmt, win) in enumerate(specs):
    with cols[i]:
        if label == "2s10s":
            if "2Y" in df.columns and "10Y" in df.columns:
                now = (df["10Y"].iloc[-1] - df["2Y"].iloc[-1]) * 100
                wk_idx = max(0, len(df) - 22)
                wk = (df["10Y"].iloc[wk_idx] - df["2Y"].iloc[wk_idx]) * 100
                st.metric("2s10s slope", f"{now:+.0f} bps",
                          f"{now - wk:+.0f} bps (1m)")
            else:
                st.metric("2s10s slope", "—")
        else:
            v = _last(col)
            if v is None:
                st.metric(label, "—")
            else:
                d = _delta_bps(col, 22) if win == "1m" else _delta_bps(col, 5)
                d_label = (f"{d:+.0f} bps ({win})" if d is not None and label != "VIX"
                           else f"{d/100:+.1f} ({win})" if d is not None else None)
                st.metric(label, fmt.format(v), d_label)

st.divider()


# ── Today's top trade — hero signal card + scanner top 3 ─────────────────
st.subheader("🎯 Today's signals")

try:
    from scripts.send_alert import build_scanner
    from dashboard.components.signal_card import (
        render_signal_card, render_signal_grid,
    )

    sdf = build_scanner()
    if not sdf.empty:
        top = sdf.dropna(subset=["Sharpe"]).nlargest(4, "Sharpe")
        best = top.iloc[0]

        render_signal_card(
            trade=best["Trade"],
            type_=best["Type"],
            sharpe=float(best["Sharpe"]),
            z=float(best["Z"]),
            expected_return_bps_yr=float(best["E[Ret]"]),
            risk_bps_yr=float(best["Risk"]),
            d1w_bps=float(best["D1W"]),
            tags=["#1 by Sharpe", "Live scanner"],
            note=("Top of today's screen. See <b>Analysis</b> for the full "
                  "ranked board, <b>Trade Decomposition</b> for carry/roll, "
                  "and <b>Backtester</b> for the historical PnL."),
        )

        # Top 3 below as a compact grid
        st.markdown("**Runners-up (top 2-4 by Sharpe)**")
        runners = []
        for _, r in top.iloc[1:4].iterrows():
            runners.append(dict(
                trade=r["Trade"], type_=r["Type"],
                sharpe=float(r["Sharpe"]), z=float(r["Z"]),
                expected_return_bps_yr=float(r["E[Ret]"]),
                risk_bps_yr=float(r["Risk"]),
                d1w_bps=float(r["D1W"]),
            ))
        render_signal_grid(runners, n_cols=3, compact=True)
    else:
        st.info("Scanner has no output — check that the data cache is fresh.")
except Exception as e:
    st.warning(f"Couldn't render scanner cards: {e}")

st.divider()


# ── Two-column row: curve snapshot + headlines ───────────────────────────
left, right = st.columns([3, 2])

with left:
    st.subheader("📉 Curve snapshot")
    ALL = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
    avail = [t for t in ALL if t in df.columns]
    if avail:
        last_r = df[avail].dropna(how="all").iloc[-1]
        wk_r   = df[avail].dropna(how="all").iloc[max(0, len(df)-6)]
        mo_r   = df[avail].dropna(how="all").iloc[max(0, len(df)-22)]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=avail, y=[mo_r[t] for t in avail],
                                  name="1m ago", mode="lines+markers",
                                  line=dict(color="#888", dash="dot")))
        fig.add_trace(go.Scatter(x=avail, y=[wk_r[t] for t in avail],
                                  name="1w ago", mode="lines+markers",
                                  line=dict(color="#4da6ff", dash="dash")))
        fig.add_trace(go.Scatter(x=avail, y=[last_r[t] for t in avail],
                                  name="Today", mode="lines+markers",
                                  line=dict(color="#4fc3f7", width=3)))
        fig.update_layout(template=PLOTLY_THEME, height=320,
                           yaxis_title="Yield (%)",
                           margin=dict(l=10, r=10, t=10, b=10),
                           legend=dict(orientation="h", yanchor="bottom",
                                        y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("📰 Latest")
    try:
        from dashboard.components.news import _fetch as _rss_fetch, _fmt_date, _utm
        # Mix Macro Manv + Bloomberg, max 6 items, sorted by date desc
        items = []
        for url in ("https://manveersahota.substack.com/feed",
                     "https://feeds.bloomberg.com/markets/news.rss"):
            items.extend(_rss_fetch(url, limit=3))
        for it in items[:6]:
            link = _utm(it["link"], "morning") if "manveer" in it["link"] else it["link"]
            st.markdown(
                f"<div style='margin:6px 0;padding-bottom:6px;"
                f"border-bottom:1px solid #1a3056'>"
                f"<a href='{link}' target='_blank' "
                f"style='color:#e8eef9;text-decoration:none;font-size:13.5px;"
                f"font-weight:600'>{it['title']}</a>"
                f"<div style='color:#6a7e9e;font-size:10.5px;margin-top:2px'>"
                f"{_fmt_date(it['published'])}</div></div>",
                unsafe_allow_html=True,
            )
    except Exception as e:
        st.caption(f"RSS unavailable: {e}")

st.divider()


# ── Today's calendar — events in next 7 days ─────────────────────────────
st.subheader("📅 Next 7 days")
try:
    import requests
    # Pull next 7 days of treasury auctions (free, fast)
    r = requests.get(
        "https://www.treasurydirect.gov/TA_WS/securities/announced",
        params={"format": "json"}, timeout=10,
    )
    auctions = []
    if r.ok:
        items = r.json()
        cutoff = date.today() + timedelta(days=7)
        for it in items:
            try:
                ad = datetime.fromisoformat(it["auctionDate"].replace("Z", "")).date()
                if date.today() <= ad <= cutoff:
                    auctions.append((ad, f"{it['securityTerm']} {it['securityType']}"))
            except Exception:
                continue

    if auctions:
        ev_rows = sorted(set(auctions))
        for d, label in ev_rows:
            days_to = (d - date.today()).days
            urgency = "🔴" if days_to <= 1 else "🟡" if days_to <= 3 else "🟢"
            st.markdown(
                f"{urgency} **{d.strftime('%a %d %b')}** — {label} auction  "
                f"<span style='color:#6a7e9e'>(T+{days_to})</span>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No scheduled auctions in the next 7 days.")
except Exception as e:
    st.caption(f"Calendar unavailable: {e}")

st.divider()


# ── Bottom: quick-links to the deeper pages ──────────────────────────────
st.markdown(
    "**Drill into specific pages:**  "
    "[Analysis (scanner)](/Analysis)  ·  "
    "[Regime](/Regime)  ·  "
    "[Backtester](/Backtester)  ·  "
    "[Trade Decomposition](/Trade_Decomposition)  ·  "
    "[Auctions](/Auction_Tracker)  ·  "
    "[Rates Calendar](/Rates_Calendar)"
)
