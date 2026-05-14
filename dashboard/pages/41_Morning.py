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


# ── Two-column row: contextual chart + headlines ─────────────────────────
# Headline → chart-topic keyword map. First match wins.
KEYWORD_TO_TOPIC = [
    (("iran", "oil", "energy", "opec", "brent", "wti", "crude", "petroleum"), "oil"),
    (("inflation", "cpi", "ppi", "breakeven", "tips", "deflation", "inflation target"), "inflation"),
    (("hong kong", "hkma", "hibor"), "asia_curve"),
    (("china", "pboc", "yuan", "renminbi"), "asia_curve"),
    (("japan", "boj", "yen", " jpy", "jgb"), "asia_curve"),
    (("europe", "euro area", "eurozone", "ecb", "bund", "german"), "eu_curve"),
    (("uk ", "gilt", "sterling", " boe", "starmer", "downing"), "uk_curve"),
    (("nvidia", "ai ", "semiconductor", "tech", "hon hai", "tsmc", "apple"), "equity_vol"),
    (("fed", "fomc", "powell", "rate cut", "rate hike"), "fed_funds"),
    (("space", "spx", "stock market", "equit", "s&p"), "equity_vol"),
    (("turkey", "lira", "emerging"), "fx"),
    (("auction", "treasury bill", "bid to cover", "indirect"), "us_curve"),
]


def _topic_for_title(title: str) -> str:
    t = title.lower()
    for kws, topic in KEYWORD_TO_TOPIC:
        if any(k in t for k in kws):
            return topic
    return "us_curve"


def _topic_label(topic: str) -> str:
    return {
        "us_curve":    "US Treasury curve",
        "eu_curve":    "EU AAA yield curve",
        "uk_curve":    "UK gilt curve",
        "asia_curve":  "Asian sovereign curves",
        "oil":         "WTI crude oil",
        "inflation":   "US TIPS + breakevens",
        "equity_vol":  "VIX + S&P proxy",
        "fed_funds":   "SOFR + EFFR (Fed funds proxy)",
        "fx":          "USD vs EUR / JPY / GBP",
    }.get(topic, "US Treasury curve")


def _render_topic_chart(topic: str):
    """Render a Plotly chart for the chosen topic. Falls back to US curve."""
    ALL = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
    avail = [t for t in ALL if t in df.columns]

    if topic == "us_curve" or topic not in (
        "eu_curve", "uk_curve", "asia_curve", "oil", "inflation",
        "equity_vol", "fed_funds", "fx",
    ):
        if not avail: return None
        last_r = df[avail].dropna(how="all").iloc[-1]
        wk_r   = df[avail].dropna(how="all").iloc[max(0, len(df)-6)]
        mo_r   = df[avail].dropna(how="all").iloc[max(0, len(df)-22)]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=avail, y=[mo_r[t] for t in avail], name="1m ago",
                                  mode="lines+markers",
                                  line=dict(color="#888", dash="dot")))
        fig.add_trace(go.Scatter(x=avail, y=[wk_r[t] for t in avail], name="1w ago",
                                  mode="lines+markers",
                                  line=dict(color="#4da6ff", dash="dash")))
        fig.add_trace(go.Scatter(x=avail, y=[last_r[t] for t in avail], name="Today",
                                  mode="lines+markers",
                                  line=dict(color="#4fc3f7", width=3)))
        fig.update_layout(template=PLOTLY_THEME, height=320, yaxis_title="Yield (%)",
                           xaxis_title="Tenor",
                           margin=dict(l=10, r=10, t=10, b=10),
                           legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                        xanchor="right", x=1))
        return fig

    if topic == "eu_curve":
        try:
            from data.openbb_data import yield_curve as _yc
            sub = _yc("germany")
            if sub.empty:
                # Fall back to ECB AAA via our own fetcher
                from data.fetchers.ecb import ECBFetcher
                from datetime import datetime as dt, timedelta as td
                eu = ECBFetcher((dt.today() - td(days=30)).isoformat(),
                                  dt.today().isoformat(), use_cache=True).fetch()
                if eu.empty: return None
                last = eu.dropna(how="all").iloc[-1]
                ts = ["EU_2Y","EU_3Y","EU_5Y","EU_7Y","EU_10Y","EU_20Y","EU_30Y"]
                ts = [t for t in ts if t in last.index]
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=[t.replace("EU_","") for t in ts],
                                          y=[last[t] for t in ts],
                                          mode="lines+markers", name="EU AAA today",
                                          line=dict(color="#a78bfa", width=3)))
                fig.update_layout(template=PLOTLY_THEME, height=320,
                                   yaxis_title="Yield (%)", xaxis_title="Tenor",
                                   margin=dict(l=10, r=10, t=10, b=10))
                return fig
            sub = sub.sort_values("maturity_years")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=sub["maturity_years"], y=sub["rate"] * 100,
                                      mode="lines+markers", name="Germany",
                                      line=dict(color="#a78bfa", width=3)))
            fig.update_layout(template=PLOTLY_THEME, height=320,
                               yaxis_title="Yield (%)", xaxis_title="Maturity (yrs)",
                               margin=dict(l=10, r=10, t=10, b=10))
            return fig
        except Exception:
            return None

    if topic == "uk_curve":
        try:
            from data.fetchers.boe import BoEFetcher
            from datetime import datetime as dt, timedelta as td
            uk = BoEFetcher((dt.today() - td(days=180)).isoformat(),
                              dt.today().isoformat(), use_cache=True).fetch()
            if uk.empty: return None
            recent = uk.tail(60)
            fig = go.Figure()
            for col, color in [("UK_2Y","#fb923c"), ("UK_5Y","#fbbf24"), ("UK_10Y","#f472b6")]:
                if col in recent.columns:
                    fig.add_trace(go.Scatter(x=recent.index, y=recent[col], name=col,
                                              line=dict(color=color, width=2)))
            fig.update_layout(template=PLOTLY_THEME, height=320,
                               yaxis_title="Gilt yield (%)",
                               margin=dict(l=10, r=10, t=10, b=10),
                               legend=dict(orientation="h", yanchor="bottom",
                                            y=1.02, xanchor="right", x=1))
            return fig
        except Exception:
            return None

    if topic == "asia_curve":
        try:
            from data.openbb_data import asia_yield_snapshot
            asia = asia_yield_snapshot()
            if asia.empty: return None
            fig = go.Figure()
            palette = {"China":"#dc2626","Japan":"#f87171","South Korea":"#fbbf24",
                       "Singapore":"#4ade80","Taiwan":"#a78bfa"}
            for c in sorted(asia["country"].unique()):
                sub = asia[asia["country"] == c].sort_values("maturity_years")
                fig.add_trace(go.Scatter(x=sub["maturity_years"], y=sub["rate"] * 100,
                                          mode="lines+markers", name=c,
                                          line=dict(color=palette.get(c, "#94a8c9"), width=2)))
            fig.update_layout(template=PLOTLY_THEME, height=320,
                               yaxis_title="Yield (%)", xaxis_title="Maturity (yrs)",
                               margin=dict(l=10, r=10, t=10, b=10),
                               legend=dict(orientation="h", yanchor="bottom",
                                            y=1.02, xanchor="right", x=1))
            return fig
        except Exception:
            return None

    if topic == "oil":
        try:
            import yfinance as yf
            h = yf.Ticker("CL=F").history(period="6mo", interval="1d")
            if h.empty: return None
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=h.index, y=h["Close"], name="WTI",
                                      line=dict(color="#fb923c", width=2),
                                      fill="tozeroy",
                                      fillcolor="rgba(251,146,60,0.10)"))
            fig.update_layout(template=PLOTLY_THEME, height=320,
                               yaxis_title="WTI ($/bbl)",
                               margin=dict(l=10, r=10, t=10, b=10),
                               showlegend=False)
            return fig
        except Exception:
            return None

    if topic == "inflation":
        cols = [c for c in ("BREAKEVEN_5Y","BREAKEVEN_10Y","TIPS_10Y") if c in df.columns]
        if not cols: return None
        win = df[cols].dropna(how="all").tail(252)
        colors = {"BREAKEVEN_5Y":"#fbbf24","BREAKEVEN_10Y":"#fb923c","TIPS_10Y":"#4fc3f7"}
        fig = go.Figure()
        for c in cols:
            fig.add_trace(go.Scatter(x=win.index, y=win[c], name=c.replace("_"," "),
                                      line=dict(color=colors[c], width=1.8)))
        fig.add_hline(y=2.0, line_dash="dash", line_color="#4ade80",
                       annotation_text="Fed 2% target")
        fig.update_layout(template=PLOTLY_THEME, height=320,
                           yaxis_title="%", margin=dict(l=10, r=10, t=10, b=10),
                           legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                        xanchor="right", x=1))
        return fig

    if topic == "equity_vol":
        if "VIX" not in df.columns: return None
        win = df["VIX"].dropna().tail(252)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=win.index, y=win.values, name="VIX",
                                  line=dict(color="#f87171", width=2),
                                  fill="tozeroy",
                                  fillcolor="rgba(248,113,113,0.10)"))
        fig.update_layout(template=PLOTLY_THEME, height=320,
                           yaxis_title="VIX", margin=dict(l=10, r=10, t=10, b=10),
                           showlegend=False)
        return fig

    if topic == "fed_funds":
        cols = [c for c in ("SOFR","EFFR") if c in df.columns]
        if not cols: return None
        win = df[cols].dropna(how="all").tail(252)
        fig = go.Figure()
        for c, color in zip(cols, ["#4fc3f7","#fb923c"]):
            fig.add_trace(go.Scatter(x=win.index, y=win[c], name=c,
                                      line=dict(color=color, width=1.8)))
        fig.update_layout(template=PLOTLY_THEME, height=320,
                           yaxis_title="Overnight rate (%)",
                           margin=dict(l=10, r=10, t=10, b=10),
                           legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                        xanchor="right", x=1))
        return fig

    if topic == "fx":
        try:
            import yfinance as yf
            tickers = {"EURUSD=X":"EURUSD", "USDJPY=X":"USDJPY", "GBPUSD=X":"GBPUSD"}
            fig = go.Figure()
            for sym, label in tickers.items():
                h = yf.Ticker(sym).history(period="6mo", interval="1d")
                if h.empty: continue
                norm = h["Close"] / h["Close"].iloc[0] * 100
                fig.add_trace(go.Scatter(x=norm.index, y=norm.values, name=label,
                                          line=dict(width=2)))
            fig.update_layout(template=PLOTLY_THEME, height=320,
                               yaxis_title="Indexed (100 at start)",
                               margin=dict(l=10, r=10, t=10, b=10),
                               legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                            xanchor="right", x=1))
            return fig
        except Exception:
            return None

    return None


# Pull headlines + initialise selection in session_state
try:
    from dashboard.components.news import _fetch as _rss_fetch, _fmt_date, _utm
    headlines: list[dict] = []
    for url in ("https://manveersahota.substack.com/feed",
                 "https://feeds.bloomberg.com/markets/news.rss"):
        headlines.extend(_rss_fetch(url, limit=3))
    headlines = headlines[:6]
except Exception:
    headlines = []

if "mb_selected_article" not in st.session_state and headlines:
    st.session_state["mb_selected_article"] = 0   # default to first item

left, right = st.columns([3, 2])

with left:
    # Topic resolution based on currently-selected article
    sel_idx = st.session_state.get("mb_selected_article", None)
    if sel_idx is None or sel_idx >= len(headlines):
        topic = "us_curve"
        sel_title = None
    else:
        sel_title = headlines[sel_idx]["title"]
        topic = _topic_for_title(sel_title)

    if sel_title:
        st.subheader(f"📊 {_topic_label(topic)}")
        st.caption(f"Chart picked because of selected article:  *{sel_title}*")
    else:
        st.subheader("📉 Curve snapshot")

    fig = _render_topic_chart(topic)
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(f"Chart for topic **{topic}** unavailable right now — "
                "data source missing or empty.")


with right:
    st.subheader("📰 Latest — click to load chart")
    if not headlines:
        st.caption("RSS unavailable.")
    else:
        for i, it in enumerate(headlines):
            is_selected = (i == st.session_state.get("mb_selected_article", -1))
            border_color = "#4fc3f7" if is_selected else "#1a3056"
            link = _utm(it["link"], "morning") if "manveer" in it["link"] else it["link"]
            topic_label = _topic_label(_topic_for_title(it["title"]))

            with st.container():
                st.markdown(
                    f"""
                    <div style='margin:4px 0;padding:8px 10px;
                                background:#0e1f3a;
                                border-left:3px solid {border_color};
                                border-radius:4px'>
                      <div style='color:#e8eef9;font-size:13px;font-weight:600;
                                  line-height:1.35;margin-bottom:2px'>
                          {it['title']}
                      </div>
                      <div style='color:#6a7e9e;font-size:10.5px;
                                  display:flex;justify-content:space-between'>
                          <span>{_fmt_date(it['published'])}</span>
                          <span style='color:#4fc3f7'>↪ {topic_label}</span>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                bc1, bc2 = st.columns([1, 1])
                with bc1:
                    if st.button("📊 Show chart", key=f"art_show_{i}",
                                  use_container_width=True,
                                  type=("primary" if is_selected else "secondary")):
                        st.session_state["mb_selected_article"] = i
                        st.rerun()
                with bc2:
                    st.link_button("Open ↗", link,
                                    use_container_width=True)

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
