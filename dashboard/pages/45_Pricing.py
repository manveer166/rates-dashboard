"""Page 45 — Pricing / Tier comparison.

Public-facing marketing page that pitches the four tiers:
  Free  →  Substack  →  Pro  →  Founding (limited)

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

st.title("💎 Pricing")
st.markdown(
    """
<p style="color:var(--c-text-2);font-size:15px;margin-top:-4px;margin-bottom:6px;">
One subscription, one login. Free for the data — paid for the scanner,
backtester, and the rest of the trader stack.
</p>
<p style="color:var(--c-text-3);font-size:12px;margin-bottom:14px;">
Research-grade RV analytics: cash-flow-level DV01 &amp; convexity,
forward-rate carry, practitioner bid/ask widths. Every formula documented
on the <a href="/Methodology" target="_self" style="color:#4fc3f7;text-decoration:none">Methodology page</a>.
</p>
    """,
    unsafe_allow_html=True,
)
st.divider()


SUB_URL_BASE = ("https://manveersahota.substack.com/subscribe"
                 "?utm_source=dashboard&utm_medium=pricing&utm_campaign=")


def _tier_card(*, name: str, badge_color: str, tagline: str, price: str,
                annual: str, includes_substack: bool, includes_dashboard: str,
                bullets: list[str], cta_text: str, cta_url: str | None,
                highlight: bool = False, limited_note: str | None = None):
    """Render one tier card."""
    border = "2px solid " + badge_color if highlight else "1px solid #233e6e"
    shadow = (f"box-shadow:0 4px 16px {badge_color}25;"
              if highlight else "")
    bg = ("linear-gradient(135deg,#0e1f3a 0%,#1a3056 100%)"
          if highlight else "#0e1f3a")

    bullets_html = "".join(
        f'<li style="margin:5px 0">{b}</li>' for b in bullets
    )

    incl_lines = []
    if includes_substack:
        incl_lines.append(
            '<div style="display:flex;align-items:center;gap:6px;margin:3px 0;'
            'color:#4ade80;font-size:12px"><b>✓</b> Paid Substack newsletter</div>'
        )
    else:
        incl_lines.append(
            '<div style="display:flex;align-items:center;gap:6px;margin:3px 0;'
            'color:#6a7e9e;font-size:12px"><b>✗</b> Paid Substack newsletter</div>'
        )
    if includes_dashboard == "free":
        incl_lines.append(
            '<div style="display:flex;align-items:center;gap:6px;margin:3px 0;'
            'color:#94a8c9;font-size:12px"><b>~</b> Free dashboard pages (22)</div>'
        )
    elif includes_dashboard == "free+":
        incl_lines.append(
            '<div style="display:flex;align-items:center;gap:6px;margin:3px 0;'
            'color:#94a8c9;font-size:12px"><b>✓</b> Free dashboard pages (22)</div>'
        )
    elif includes_dashboard == "pro":
        incl_lines.append(
            '<div style="display:flex;align-items:center;gap:6px;margin:3px 0;'
            'color:#94a8c9;font-size:12px"><b>✓</b> Free dashboard pages (22)</div>'
        )
        incl_lines.append(
            '<div style="display:flex;align-items:center;gap:6px;margin:3px 0;'
            f'color:{badge_color};font-size:12px;font-weight:600">'
            '<b>✓</b> Premium dashboard pages (13)</div>'
        )
    incl_html = "".join(incl_lines)

    limited_html = ""
    if limited_note:
        limited_html = (
            f'<div style="background:#3a1a06;color:#fb923c;font-size:10.5px;'
            f'letter-spacing:0.5px;padding:4px 8px;border-radius:4px;'
            f'margin-top:8px;text-align:center;font-weight:700">'
            f'⚡ {limited_note}</div>'
        )

    cta_html = ""
    if cta_url and cta_text:
        cta_html = (
            f'<div style="margin-top:18px;text-align:center">'
            f'<a href="{cta_url}" target="_blank" '
            f'style="display:inline-block;background:{badge_color};'
            f'color:#0a1628;padding:11px 22px;border-radius:6px;'
            f'text-decoration:none;font-weight:700;font-size:13.5px;'
            f'width:90%;box-sizing:border-box">'
            f'{cta_text}</a></div>'
        )
    elif cta_text:
        # Disabled-style label (no link) — used for the Free tier
        cta_html = (
            f'<div style="margin-top:18px;text-align:center">'
            f'<div style="background:#1a3056;color:#94a8c9;padding:11px 22px;'
            f'border-radius:6px;font-weight:600;font-size:13px">{cta_text}</div>'
            f'</div>'
        )

    return f"""
    <div style='background:{bg};border:{border};border-radius:10px;
                padding:20px 22px;height:100%;{shadow}'>
      <div style='color:{badge_color};font-size:10.5px;letter-spacing:2px;
                  font-weight:700;text-transform:uppercase'>{name}</div>
      <h3 style='color:#e8eef9;margin:8px 0 6px;font-size:22px;line-height:1.2'>
          {tagline}
      </h3>
      <div style='margin:12px 0 8px'>
          <span style='color:#e8eef9;font-size:30px;font-weight:700'>{price}</span>
          {f"<span style='color:#6a7e9e;font-size:13px;margin-left:6px'>/ month</span>" if price not in ("$0", "—") else ""}
      </div>
      {f"<div style='color:#94a8c9;font-size:12px;margin-bottom:4px'>{annual}</div>" if annual else ""}
      {limited_html}
      <div style='margin-top:14px;padding-top:14px;border-top:1px solid #233e6e'>
          {incl_html}
      </div>
      <div style='margin-top:14px;padding-top:12px;border-top:1px solid #233e6e'>
          <div style='color:#94a8c9;font-size:10.5px;letter-spacing:1px;
                      font-weight:700;margin-bottom:6px'>HIGHLIGHTS</div>
          <ul style='color:#cbd5e1;font-size:12.5px;line-height:1.55;
                     padding-left:18px;margin:0'>{bullets_html}</ul>
      </div>
      {cta_html}
    </div>
    """


# ── 4-column tier grid ────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4, gap="medium")

with c1:
    st.markdown(_tier_card(
        name="Free",
        badge_color="#4ade80",
        tagline="Rates intel",
        price="$0",
        annual="Forever free",
        includes_substack=False,
        includes_dashboard="free+",
        bullets=[
            "Free newsletter posts",
            "🌅 Morning Briefing daily",
            "📉 US, EU, UK & Asian yield curves",
            "💱 FX overlay · 🔥 Global inflation",
            "🎯 Trade of the Week + 🏆 track record",
            "📅 Rates Calendar · 📚 Glossary",
        ],
        cta_text="You're here",
        cta_url=None,
    ), unsafe_allow_html=True)

with c2:
    st.markdown(_tier_card(
        name="Substack",
        badge_color="#fbbf24",
        tagline="The writing + insight tools",
        price="$15",
        annual="$150 / year (save 17%)",
        includes_substack=True,
        includes_dashboard="pro",
        bullets=[
            "Everything in Free",
            "📨 Full paid Substack archive",
            "📨 Premium-only Substack posts",
            "<b>7 semi-pro dashboard pages:</b>",
            "📐 Regression · 🧮 PCA · 🔗 Correlation",
            "🧩 Trade Decomposition · 📌 Watchlist",
            "🏛️ Auctions · 📊 CTA Positioning",
        ],
        cta_text="📨 Subscribe — $15",
        cta_url=SUB_URL_BASE + "substack_only",
    ), unsafe_allow_html=True)

with c3:
    st.markdown(_tier_card(
        name="Pro · Macro Manv",
        badge_color="#4fc3f7",
        tagline="The full RV research stack",
        price="$49",
        annual="$420 / year (save 28%)",
        includes_substack=True,
        includes_dashboard="pro",
        bullets=[
            "Everything in Substack",
            "<b>+6 Pro-only trader tools:</b>",
            "🔍 Trade Scanner — ranked RV board",
            "🧰 Trade Builder — DV01-neutral + ticket",
            "🧪 Backtester — 5Y daily PnL stats",
            "🧭 Regime detector — conditional Sharpe",
            "🧮 PCA Backtest — strategy on PCs",
            "🌊 Vol Surface — swaption grid + smile",
        ],
        cta_text="📬 Upgrade to Pro →",
        cta_url=SUB_URL_BASE + "pro_upgrade",
        highlight=True,
    ), unsafe_allow_html=True)

with c4:
    st.markdown(_tier_card(
        name="Founding",
        badge_color="#a78bfa",
        tagline="Pro, price-locked",
        price="$29",
        annual="$290 / year (save 16%)",
        includes_substack=True,
        includes_dashboard="pro",
        bullets=[
            "Everything in Pro — same access",
            "🔒 <b>Price locked for life (10 years)</b>",
            "💬 Direct line to Macro Manv — ask anything",
            "⚡ Direct line to feature requests",
            "🚀 First access to new pages",
            "<i>For the first 100. Then it's $49 like everyone else.</i>",
        ],
        cta_text="⚡ Lock in $29 →",
        cta_url=SUB_URL_BASE + "founding",
        limited_note="LIMITED — FIRST 100 SUBSCRIBERS",
    ), unsafe_allow_html=True)


st.divider()


# ── How tier upgrades work ───────────────────────────────────────────────
st.subheader("🔁 How upgrades work")
ec1, ec2, ec3 = st.columns(3)
with ec1:
    st.markdown(
        """
        ### One subscription, one email
        Your Substack subscription email is also your dashboard login.
        Pay through Substack, get instant access here. No second account
        to manage.
        """
    )
with ec2:
    st.markdown(
        """
        ### Cancel any time
        Substack handles the billing — same monthly or annual cycle as
        any other paid newsletter. Cancel mid-cycle, keep access until
        the period ends.
        """
    )
with ec3:
    st.markdown(
        """
        ### Founding lock — for life
        First 100 subscribers at the $29/mo rate **stay there for life**
        (10-year price guarantee on any active subscription). The rate
        goes up for everyone after slot 100, but not for you.
        """
    )

st.divider()


# ── Feature comparison matrix ────────────────────────────────────────────
st.subheader("📋 Full feature comparison")

import pandas as pd
matrix = [
    ("**Free dashboard pages (22)**",                     "✓",        "✓",        "✓",       "✓"),
    ("• Morning Briefing · What Changed",                 "✓",        "✓",        "✓",       "✓"),
    ("• US / EU / UK / Asian curves",                     "✓",        "✓",        "✓",       "✓"),
    ("• Real Rates · FX · Global Inflation",              "✓",        "✓",        "✓",       "✓"),
    ("• Cross-Asset · Vol Scorecard · Bond Futures",      "✓",        "✓",        "✓",       "✓"),
    ("• Trade of the Week + Performance",                 "✓",        "✓",        "✓",       "✓"),
    ("• Rates Calendar · Glossary · User Guide",          "✓",        "✓",        "✓",       "✓"),
    ("**Free newsletter posts**",                         "✓",        "✓",        "✓",       "✓"),
    ("**Paid newsletter (Substack premium)**",            "—",        "✓",        "✓",       "✓"),
    ("• Full archive access",                             "—",        "✓",        "✓",       "✓"),
    ("• Premium-only posts",                              "—",        "✓",        "✓",       "✓"),
    ("**Substack-tier semi-pro pages (7)**",              "—",        "✓",        "✓",       "✓"),
    ("• 📐 Regression — yields vs macro fits",            "—",        "✓",        "✓",       "✓"),
    ("• 🧮 PCA — curve decomposition",                    "—",        "✓",        "✓",       "✓"),
    ("• 🔗 Correlation matrix",                           "—",        "✓",        "✓",       "✓"),
    ("• 🧩 Trade Decomposition (carry/roll/MR)",          "—",        "✓",        "✓",       "✓"),
    ("• 📌 Watchlist with auto-alerts",                   "—",        "✓",        "✓",       "✓"),
    ("• 🏛️ Auctions · 📊 CTA Positioning",                "—",        "✓",        "✓",       "✓"),
    ("**Pro-tier trader tools (6)**",                     "—",        "—",        "✓",       "✓"),
    ("• 🔍 Trade Scanner — ranked RV board",              "—",        "—",        "✓",       "✓"),
    ("• 🧰 Trade Builder — DV01-neutral ticket",          "—",        "—",        "✓",       "✓"),
    ("• 🧪 Backtester — 5Y daily PnL",                    "—",        "—",        "✓",       "✓"),
    ("• 🧭 Regime detector — conditional Sharpe",         "—",        "—",        "✓",       "✓"),
    ("• 🧮 PCA Backtest — strategy on PCs",               "—",        "—",        "✓",       "✓"),
    ("• 🌊 Vol Surface",                                  "—",        "—",        "✓",       "✓"),
    ("**Founding-only perks**",                           "—",        "—",        "—",       "✓"),
    ("• 🔒 Price locked for life (10 years)",             "—",        "—",        "—",       "✓"),
    ("• 💬 Direct line to Macro Manv",                    "—",        "—",        "—",       "✓"),
    ("• ⚡ Direct feature-request line",                  "—",        "—",        "—",       "✓"),
    ("• 🚀 First access to new pages",                    "—",        "—",        "—",       "✓"),
    ("**Price (monthly)**",                               "**$0**",   "**$15**",  "**$49**", "**$29**"),
    ("**Price (annual)**",                                "—",        "$150",     "$420",    "$290"),
]
mdf = pd.DataFrame(matrix, columns=["Feature", "Free", "Substack",
                                       "Pro", "Founding"])
st.markdown(mdf.to_markdown(index=False), unsafe_allow_html=False)


st.divider()


# ── Counter strip ────────────────────────────────────────────────────────
from dashboard.components.signal_card import render_market_kpi_row
render_market_kpi_row([
    {"label": "Free pages",     "value": "22", "unit": "publicly browsable",
     "hint": "Curves · macro · TotW · calendar", "color": "#4ade80"},
    {"label": "Premium pages",  "value": "13", "unit": "Pro / Founding",
     "hint": "Scanner · Backtester · Regime · …", "color": "#4fc3f7"},
    {"label": "Total built",    "value": "45", "unit": "pages",
     "hint": "Updated continuously", "color": "#fbbf24"},
    {"label": "Tier you're on", "value": "—",  "unit": "log in to see",
     "hint": "Free · Substack · Pro · Founding", "color": "#a78bfa"},
])

st.divider()
st.caption(
    "Questions? Reply to any Macro Manv email, or DM "
    "[@MacroManv](https://twitter.com/MacroManv) on X."
)
