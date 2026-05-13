"""Page 19 — Trade of the Week.

Curated, admin-published trade pick with a thesis, live PnL tracking, and a
historical archive for credibility.  Subscribers see the latest entry on the
top; admin sees a write form to publish the next pick.
"""

from __future__ import annotations  # PEP 604 unions on Python 3.9

import json
import sys
from datetime import date, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import (
    get_master_df, init_session_state, password_gate, is_admin,
)

st.set_page_config(page_title="Trade of the Week", page_icon="🎯", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Trade of the Week")

st.title("🎯 Trade of the Week")
st.caption("Hand-picked rates trade with thesis, entry level, and tracked PnL.")
st.divider()

STORE = Path(__file__).parent.parent.parent / "data" / "trade_of_week.json"

# ── Storage helpers ───────────────────────────────────────────────────────
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

# ── PnL helper ────────────────────────────────────────────────────────────
def _pnl_bps(entry: dict, df: pd.DataFrame) -> float | None:
    """Compute current PnL in bps for a curve / outright trade.

    Trade format examples:
      {"type":"outright","tenor":"10Y","direction":"receive","entry_level":4.31}
      {"type":"curve","tenors":["2Y","10Y"],"direction":"receive","entry_level":52.0}
      {"type":"fly","tenors":["2Y","5Y","10Y"],"direction":"receive","entry_level":-15.0}
    """
    try:
        if df.empty:
            return None
        row = df.iloc[-1]
        if entry["type"] == "outright":
            t = entry["tenor"]
            if t not in df.columns:
                return None
            current = float(row[t]) * 100  # bps
            entry_lvl = float(entry["entry_level"]) * 100
            move = current - entry_lvl
            # 'receive' makes money when yield falls
            return -move if entry["direction"] == "receive" else move
        if entry["type"] == "curve":
            t1, t2 = entry["tenors"]
            if t1 not in df.columns or t2 not in df.columns:
                return None
            current = (float(row[t2]) - float(row[t1])) * 100
            entry_lvl = float(entry["entry_level"])
            move = current - entry_lvl
            # receive curve = receive long-end vs pay front-end → makes money
            # when curve flattens (long < front), i.e. spread narrows
            return -move if entry["direction"] == "receive" else move
        if entry["type"] == "fly":
            t1, t2, t3 = entry["tenors"]
            if any(t not in df.columns for t in (t1, t2, t3)):
                return None
            current = (2 * float(row[t2]) - float(row[t1]) - float(row[t3])) * 100
            entry_lvl = float(entry["entry_level"])
            move = current - entry_lvl
            return -move if entry["direction"] == "receive" else move
    except Exception:
        return None

# ── Render ────────────────────────────────────────────────────────────────
df = get_master_df()
entries = sorted(_load(), key=lambda e: e.get("week_of", ""), reverse=True)

if entries:
    latest = entries[0]
    st.subheader(f"📌 This week — {latest.get('week_of', '')}")

    # Compute live PnL + days held for the hero card
    pnl = _pnl_bps(latest, df)
    entry_date = pd.Timestamp(latest.get("entry_date") or latest.get("week_of"))
    days_held = (pd.Timestamp(date.today()) - entry_date).days

    # Card-ready trade name
    if latest["type"] == "outright":
        trade_str = f"Rcv {latest['tenor']}" if latest.get("direction", "receive") == "receive" \
                    else f"Pay {latest['tenor']}"
        type_label = "Outright"
    elif latest["type"] == "curve":
        prefix = "Rcv" if latest.get("direction", "receive") == "receive" else "Pay"
        trade_str = f"{prefix} {'/'.join(latest['tenors'])}"
        type_label = "Curve"
    else:
        prefix = "Rcv" if latest.get("direction", "receive") == "receive" else "Pay"
        trade_str = f"{prefix} {'/'.join(latest['tenors'])}"
        type_label = "Fly"

    # Hero signal card
    from dashboard.components.signal_card import (
        render_signal_card, render_units_legend,
    )
    note = latest.get("thesis", "")
    if latest.get("link"):
        note += f'<br><a href="{latest["link"]}" target="_blank" '\
                f'style="color:#4fc3f7;font-weight:600;text-decoration:none">'\
                f'Read the full write-up →</a>'

    render_signal_card(
        trade=trade_str,
        type_=type_label,
        sharpe=0.0,   # not part of the TotW model — left blank in the card
        z=0.0,
        expected_return_bps_yr=(pnl * 365 / max(days_held, 1)) if pnl is not None else None,
        d1w_bps=pnl if pnl is not None and days_held <= 7 else None,
        days=days_held,
        direction=latest.get("direction", "receive"),
        tags=["Trade of the Week", f"Entry {latest.get('entry_date','—')}",
              f"Status {latest.get('status','live')}"],
        note=note or None,
    )

    # Live PnL stand-out metric (still useful at-a-glance above the chart)
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Live PnL (bps)", f"{pnl:+.1f}" if pnl is not None else "—",
                delta=f"vs entry {latest.get('entry_level','—')}")
    mc2.metric("Days held", days_held)
    mc3.metric("Annualised PnL (bps/yr)",
                f"{(pnl * 365 / max(days_held, 1)):+.0f}" if pnl is not None and days_held > 0 else "—")

    with st.expander("Units key"):
        render_units_legend()
    st.divider()

    if len(entries) > 1:
        st.subheader("📚 Past picks")
        rows = []
        for e in entries[1:]:
            pnl = _pnl_bps(e, df)
            rows.append({
                "Week of":  e.get("week_of", ""),
                "Trade":    (f"{e.get('direction','receive').capitalize()} "
                             f"{e.get('tenor', '/'.join(e.get('tenors', [])))}"),
                "Entry":    e.get("entry_level", "—"),
                "PnL bps":  f"{pnl:+.1f}" if pnl is not None else "—",
                "Status":   e.get("status", "live"),
                "Notes":    e.get("notes", ""),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.info("No trade of the week published yet.")

# ── Admin write form ──────────────────────────────────────────────────────
if is_admin():
    st.divider()
    with st.expander("✏️ Admin — publish next pick", expanded=False):
        with st.form("totw_publish"):
            ttype = st.selectbox("Type", ["outright", "curve", "fly"])
            direction = st.selectbox("Direction", ["receive", "pay"])

            tenors = st.multiselect(
                "Tenor(s) — pick 1 (outright), 2 (curve), or 3 (fly)",
                ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"],
            )
            entry_level = st.number_input("Entry level (% for outright, bps for curve/fly)",
                                          value=0.0, step=0.01, format="%.4f")
            week_of = st.date_input("Week of", value=date.today())
            thesis = st.text_area("Thesis (1-3 sentences)", height=100)
            link = st.text_input("Link to full post (optional)")
            notes = st.text_input("Notes (optional)")

            if st.form_submit_button("📤 Publish", use_container_width=True, type="primary"):
                expected = {"outright": 1, "curve": 2, "fly": 3}[ttype]
                if len(tenors) != expected:
                    st.error(f"{ttype} needs exactly {expected} tenor(s).")
                elif not thesis.strip():
                    st.error("Thesis is required.")
                else:
                    new_entry = {
                        "type": ttype,
                        "direction": direction,
                        "entry_level": float(entry_level),
                        "entry_date": str(date.today()),
                        "week_of": week_of.isoformat(),
                        "thesis": thesis.strip(),
                        "link": link.strip() or None,
                        "notes": notes.strip(),
                        "status": "live",
                    }
                    if ttype == "outright":
                        new_entry["tenor"] = tenors[0]
                    else:
                        new_entry["tenors"] = tenors
                    rows = _load()
                    rows.append(new_entry)
                    _save(rows)
                    st.success("Published. Reloading…")
                    st.rerun()

        # Manage existing — close out a trade
        if entries:
            st.markdown("---")
            st.markdown("**Close out a published trade:**")
            options = [f"{e.get('week_of','?')} — {e.get('type','?')}"
                       for e in entries if e.get("status") == "live"]
            if options:
                idx = st.selectbox("Pick a live trade", range(len(options)),
                                   format_func=lambda i: options[i])
                if st.button("✓ Mark as closed"):
                    rows = _load()
                    target = sorted(rows, key=lambda e: e.get("week_of",""), reverse=True)
                    live_entries = [e for e in target if e.get("status") == "live"]
                    if 0 <= idx < len(live_entries):
                        target_entry = live_entries[idx]
                        for r in rows:
                            if (r.get("week_of") == target_entry.get("week_of")
                                    and r.get("entry_date") == target_entry.get("entry_date")):
                                r["status"] = "closed"
                                r["closed_date"] = str(date.today())
                                pnl = _pnl_bps(r, df)
                                if pnl is not None:
                                    r["final_pnl_bps"] = round(pnl, 1)
                                break
                        _save(rows)
                        st.success("Closed.")
                        st.rerun()
