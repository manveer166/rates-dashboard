"""Page 35 — Performance Attribution.

Public-facing track record for every Trade-of-the-Week pick: cumulative PnL,
hit rate, win/loss stats, signal-by-signal table.  This is your subscriber
credibility play — every visitor can see whether the picks have actually
made money.

Data: `data/trade_of_week.json` (same store the TotW page writes to).
PnL math: same convention as Backtester (receive PnL = -d(level)*100).
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import get_master_df, init_session_state, password_gate

st.set_page_config(page_title="Performance", page_icon="🏆", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Performance")

st.title("🏆 Performance — Trade of the Week")
st.caption(
    "Live and closed-out track record. Every pick from the Trade-of-the-Week "
    "page, marked-to-market against the same yield series the scanner uses."
)
st.divider()


STORE = Path(__file__).parent.parent.parent / "data" / "trade_of_week.json"


def _load_picks() -> list[dict]:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text())
        except Exception:
            return []
    return []


def _level_at(df: pd.DataFrame, ttype: str, tenors, when: date) -> float | None:
    """Return the structure level on a given date (or last available before)."""
    if df.empty: return None
    try:
        idx = df.index.searchsorted(pd.Timestamp(when), side="right") - 1
        if idx < 0: return None
        row = df.iloc[idx]
        if ttype == "outright":
            return float(row[tenors[0]])
        if ttype == "curve":
            t1, t2 = tenors
            return float(row[t2] - row[t1])
        # fly: 2*belly - w1 - w2 (simple, not DV01-weighted — same as Backtester)
        w1, b, w2 = tenors
        return float(2 * row[b] - row[w1] - row[w2])
    except Exception:
        return None


def _pnl_series(df: pd.DataFrame, pick: dict) -> pd.Series | None:
    """Daily cumulative PnL series (bps) from entry through today (or close)."""
    ttype = pick["type"]
    tenors = [pick["tenor"]] if ttype == "outright" else pick["tenors"]
    if any(t not in df.columns for t in tenors): return None

    if ttype == "outright":
        lvl = df[tenors[0]].dropna()
    elif ttype == "curve":
        lvl = (df[tenors[1]] - df[tenors[0]]).dropna()
    else:
        lvl = (2 * df[tenors[1]] - df[tenors[0]] - df[tenors[2]]).dropna()

    entry_d = pd.to_datetime(pick.get("entry_date") or pick.get("week_of"))
    end_d   = pd.to_datetime(pick.get("closed_date")) if pick.get("status") == "closed" \
              else pd.Timestamp(date.today())
    sub = lvl.loc[entry_d:end_d]
    if sub.empty: return None
    sign = -1.0 if pick.get("direction", "receive") == "receive" else 1.0
    return sign * (sub - sub.iloc[0]) * 100   # bps from entry


def _summary_stats(pnl: pd.Series) -> dict:
    if pnl.empty: return {}
    daily = pnl.diff().dropna()
    if len(daily) < 2:
        return {"days": len(pnl), "total_bps": float(pnl.iloc[-1])}
    return {
        "days":         int(len(pnl)),
        "total_bps":    float(pnl.iloc[-1]),
        "ann_bps":      float(daily.mean() * 252),
        "vol_bps":      float(daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0,
        "sharpe":       (float(daily.mean() / daily.std() * np.sqrt(252))
                          if daily.std() > 0 else 0.0),
        "hit_rate":     float((daily > 0).mean() * 100),
        "max_dd":       float((pnl - pnl.cummax()).min()),
    }


# ── Load picks + master ──────────────────────────────────────────────────
picks = _load_picks()
df    = get_master_df()

if not picks:
    st.info(
        "**No Trade-of-the-Week picks published yet.**\n\n"
        "Once you publish picks via the 🎯 Trade of the Week page, this page "
        "will track every one of them mark-to-market — cumulative PnL, hit rate, "
        "max drawdown, win/loss stats. It's the credibility view subscribers "
        "see when they want proof the picks work."
    )
    st.stop()


# ── Compute PnL per pick ─────────────────────────────────────────────────
records = []
all_daily: list[pd.Series] = []
for p in picks:
    pnl = _pnl_series(df, p)
    if pnl is None or pnl.empty: continue
    s = _summary_stats(pnl)
    name = (f"{p.get('direction','receive').capitalize()} {p.get('tenor','')}"
            if p["type"] == "outright"
            else f"{p.get('direction','receive').capitalize()} "
                  f"{'/'.join(p.get('tenors', []))}"
                  f"{' fly' if p['type']=='fly' else ' curve'}")
    records.append({
        "Trade":      name,
        "Week of":    p.get("week_of", ""),
        "Status":     p.get("status", "live"),
        "Days held":  s.get("days", 0),
        "PnL (bps)":  round(s.get("total_bps", 0), 1),
        "Sharpe":     round(s.get("sharpe", 0), 2),
        "Hit rate %": round(s.get("hit_rate", 0), 0),
        "Max DD bps": round(s.get("max_dd", 0), 1),
    })
    # Build daily-PnL series labelled by (week_of, name) for stitching
    daily = pnl.diff().fillna(0.0)
    daily.name = name
    all_daily.append(daily)

if not records:
    st.warning("Picks found but couldn't compute PnL — yields data may be missing.")
    st.stop()

picks_df = pd.DataFrame(records)


# ── Aggregate stats ──────────────────────────────────────────────────────
n_total  = len(picks_df)
n_live   = int((picks_df["Status"] == "live").sum())
n_closed = int((picks_df["Status"] == "closed").sum())
n_winners = int((picks_df["PnL (bps)"] > 0).sum())
total_bps = float(picks_df["PnL (bps)"].sum())
avg_win   = float(picks_df.loc[picks_df["PnL (bps)"] > 0, "PnL (bps)"].mean()) if n_winners else 0.0
losers    = picks_df.loc[picks_df["PnL (bps)"] < 0, "PnL (bps)"]
avg_loss  = float(losers.mean()) if not losers.empty else 0.0

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Picks",          f"{n_total}")
m2.metric("Live",           f"{n_live}")
m3.metric("Closed",         f"{n_closed}")
m4.metric("Winners",        f"{n_winners}/{n_total}",
          f"{n_winners/n_total*100:.0f}%" if n_total else "—")
m5.metric("Total PnL",      f"{total_bps:+.0f} bps")
m6.metric("Avg win / loss", f"{avg_win:+.0f} / {avg_loss:+.0f} bps")

st.divider()

# ── Cumulative PnL chart (sum across all picks, treated as portfolio) ────
st.subheader("📈 Cumulative portfolio PnL")
st.caption("Sum of every pick's mark-to-market PnL, treated as a 1-unit-per-pick portfolio.")
if all_daily:
    # Align by date
    daily_df = pd.concat(all_daily, axis=1).fillna(0.0)
    portfolio = daily_df.sum(axis=1).cumsum()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=portfolio.index, y=portfolio.values, name="Portfolio",
        line=dict(color="#4ade80" if portfolio.iloc[-1] >= 0 else "#f87171", width=2.5),
        fill="tozeroy",
        fillcolor=("rgba(74,222,128,0.10)" if portfolio.iloc[-1] >= 0
                    else "rgba(248,113,113,0.10)"),
    ))
    fig.add_hline(y=0, line_dash="dot", line_color="#94a8c9")
    fig.update_layout(template=PLOTLY_THEME, height=380,
                      margin=dict(l=10, r=10, t=10, b=10),
                      yaxis_title="Cumulative PnL (bps)")
    st.plotly_chart(fig, use_container_width=True)

# ── Per-pick table ───────────────────────────────────────────────────────
st.subheader("📋 Pick-by-pick")
disp = picks_df.sort_values("Week of", ascending=False)
st.dataframe(
    disp, use_container_width=True, hide_index=True,
    column_config={
        "PnL (bps)":  st.column_config.NumberColumn(format="%+.1f"),
        "Sharpe":     st.column_config.NumberColumn(format="%+.2f"),
        "Hit rate %": st.column_config.NumberColumn(format="%.0f"),
        "Max DD bps": st.column_config.NumberColumn(format="%.1f"),
    },
)

# ── Win / loss distribution ──────────────────────────────────────────────
with st.expander("📊 Win/loss distribution (closed picks)"):
    closed = picks_df[picks_df["Status"] == "closed"]
    if closed.empty:
        st.caption("No closed picks yet.")
    else:
        fig2 = go.Figure(go.Histogram(x=closed["PnL (bps)"].values,
                                       nbinsx=20, marker_color="#4fc3f7"))
        fig2.add_vline(x=0, line_dash="dot", line_color="#94a8c9")
        fig2.update_layout(template=PLOTLY_THEME, height=300,
                            margin=dict(l=10, r=10, t=10, b=10),
                            xaxis_title="PnL per pick (bps)",
                            yaxis_title="Picks")
        st.plotly_chart(fig2, use_container_width=True)

st.divider()
st.caption(
    "PnL is mark-to-market only — no transaction costs, no DV01 sizing across "
    "picks (each pick treated as one unit). For sized PnL, use the Backtester."
)
