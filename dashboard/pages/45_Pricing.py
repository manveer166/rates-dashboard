"""Page 45 — Pricing / Tier comparison.

Public-facing marketing page that pitches the Free vs Premium tiers.
Designed to convert free users → paid subscribers.
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import init_session_state, password_gate

st.set_page_config(page_title="Pricing", page_icon="💎", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Pricing")

st.title("💎 Macro Manv Tiers")
st.caption("What's free, what's paid, and why.")
st.divider()


# ── Two-column hero ──────────────────────────────────────────────────────
free_col, prem_col = st.columns(2, gap="large")

with free_col:
    st.markdown(
        """
        <div style='background:#0e1f3a;border:1px solid #233e6e;border-radius:10px;
                    padding:24px 28px;height:100%;'>
          <div style='color:#4ade80;font-size:11px;letter-spacing:2px;
                      font-weight:700'>FREE</div>
          <h2 style='color:#e8eef9;margin:6px 0 12px;font-size:28px'>
              Rates intel
          </h2>
          <p style='color:#94a8c9;font-size:14px;line-height:1.6'>
              Live US, EU, UK and Asian yield curves. Cross-asset context.
              Real rates, breakevens, global inflation. A morning briefing
              that pulls together today's top trade with the headlines that
              matter for it. The auction calendar, the FOMC clock, and the
              full Substack archive. Every week, one curated Trade of the
              Week — its thesis and its running PnL, on the record.
          </p>
          <p style='color:#cbd5e1;font-size:14px;margin-top:18px;font-weight:600'>
              For rates-curious investors who want institutional-quality
              data without an institutional bill.
          </p>
          <div style='margin-top:24px;padding-top:18px;
                      border-top:1px solid #233e6e'>
            <div style='color:#94a8c9;font-size:11px;letter-spacing:1px;
                        font-weight:700;margin-bottom:10px'>WHAT YOU GET</div>
            <ul style='color:#cbd5e1;font-size:13px;line-height:1.9;
                       padding-left:18px;margin:0'>
              <li>🌅 Morning Briefing — single-screen daily view</li>
              <li>🆕 What Changed Today — auto-flagged moves</li>
              <li>📉 Yield curves: US, EU AAA, UK, Asia</li>
              <li>📊 Spreads · 💱 FX · 📉 Real rates · 🔥 Inflation</li>
              <li>🌐 Global Macro · 📈 Bond futures · 🌊 Vol Scorecard</li>
              <li>🎯 Trade of the Week + 🏆 full track record</li>
              <li>📅 Rates Calendar · 📡 Sources · 📖 Glossary</li>
            </ul>
          </div>
          <div style='margin-top:24px;padding:12px 16px;background:#122340;
                      border-radius:6px;text-align:center'>
            <div style='color:#94a8c9;font-size:12px'>Price</div>
            <div style='color:#e8eef9;font-size:24px;font-weight:700'>
                $0 / month
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with prem_col:
    st.markdown(
        """
        <div style='background:linear-gradient(135deg,#0e1f3a 0%,#1a3056 100%);
                    border:2px solid #4fc3f7;border-radius:10px;
                    padding:24px 28px;height:100%;
                    box-shadow:0 4px 12px rgba(79,195,247,0.15);'>
          <div style='color:#4fc3f7;font-size:11px;letter-spacing:2px;
                      font-weight:700'>PREMIUM — MACRO MANV PRO</div>
          <h2 style='color:#e8eef9;margin:6px 0 12px;font-size:28px'>
              The analytical stack
          </h2>
          <p style='color:#94a8c9;font-size:14px;line-height:1.6'>
              Every receive/pay outright, curve, and fly ranked by Sharpe
              with carry, rolldown, Z-score, and expected return.
              DV01-neutral trade construction that hands you a ticket.
              A backtester that gives every signal a credibility number.
              Regime detection that tells you whether carry or convexity
              wins in today's market.
          </p>
          <p style='color:#cbd5e1;font-size:14px;margin-top:18px;font-weight:600'>
              For active rates traders who size positions, not just opinions.
          </p>
          <div style='margin-top:24px;padding-top:18px;
                      border-top:1px solid #4fc3f7'>
            <div style='color:#4fc3f7;font-size:11px;letter-spacing:1px;
                        font-weight:700;margin-bottom:10px'>EVERYTHING IN FREE, PLUS</div>
            <ul style='color:#cbd5e1;font-size:13px;line-height:1.9;
                       padding-left:18px;margin:0'>
              <li>🔍 <b>Trade Scanner</b> — full ranked RV board</li>
              <li>🧰 <b>Trade Builder</b> — DV01-neutral leg sizing + ticket</li>
              <li>🧪 <b>Backtester</b> — historical PnL for any trade</li>
              <li>🧩 <b>Trade Decomposition</b> — carry/roll/mean-rev waterfall</li>
              <li>🧭 <b>Regime detector</b> — carry vs convexity + conditional Sharpe</li>
              <li>📐 <b>Regression · 🧮 PCA + PCA Backtest · 🔗 Correlation</b></li>
              <li>🌊 <b>Vol Surface</b> — swaption ATM grid + smile</li>
              <li>🏛️ <b>Auctions</b> — bid-to-cover, weak-flag alerts</li>
              <li>📊 <b>CTA Positioning</b> — CFTC with 1Y percentile</li>
              <li>📌 <b>Watchlist</b> — pin + live PnL + auto-alerts</li>
            </ul>
          </div>
          <div style='margin-top:24px;padding:12px 16px;background:#0a1628;
                      border-radius:6px;text-align:center;
                      border:1px solid #4fc3f7'>
            <div style='color:#94a8c9;font-size:12px'>Same as your</div>
            <div style='color:#e8eef9;font-size:20px;font-weight:700;margin:4px 0'>
                Macro Manv paid Substack
            </div>
            <div style='color:#94a8c9;font-size:11px;margin-top:4px'>
                One subscription, same login email
            </div>
          </div>
          <div style='margin-top:18px;text-align:center'>
            <a href='https://manveersahota.substack.com/subscribe?utm_source=dashboard&utm_medium=pricing&utm_campaign=upgrade'
               target='_blank'
               style='display:inline-block;background:#4fc3f7;color:#0a1628;
                      padding:12px 32px;border-radius:6px;text-decoration:none;
                      font-weight:700;font-size:15px'>
                📬 Upgrade to Pro →
            </a>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.write("")
st.write("")


# ── Why-this-split rationale ─────────────────────────────────────────────
st.subheader("🤔 Why this split?")

rc1, rc2, rc3 = st.columns(3)
with rc1:
    st.markdown(
        """
        ### Free is generous on purpose
        Every yield curve, every breakeven, every piece of macro context is
        free. That's how we build trust and prove the data quality.

        **Free readers see *what* the market is doing.**
        """
    )
with rc2:
    st.markdown(
        """
        ### Premium is the alpha layer
        It's the *which trade to put on, how to size it, and what's the
        historical edge*. Work that takes hours per day if you do it
        manually.

        **Premium readers see *what to do about it*.**
        """
    )
with rc3:
    st.markdown(
        """
        ### Owner-only tools
        Compose pages (Alerts, AI Drafter, Social Cards, A/B Tests, Admin)
        produce the content that subscribers consume on Substack / email /
        social.

        **Subscribers never see these — and shouldn't have to.**
        """
    )

st.divider()


# ── Counter strip ────────────────────────────────────────────────────────
from dashboard.components.signal_card import render_market_kpi_row
render_market_kpi_row([
    {"label": "Free pages",     "value": "22", "unit": "publicly browsable",
     "hint": "Markets + Help + TotW + Performance", "color": "#4ade80"},
    {"label": "Premium pages",  "value": "13", "unit": "behind the gate",
     "hint": "Analytics + Trade tools + Flow data", "color": "#4fc3f7"},
    {"label": "Owner-only",     "value": "10", "unit": "admin tools",
     "hint": "Publish + Admin (invisible to subscribers)", "color": "#94a8c9"},
    {"label": "Total",          "value": "45", "unit": "pages built",
     "hint": "Updated continuously", "color": "#fbbf24"},
])

st.divider()
st.caption(
    "Questions? Reply to any Macro Manv email or DM "
    "[@MacroManv](https://twitter.com/MacroManv) on X."
)
