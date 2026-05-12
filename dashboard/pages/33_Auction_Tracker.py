"""Page 33 — Treasury Auction Tracker.

Live auction quality dashboard: bid-to-cover, indirect / direct / primary
dealer takedown, and a flag for genuinely weak auctions worth a Substack
post.

Data: TreasuryDirect public API (`/TA_WS/securities/auctioned`) — no key,
no rate limit issues, refreshed every hour.

Concepts:
  • Bid-to-cover (B/C) ratio  — total tendered / total accepted. Higher = stronger demand.
  • Indirect bid %            — foreign / non-dealer demand share.
  • Primary dealer %          — dealer takedown — when high, demand was weak.
  • Tail (high - WI)          — not directly available; we proxy with high
                                yield vs previous-auction yield change.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import init_session_state, password_gate

st.set_page_config(page_title="Auction Tracker", page_icon="🏛️", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Auction Tracker")

from dashboard.components.premium_gate import premium_gate
if not premium_gate("Auctions"):
    st.stop()

st.title("🏛️ Treasury Auction Tracker")
st.caption(
    "Bid-to-cover, indirect/direct/primary dealer takedown, and weak-auction "
    "flags from TreasuryDirect. Live data, no key needed."
)
st.divider()


@st.cache_data(ttl=3600, show_spinner="Pulling auction data…")
def _fetch_auctioned(days: int = 365) -> pd.DataFrame:
    try:
        r = requests.get(
            "https://www.treasurydirect.gov/TA_WS/securities/auctioned",
            params={"format": "json", "days": days}, timeout=20,
        )
        r.raise_for_status()
        items = r.json()
    except Exception as e:
        st.warning(f"TreasuryDirect fetch failed: {e}")
        return pd.DataFrame()

    rows = []
    for it in items:
        try:
            ad = datetime.fromisoformat(it["auctionDate"].replace("Z", "")).date()
        except Exception:
            continue

        def _f(key):
            v = it.get(key, "")
            try: return float(v)
            except (ValueError, TypeError): return np.nan

        total_acc = _f("totalAccepted")
        total_ten = _f("totalTendered")
        prim      = _f("primaryDealerAccepted")
        indirect  = _f("indirectBidderAccepted")
        direct    = _f("directBidderAccepted")

        # Pull yield: highYield for coupons, averageMedianDiscountRate for bills
        high_y = _f("highYield")
        if np.isnan(high_y):
            high_y = _f("averageMedianDiscountRate")

        rows.append({
            "auction_date":     ad,
            "type":             it.get("securityType", ""),
            "term":             it.get("securityTerm", ""),
            "cusip":            it.get("cusip", ""),
            "high_yield":       high_y,
            "bid_to_cover":     _f("bidToCoverRatio"),
            "primary_dealer":   prim,
            "indirect":         indirect,
            "direct":           direct,
            "total_accepted":   total_acc,
            "total_tendered":   total_ten,
        })
    df = pd.DataFrame(rows).sort_values("auction_date")
    if df.empty:
        return df
    # Compute %-shares
    df["primary_pct"]  = (df["primary_dealer"] / df["total_accepted"] * 100).round(1)
    df["indirect_pct"] = (df["indirect"]       / df["total_accepted"] * 100).round(1)
    df["direct_pct"]   = (df["direct"]         / df["total_accepted"] * 100).round(1)
    return df


df = _fetch_auctioned(days=365)
if df.empty:
    st.error("No auction data available — TreasuryDirect API may be down.")
    st.stop()


# ── Latest coupon callout ────────────────────────────────────────────────
COUPON_TYPES = {"Note", "Bond"}
coupons = df[df["type"].isin(COUPON_TYPES)].copy()
if not coupons.empty:
    latest = coupons.iloc[-1]
    bc = latest["bid_to_cover"]
    indirect_pct = latest["indirect_pct"]

    # Quality verdict
    if bc < 2.30 or (not np.isnan(indirect_pct) and indirect_pct < 60):
        verdict = "❌ WEAK"; color = "#f87171"
    elif bc > 2.55 and (not np.isnan(indirect_pct) and indirect_pct > 70):
        verdict = "✅ STRONG"; color = "#4ade80"
    else:
        verdict = "→ AVERAGE"; color = "#fbbf24"

    st.markdown(
        f"""
        <div style='background:#122340;border-left:4px solid {color};
                    padding:14px 18px;border-radius:6px;margin:8px 0 16px'>
        <div style='color:#94a8c9;font-size:11px;letter-spacing:1px;
                    font-weight:700'>LATEST COUPON AUCTION  —  {verdict}</div>
        <div style='color:#e8eef9;font-size:22px;font-weight:700;margin:4px 0'>
            {latest['term']} {latest['type']}  ·  {latest['auction_date']}
        </div>
        <div style='color:#94a8c9;font-size:14px'>
            B/C <b style='color:{color}'>{bc:.2f}</b>  ·
            Indirect <b>{indirect_pct:.1f}%</b>  ·
            Direct <b>{latest['direct_pct']:.1f}%</b>  ·
            Primary <b>{latest['primary_pct']:.1f}%</b>  ·
            High yield <b>{latest['high_yield']:.3f}%</b>
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── All recent auctions ──────────────────────────────────────────────────
st.subheader("📋 Last 60 days")
horizon = (datetime.today().date() - timedelta(days=60))
recent = df[df["auction_date"] >= horizon].copy()

# Weak / strong flags per row
def _flag(r):
    if r["type"] not in COUPON_TYPES:
        return ""    # bills aren't really tail-watched
    if (not np.isnan(r["bid_to_cover"]) and r["bid_to_cover"] < 2.30) or \
       (not np.isnan(r["indirect_pct"]) and r["indirect_pct"] < 60):
        return "❌ Weak"
    if (not np.isnan(r["bid_to_cover"]) and r["bid_to_cover"] > 2.55) and \
       (not np.isnan(r["indirect_pct"]) and r["indirect_pct"] > 70):
        return "✅ Strong"
    return ""

recent["flag"] = recent.apply(_flag, axis=1)
disp = recent[[
    "auction_date", "term", "type", "high_yield",
    "bid_to_cover", "indirect_pct", "direct_pct", "primary_pct", "flag",
]].rename(columns={
    "auction_date":  "Date",
    "term":          "Term",
    "type":          "Type",
    "high_yield":    "Yield (%)",
    "bid_to_cover":  "B/C",
    "indirect_pct":  "Indirect %",
    "direct_pct":    "Direct %",
    "primary_pct":   "Primary %",
    "flag":          "Verdict",
}).sort_values("Date", ascending=False)
st.dataframe(disp, use_container_width=True, hide_index=True,
             column_config={
                 "Yield (%)":  st.column_config.NumberColumn(format="%.3f"),
                 "B/C":        st.column_config.NumberColumn(format="%.2f"),
                 "Indirect %": st.column_config.NumberColumn(format="%.1f"),
                 "Direct %":   st.column_config.NumberColumn(format="%.1f"),
                 "Primary %":  st.column_config.NumberColumn(format="%.1f"),
             })

st.divider()


# ── Rolling B/C trend per tenor ──────────────────────────────────────────
st.subheader("📈 Bid-to-cover trend by tenor")
tenor_options = sorted(coupons["term"].unique())
chosen_tenor = st.selectbox("Pick a tenor", tenor_options,
                             index=tenor_options.index("10-Year")
                             if "10-Year" in tenor_options else 0)

sub = coupons[coupons["term"] == chosen_tenor].sort_values("auction_date")
if not sub.empty:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        row_heights=[0.55, 0.45],
                        subplot_titles=(f"B/C ratio — {chosen_tenor}",
                                        f"Indirect bid % — {chosen_tenor}"))
    fig.add_trace(go.Scatter(x=sub["auction_date"], y=sub["bid_to_cover"],
                              mode="lines+markers",
                              line=dict(color="#4fc3f7", width=2),
                              marker=dict(size=8),
                              name="B/C"),
                  row=1, col=1)
    fig.add_hline(y=sub["bid_to_cover"].mean(), line_dash="dash",
                   line_color="#94a8c9",
                   annotation_text=f"Mean {sub['bid_to_cover'].mean():.2f}",
                   row=1, col=1)
    fig.add_hline(y=2.30, line_dash="dot", line_color="#f87171",
                   annotation_text="Weak floor 2.30",
                   annotation_position="bottom right",
                   row=1, col=1)
    fig.add_trace(go.Scatter(x=sub["auction_date"], y=sub["indirect_pct"],
                              mode="lines+markers",
                              line=dict(color="#a78bfa", width=2),
                              marker=dict(size=8),
                              name="Indirect %"),
                  row=2, col=1)
    fig.add_hline(y=sub["indirect_pct"].mean(), line_dash="dash",
                   line_color="#94a8c9",
                   annotation_text=f"Mean {sub['indirect_pct'].mean():.1f}%",
                   row=2, col=1)
    fig.update_layout(template=PLOTLY_THEME, height=520,
                      margin=dict(l=10, r=10, t=40, b=10),
                      hovermode="x unified", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)


# ── Notable weak auctions in last 90 days ────────────────────────────────
st.divider()
st.subheader("🚨 Substack-worthy weak auctions (last 90 days)")
horizon90 = (datetime.today().date() - timedelta(days=90))
weak = coupons[
    (coupons["auction_date"] >= horizon90) & (
        (coupons["bid_to_cover"] < 2.30) |
        (coupons["indirect_pct"] < 60)
    )
].sort_values("auction_date", ascending=False)

if weak.empty:
    st.info("No weak auctions in the last 90 days. Demand has been solid.")
else:
    for _, w in weak.iterrows():
        reasons = []
        if w["bid_to_cover"] < 2.30:
            reasons.append(f"B/C {w['bid_to_cover']:.2f} (below 2.30 floor)")
        if w["indirect_pct"] < 60:
            reasons.append(f"indirect only {w['indirect_pct']:.1f}%")
        if w["primary_pct"] > 25:
            reasons.append(f"primary dealers absorbed {w['primary_pct']:.1f}%")

        st.markdown(
            f"""
            <div style='background:#122340;border-left:3px solid #f87171;
                        padding:10px 14px;border-radius:4px;margin:6px 0'>
            <div style='color:#e8eef9;font-size:15px;font-weight:700'>
                {w['term']} {w['type']}  ·  {w['auction_date']}
            </div>
            <div style='color:#f87171;font-size:13px;margin-top:3px'>
                {' · '.join(reasons)}
            </div>
            <div style='color:#94a8c9;font-size:11px;margin-top:3px'>
                Yield {w['high_yield']:.3f}%  ·
                Indirect {w['indirect_pct']:.1f}%  ·
                Direct {w['direct_pct']:.1f}%  ·
                Primary {w['primary_pct']:.1f}%
            </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.divider()
st.caption(
    "**B/C below 2.30** is the rough 'weak demand' threshold for coupon "
    "auctions. **Indirect below 60%** signals foreign demand drying up. "
    "**Primary dealer share above 25%** means dealers are absorbing supply "
    "(usually a tail, sometimes Substack-worthy)."
)
