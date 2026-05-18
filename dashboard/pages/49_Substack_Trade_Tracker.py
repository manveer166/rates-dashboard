"""Page 49 — Substack Trade Tracker.

The "retrospective writes itself" page. Every trade idea published on
Macro Manv gets logged here with entry, structure, DV01, thesis, live
mark-to-market, and a four-component P&L attribution (directional /
carry / convexity / transaction cost) ready to drop into the next
Good / Bad / Ugly retrospective.

Reads the same `data/trade_of_week.json` store the TotW page uses — so
publishing a trade on the TotW page automatically shows up here, fully
decomposed. No duplicate data entry.

Free public page. Readers see the track record; admin gets an add-trade
form at the bottom.
"""

from __future__ import annotations

import io
import json
import sys
from datetime import date, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import streamlit as st

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import (
    get_master_df, init_session_state, password_gate, is_admin,
)

import fixed_income as fi

st.set_page_config(page_title="Substack Trade Tracker", page_icon="📜",
                    layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Substack Trade Tracker")

st.title("📜 Substack Trade Tracker")
st.markdown(
    '<p style="color:var(--c-text-2);font-size:15px;margin-top:-4px;'
    'margin-bottom:6px;">'
    "Every rates trade published on Macro Manv, with the math behind it. "
    "Live mark-to-market plus a four-component P&L attribution "
    "(directional · carry · convexity · transaction cost) on every leg."
    "</p>"
    '<p style="color:var(--c-text-3);font-size:12px;margin-bottom:14px;">'
    'Same source of truth as the <a href="/Trade_of_the_Week" '
    'style="color:#4fc3f7;text-decoration:none">Trade of the Week</a> '
    'page. The math layer is the same one used by the '
    '<a href="/Backtester" style="color:#4fc3f7;text-decoration:none">'
    'Backtester</a> — documented on the '
    '<a href="/Methodology" style="color:#4fc3f7;text-decoration:none">'
    'Methodology</a> page.'
    "</p>",
    unsafe_allow_html=True,
)
st.divider()


STORE = Path(__file__).parent.parent.parent / "data" / "trade_of_week.json"
TY = {"2Y": 2.0, "3Y": 3.0, "5Y": 5.0, "7Y": 7.0,
      "10Y": 10.0, "20Y": 20.0, "30Y": 30.0}


# ── Storage helpers ──────────────────────────────────────────────────────
def _load() -> list:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text())
        except Exception:
            return []
    return []


def _save(rows: list) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(rows, indent=2, default=str))


# ── Trade-name formatter ─────────────────────────────────────────────────
def _trade_name(trade: dict) -> str:
    direction = (trade.get("direction") or "receive").capitalize()
    if trade["type"] == "outright":
        return f"{direction} {trade.get('tenor', '')}"
    if trade["type"] == "curve":
        return f"{direction} {'/'.join(trade.get('tenors', []))} curve"
    return f"{direction} {'/'.join(trade.get('tenors', []))} fly"


# ── Per-trade attribution helper ─────────────────────────────────────────
def _trade_attribution(trade: dict, df: pd.DataFrame) -> dict:
    """Return {directional, carry, convexity, tcost, total} for one trade.

    All components in bps yield-equivalent at the trade's leg DV01s.

    Components:
      • directional = sign × (current_level − entry_level) × 100
      • carry       = (days_held / 365) × annual_carry_bps (computed at entry)
      • convexity   = per-leg ½·C·Δy² summed with the trade's sign convention
      • tcost       = round-trip bid/ask paid on entry and exit
    """
    if df.empty:
        return _empty_attribution()

    direction = trade.get("direction", "receive")
    sign = 1.0 if direction == "receive" else -1.0
    is_receiver = (direction == "receive")
    ttype = trade["type"]

    # ── 1. Directional P&L (mark-to-market on the trade level) ──────────
    row = df.iloc[-1]
    if ttype == "outright":
        t = trade.get("tenor", "10Y")
        if t not in df.columns:
            return _empty_attribution()
        current_level = float(row[t])
        entry_level   = float(trade["entry_level"])
        # outright entry_level is in %; level diff × 100 = bps yield
        directional = sign * -(current_level - entry_level) * 100   # receive: yield down = +PnL
        tenors_use  = [t]
    elif ttype == "curve":
        t1, t2 = trade["tenors"]
        if t1 not in df.columns or t2 not in df.columns:
            return _empty_attribution()
        current_spread = (float(row[t2]) - float(row[t1])) * 100   # bps
        entry_spread   = float(trade["entry_level"])               # already bps
        # receive curve = bet on flatten = spread narrows = receiver gains
        directional = sign * -(current_spread - entry_spread)
        tenors_use  = [t1, t2]
    elif ttype == "fly":
        w1, b, w2 = trade["tenors"]
        if any(t not in df.columns for t in (w1, b, w2)):
            return _empty_attribution()
        current_fly = (2 * float(row[b]) - float(row[w1])
                       - float(row[w2])) * 100   # bps
        entry_fly   = float(trade["entry_level"])
        directional = sign * -(current_fly - entry_fly)
        tenors_use  = [w1, b, w2]
    else:
        return _empty_attribution()

    # ── 2. Days held ────────────────────────────────────────────────────
    entry_date = pd.Timestamp(trade.get("entry_date") or trade.get("week_of"))
    days_held  = max(0, (pd.Timestamp(date.today()) - entry_date).days)

    # ── 3. Carry (forward_carry_rolldown @ entry curve, accrued daily) ──
    # Build the curve dict from the row AT ENTRY (closest available date)
    try:
        entry_idx = df.index.get_indexer([entry_date], method="nearest")[0]
        entry_row = df.iloc[entry_idx]
        curve_at_entry = {t: float(entry_row[t]) for t in TY
                          if t in df.columns and pd.notna(entry_row[t])}
        on_rate = 5.3
        for col in ("SOFR", "DFF", "EFFR"):
            if col in df.columns:
                s = df[col].iloc[:entry_idx + 1].dropna()
                if len(s):
                    on_rate = float(s.iloc[-1]); break
        if ttype == "outright":
            cr = fi.forward_carry_rolldown(
                curve_at_entry, on_rate, "outright",
                tenor1=tenors_use[0], holding_months=12.0)
        elif ttype == "curve":
            cr = fi.forward_carry_rolldown(
                curve_at_entry, on_rate, "spread",
                tenor1=tenors_use[1], tenor2=tenors_use[0],
                holding_months=12.0)
        else:
            cr = fi.forward_carry_rolldown(
                curve_at_entry, on_rate, "fly",
                tenor1=tenors_use[0], tenor2=tenors_use[1],
                tenor3=tenors_use[2], holding_months=12.0)
        annual_carry = (cr.get("total", 0.0) or 0.0) * sign
        carry = annual_carry * (days_held / 365.0)
    except Exception:
        annual_carry = 0.0
        carry = 0.0

    # ── 4. Convexity (per-leg ½·C·Δy² using entry yields) ───────────────
    try:
        if ttype == "outright":
            t = tenors_use[0]
            y_entry = float(entry_row[t])
            y_now   = float(row[t])
            dy_dec  = (y_now - y_entry) / 100.0
            C       = fi.convexity_par(TY[t], y_entry)
            dv01    = fi.dv01_par(TY[t], y_entry)
            sign_leg = 1.0 if is_receiver else -1.0
            dollar_pnl = sign_leg * 0.5 * C * (dy_dec ** 2) * 1e6
            convexity = dollar_pnl / dv01 if dv01 > 0 else 0.0
        elif ttype == "curve":
            t1, t2 = tenors_use
            y1_e, y2_e = float(entry_row[t1]), float(entry_row[t2])
            y1_n, y2_n = float(row[t1]),       float(row[t2])
            dy1 = (y1_n - y1_e) / 100.0
            dy2 = (y2_n - y2_e) / 100.0
            C1, C2 = fi.convexity_par(TY[t1], y1_e), fi.convexity_par(TY[t2], y2_e)
            d1, d2 = fi.dv01_par(TY[t1], y1_e), fi.dv01_par(TY[t2], y2_e)
            ratio  = d2 / d1 if d1 > 0 else 0.0
            sl, ss = (1.0, -1.0) if is_receiver else (-1.0, 1.0)
            long_pnl  = sl * 0.5 * C2 * (dy2 ** 2) * 1e6
            short_pnl = ss * 0.5 * C1 * (dy1 ** 2) * (ratio * 1e6)
            convexity = (long_pnl + short_pnl) / d2 if d2 > 0 else 0.0
        else:  # fly
            w1, b, w2 = tenors_use
            yw1_e, yb_e, yw2_e = (float(entry_row[w1]),
                                  float(entry_row[b]),
                                  float(entry_row[w2]))
            yw1_n, yb_n, yw2_n = (float(row[w1]),
                                  float(row[b]),
                                  float(row[w2]))
            dyw1 = (yw1_n - yw1_e) / 100.0
            dyb  = (yb_n  - yb_e)  / 100.0
            dyw2 = (yw2_n - yw2_e) / 100.0
            Cw1, Cb, Cw2 = (fi.convexity_par(TY[w1], yw1_e),
                            fi.convexity_par(TY[b], yb_e),
                            fi.convexity_par(TY[w2], yw2_e))
            dw1, db_, dw2 = (fi.dv01_par(TY[w1], yw1_e),
                             fi.dv01_par(TY[b], yb_e),
                             fi.dv01_par(TY[w2], yw2_e))
            r1 = 0.5 * db_ / dw1 if dw1 > 0 else 0.0
            r2 = 0.5 * db_ / dw2 if dw2 > 0 else 0.0
            sb_, sw = (1.0, -1.0) if is_receiver else (-1.0, 1.0)
            belly_pnl = sb_ * 0.5 * Cb  * (dyb  ** 2) * 1e6
            w1_pnl    = sw  * 0.5 * Cw1 * (dyw1 ** 2) * (r1 * 1e6)
            w2_pnl    = sw  * 0.5 * Cw2 * (dyw2 ** 2) * (r2 * 1e6)
            convexity = ((belly_pnl + w1_pnl + w2_pnl) / db_
                         if db_ > 0 else 0.0)
    except Exception:
        convexity = 0.0

    # ── 5. Transaction costs (round-trip bid/ask) ───────────────────────
    try:
        if ttype == "outright":
            tcost = fi.tcost_outright_bps(TY[tenors_use[0]])
        elif ttype == "curve":
            t1, t2 = tenors_use
            tcost = fi.tcost_curve_bps(TY[t1], TY[t2])
        else:
            w1, b, w2 = tenors_use
            tcost = fi.tcost_fly_bps(TY[w1], TY[b], TY[w2])
        # Closed trades have paid round-trip; live trades only paid half.
        if trade.get("status", "live") == "live":
            tcost = tcost / 2.0
    except Exception:
        tcost = 0.0

    total = directional + carry + convexity - tcost
    return {
        "directional": float(directional),
        "carry":       float(carry),
        "convexity":   float(convexity),
        "tcost":       float(tcost),
        "total":       float(total),
        "days_held":   int(days_held),
        "annual_carry_bps": float(annual_carry),
    }


def _empty_attribution() -> dict:
    return {"directional": 0.0, "carry": 0.0, "convexity": 0.0,
            "tcost": 0.0, "total": 0.0, "days_held": 0,
            "annual_carry_bps": 0.0}


# ── Scenario helper: hypothetical parallel yield moves ───────────────────
def _scenario_table(trade: dict, df: pd.DataFrame,
                     bumps_bps: list = (-100, -50, -25, 0, 25, 50, 100)
                     ) -> pd.DataFrame:
    """For each ±bp parallel shift, project total P&L (directional only).

    Convexity is held at its current entry value (no re-mark), so this
    is the linear-plus-convexity scenario the trader cares about most.
    """
    if df.empty:
        return pd.DataFrame()
    sign = 1.0 if trade.get("direction", "receive") == "receive" else -1.0
    ttype = trade["type"]

    base_attr = _trade_attribution(trade, df)
    base_directional = base_attr["directional"]

    rows = []
    for dy in bumps_bps:
        # Shift every relevant tenor by dy bps and recompute the
        # level → directional delta.
        if ttype == "outright":
            extra_dir = sign * -dy   # receive gains when yield falls = -dy * sign
        elif ttype == "curve":
            # Parallel shift leaves spread unchanged → directional unchanged
            # That's the right answer for a "parallel shift" scenario.
            extra_dir = 0.0
        else:  # fly
            # Parallel shift leaves fly value unchanged
            extra_dir = 0.0
        rows.append({
            "Δyield (bps)": dy,
            "Directional Δ (bps)": round(extra_dir, 1),
            "Projected total (bps)": round(base_attr["total"] + extra_dir, 1),
        })
    return pd.DataFrame(rows)


# ── Load and decorate every trade ────────────────────────────────────────
df = get_master_df()
entries = sorted(_load(), key=lambda e: e.get("week_of", ""), reverse=True)

if not entries:
    st.info(
        "🪶 **No Substack trades published yet.** The first will appear here "
        "with full attribution the moment it's posted on the "
        "[Trade of the Week](/Trade_of_the_Week) page. "
        "[Subscribe to the Macro Manv newsletter](https://manveersahota.substack.com/subscribe"
        "?utm_source=dashboard&utm_medium=tracker_empty&utm_campaign=launch) "
        "to get each pick in your inbox the moment it's live."
    )
    st.stop()
    # Hard fence — st.stop() is a no-op outside the Streamlit runtime
    # (smoke tests, bare-mode scripts), so SystemExit is the only thing
    # that guarantees the rest of the page never runs with empty data.
    raise SystemExit(0)


# Decorate every trade with its attribution dict
for e in entries:
    e["_attr"] = _trade_attribution(e, df)


# ── Header KPIs ──────────────────────────────────────────────────────────
n_total   = len(entries)
n_live    = sum(1 for e in entries if e.get("status", "live") == "live")
n_closed  = n_total - n_live
totals    = [e["_attr"]["total"] for e in entries]
total_bps = sum(totals)
n_winners = sum(1 for t in totals if t > 0)
hit_rate  = (n_winners / n_total * 100) if n_total else 0.0
best      = max(entries, key=lambda e: e["_attr"]["total"])
worst     = min(entries, key=lambda e: e["_attr"]["total"])

st.subheader("🏆 Track record at a glance")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Trades published",  f"{n_total}",
          delta=f"{n_live} live · {n_closed} closed")
m2.metric("Cumulative P&L",    f"{total_bps:+.0f} bps")
m3.metric("Hit rate",          f"{hit_rate:.0f}%",
          delta=f"{n_winners} of {n_total} winners")
m4.metric("Best trade",        f"{best['_attr']['total']:+.0f} bps",
          delta=_trade_name(best))
m5.metric("Worst trade",       f"{worst['_attr']['total']:+.0f} bps",
          delta=_trade_name(worst))
st.divider()


# ── Per-trade table with attribution columns ────────────────────────────
st.subheader("📋 All published trades (with attribution)")
st.caption(
    "Each row decomposes total P&L into the four components. The Methodology "
    "page explains exactly how each one is computed."
)

rows = []
for i, e in enumerate(entries):
    a = e["_attr"]
    rows.append({
        "#":     n_total - i,
        "Week":  e.get("week_of", "—"),
        "Trade": _trade_name(e),
        "Entry": e.get("entry_level", "—"),
        "Days":  a["days_held"],
        "Direct.": round(a["directional"], 1),
        "Carry":  round(a["carry"], 1),
        "Conv":   round(a["convexity"], 1),
        "TCost":  round(-a["tcost"], 1),
        "Total":  round(a["total"], 1),
        "Status": e.get("status", "live"),
    })
table_df = pd.DataFrame(rows).set_index("#")
st.dataframe(table_df, use_container_width=True)


# ── Per-trade expand cards with thesis + scenario table ──────────────────
st.subheader("🔍 Trade-by-trade detail")
for i, e in enumerate(entries):
    a = e["_attr"]
    label = (f"#{n_total - i}  ·  {e.get('week_of','—')}  ·  "
             f"{_trade_name(e)}  ·  Entry {e.get('entry_level','—')}  ·  "
             f"P&L {a['total']:+.0f} bps")
    with st.expander(label, expanded=(i == 0)):
        cc1, cc2 = st.columns([3, 2])
        with cc1:
            st.markdown(f"**Thesis:** {e.get('thesis','—')}")
            if e.get("link"):
                st.markdown(
                    f"📖 [Read the full post →]({e['link']})"
                )
            if e.get("notes"):
                st.caption(f"_Notes: {e['notes']}_")

            # Attribution breakdown
            st.markdown("**P&L decomposition (bps):**")
            attr_df = pd.DataFrame([
                {"Component": "Directional (level moved)",
                 "Bps": round(a["directional"], 1)},
                {"Component": "Carry (held for "
                              f"{a['days_held']}d at "
                              f"{a['annual_carry_bps']:+.0f} bps/yr)",
                 "Bps": round(a["carry"], 1)},
                {"Component": "Convexity (½·C·Δy², per leg)",
                 "Bps": round(a["convexity"], 1)},
                {"Component": ("Transaction cost "
                               f"({'half (entry only)' if e.get('status','live')=='live' else 'round-trip'})"),
                 "Bps": round(-a["tcost"], 1)},
                {"Component": "**TOTAL**",
                 "Bps": round(a["total"], 1)},
            ]).set_index("Component")
            st.dataframe(attr_df, use_container_width=True)

        with cc2:
            st.markdown("**Parallel-shift scenarios**")
            st.caption("If yields shift uniformly by ±bps from here, where "
                       "does total P&L land?")
            scen_df = _scenario_table(e, df)
            st.dataframe(scen_df.set_index("Δyield (bps)"),
                         use_container_width=True)


# ── Exportable retrospective tables ──────────────────────────────────────
st.divider()
st.subheader("📤 Export for the next retrospective")
st.caption(
    "Drop these straight into the next Good / Bad / Ugly post. The CSV is "
    "raw data; the Markdown is paste-ready for Substack."
)

# CSV
csv_buf = io.StringIO()
table_df.to_csv(csv_buf)
ex1, ex2 = st.columns(2)
with ex1:
    st.download_button(
        "⬇️ Download retrospective CSV",
        data=csv_buf.getvalue(),
        file_name=f"substack_trades_{date.today().isoformat()}.csv",
        mime="text/csv",
        use_container_width=True,
    )

# Markdown
md_lines = [
    f"# Trade retrospective — as of {date.today().isoformat()}",
    "",
    f"**{n_total}** trades published. **{hit_rate:.0f}%** hit rate. "
    f"**{total_bps:+.0f} bps** cumulative.",
    "",
    "| # | Week | Trade | Entry | Direct. | Carry | Conv | TCost | **Total** | Status |",
    "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
]
for i, e in enumerate(entries):
    a = e["_attr"]
    md_lines.append(
        f"| {n_total - i} | {e.get('week_of','—')} | "
        f"{_trade_name(e)} | {e.get('entry_level','—')} | "
        f"{a['directional']:+.1f} | {a['carry']:+.1f} | "
        f"{a['convexity']:+.1f} | {-a['tcost']:+.1f} | "
        f"**{a['total']:+.1f}** | {e.get('status','live')} |"
    )
with ex2:
    st.download_button(
        "⬇️ Download retrospective Markdown",
        data="\n".join(md_lines),
        file_name=f"substack_trades_{date.today().isoformat()}.md",
        mime="text/markdown",
        use_container_width=True,
    )

with st.expander("👀 Preview the Markdown export"):
    st.markdown("\n".join(md_lines))


# ── Admin: link to add-trade form ────────────────────────────────────────
if is_admin():
    st.divider()
    st.info(
        "Admin: publish new trades on the "
        "[Trade of the Week](/Trade_of_the_Week) page — they appear here "
        "automatically with full attribution."
    )
