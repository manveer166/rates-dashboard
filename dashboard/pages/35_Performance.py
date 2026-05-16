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
        "_raw":        p,   # keep original pick dict for the signal-card view
        "_summary":    s,
    })
    # Build daily-PnL series labelled by (week_of, name) for stitching
    daily = pnl.diff().fillna(0.0)
    daily.name = name
    all_daily.append(daily)

if not records:
    st.warning("Picks found but couldn't compute PnL — yields data may be missing.")
    st.stop()
    # Defensive: st.stop() doesn't actually stop in bare/test mode. Hard
    # fence so smoke tests + the if-records-was-empty path don't crash on
    # the missing-column references further down.
    raise SystemExit(0)

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

# ── Per-pick cards (most recent first) ───────────────────────────────────
st.subheader("🃏 Pick-by-pick — signal cards")
from dashboard.components.signal_card import render_signal_grid

card_payloads = []
for rec in sorted(records, key=lambda r: r["Week of"], reverse=True):
    p = rec["_raw"]; s = rec["_summary"]
    type_label = {"outright": "Outright", "curve": "Curve", "fly": "Fly"}.get(p["type"], "Outright")
    tenor_str = p.get("tenor") if p["type"] == "outright" else "/".join(p.get("tenors", []))
    prefix = "Rcv" if p.get("direction", "receive") == "receive" else "Pay"
    card_payloads.append(dict(
        trade=f"{prefix} {tenor_str}",
        type_=type_label,
        sharpe=float(s.get("sharpe", 0)),
        z=0.0,   # not part of TotW model
        expected_return_bps_yr=(s.get("total_bps", 0) * 365 / max(s.get("days", 1), 1)),
        hit_rate_pct=float(s.get("hit_rate", 0)),
        max_dd_bps=float(s.get("max_dd", 0)),
        days=int(s.get("days", 0)),
        direction=p.get("direction", "receive"),
        tags=[f"Week of {p.get('week_of', '?')}",
              f"Status: {p.get('status', 'live')}",
              f"Entry: {p.get('entry_level', '—')}"],
        note=(f"PnL <b>{s.get('total_bps', 0):+.1f} bps</b> over {s.get('days', 0)} days. "
              + (f'<a href="{p["link"]}" target="_blank" style="color:#4fc3f7">Write-up →</a>'
                 if p.get("link") else "")),
    ))
render_signal_grid(card_payloads, n_cols=2, compact=True)


# ── Per-pick table — still available for power users ─────────────────────
# ── PnL attribution for closed picks (level/curve/curvature/carry) ──────
st.subheader("🔍 PnL attribution — closed picks")
st.caption(
    "Decomposes each closed pick's mark-to-market PnL into 4 components:  "
    "**Level** (parallel curve shift over the holding period), "
    "**Curve** (2s10s reshape), "
    "**Curvature** (2/5/10 belly fly reshape), "
    "**Residual** (everything else — carry, roll, idiosyncratic). "
    "Identifies whether your picks made money for the right reason."
)


def _attribute_pnl(p: dict) -> dict | None:
    """Decompose realised PnL of a pick into level/curve/curvature/residual."""
    tenors = [p["tenor"]] if p["type"] == "outright" else p["tenors"]
    if any(t not in df.columns for t in tenors):
        return None
    entry_d = pd.to_datetime(p.get("entry_date") or p.get("week_of"))
    end_d   = pd.to_datetime(p.get("closed_date")) if p.get("status") == "closed" else \
              pd.Timestamp(date.today())
    sub = df.loc[entry_d:end_d]
    if sub.empty: return None

    # Total realised PnL (level change)
    if p["type"] == "outright":
        lvl = df[tenors[0]].dropna()
    elif p["type"] == "curve":
        lvl = (df[tenors[1]] - df[tenors[0]]).dropna()
    else:
        lvl = (2 * df[tenors[1]] - df[tenors[0]] - df[tenors[2]]).dropna()
    sub_l = lvl.loc[entry_d:end_d]
    if sub_l.empty: return None
    sign = -1.0 if p.get("direction", "receive") == "receive" else 1.0
    total_pnl = sign * (sub_l.iloc[-1] - sub_l.iloc[0]) * 100  # bps

    # Decompose factors over the same window
    # Level factor = avg parallel shift across 2/5/10/30 (in bps)
    factors_d_bps = {}
    pcs = ["2Y", "5Y", "10Y", "30Y"]
    if all(t in sub.columns for t in pcs) and not sub.empty:
        first = sub[pcs].dropna(how="all").iloc[0]
        last  = sub[pcs].dropna(how="all").iloc[-1]
        # Level: mean change across all tenors
        factors_d_bps["level_bps"]    = float((last - first).mean() * 100)
        # Curve (2s10s): change in (10Y - 2Y)
        factors_d_bps["curve_bps"]    = float(((last["10Y"] - last["2Y"]) -
                                                  (first["10Y"] - first["2Y"])) * 100)
        # Curvature (2/5/10 fly): change in (2*5Y - 2Y - 10Y)
        factors_d_bps["curvature_bps"] = float(((2*last["5Y"] - last["2Y"] - last["10Y"]) -
                                                  (2*first["5Y"] - first["2Y"] - first["10Y"])) * 100)
    else:
        factors_d_bps = {"level_bps": 0, "curve_bps": 0, "curvature_bps": 0}

    # Sensitivity: how does the pick's level change with each factor?
    # We use simple regression coefficients on historical daily changes
    common = lvl.loc[entry_d - pd.Timedelta(days=300):end_d].dropna()
    if all(t in df.columns for t in pcs) and len(common) > 60:
        hist = df.loc[common.index, pcs].dropna()
        common = common.reindex(hist.index)
        # Daily changes
        dl = common.diff().dropna() * 100  # pick level change in bps
        dh = hist.diff().dropna() * 100
        common2 = dl.index.intersection(dh.index)
        if len(common2) > 30:
            dl = dl.loc[common2]
            level_f = dh.loc[common2][pcs].mean(axis=1)
            curve_f = dh.loc[common2]["10Y"] - dh.loc[common2]["2Y"]
            curv_f  = 2 * dh.loc[common2]["5Y"] - dh.loc[common2]["2Y"] - dh.loc[common2]["10Y"]
            X = np.column_stack([level_f.values, curve_f.values, curv_f.values])
            try:
                beta, *_ = np.linalg.lstsq(X, dl.values, rcond=None)
            except Exception:
                beta = np.array([0.0, 0.0, 0.0])
        else:
            beta = np.array([0.0, 0.0, 0.0])
    else:
        beta = np.array([0.0, 0.0, 0.0])

    # Predicted attribution: beta · factor_change, signed by direction
    level_pnl     = sign * beta[0] * factors_d_bps["level_bps"]
    curve_pnl     = sign * beta[1] * factors_d_bps["curve_bps"]
    curvature_pnl = sign * beta[2] * factors_d_bps["curvature_bps"]
    residual_pnl  = total_pnl - (level_pnl + curve_pnl + curvature_pnl)

    return {
        "total":      total_pnl,
        "level":      level_pnl,
        "curve":      curve_pnl,
        "curvature":  curvature_pnl,
        "residual":   residual_pnl,
    }


closed_picks_raw = [rec["_raw"] for rec in records
                     if rec.get("_raw", {}).get("status") == "closed"]
if closed_picks_raw:
    attr_rows = []
    for p in closed_picks_raw:
        a = _attribute_pnl(p)
        if a is None: continue
        attr_rows.append({
            "Trade":         f"{p.get('direction','receive').capitalize()} "
                              f"{p.get('tenor', '/'.join(p.get('tenors', [])))}",
            "Closed":        p.get("closed_date", "—"),
            "Total (bps)":   round(a["total"], 1),
            "Level (bps)":   round(a["level"], 1),
            "Curve (bps)":   round(a["curve"], 1),
            "Curvature (bps)": round(a["curvature"], 1),
            "Residual (bps)":  round(a["residual"], 1),
        })
    if attr_rows:
        st.dataframe(
            pd.DataFrame(attr_rows).set_index("Trade"),
            use_container_width=True,
            column_config={
                "Total (bps)":     st.column_config.NumberColumn(format="%+.1f"),
                "Level (bps)":     st.column_config.NumberColumn(format="%+.1f"),
                "Curve (bps)":     st.column_config.NumberColumn(format="%+.1f"),
                "Curvature (bps)": st.column_config.NumberColumn(format="%+.1f"),
                "Residual (bps)":  st.column_config.NumberColumn(format="%+.1f"),
            },
        )
        st.caption(
            "If **Residual** is a big share of Total, the pick made (or lost) money for "
            "reasons outside curve factor moves — likely carry / roll / micro-structure."
        )
else:
    st.info(
        "Attribution shows up here once you close out at least one Trade of the Week. "
        "Until then, refer to the **🃏 Pick-by-pick** signal cards above for live PnL on open picks."
    )


st.divider()

st.subheader("📋 Pick-by-pick — full table")
disp = picks_df.drop(columns=[c for c in ["_raw", "_summary"] if c in picks_df.columns]) \
                .sort_values("Week of", ascending=False)
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
