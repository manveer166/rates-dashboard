"""Page 36 — Trade Journal (admin).

Free-text journal entries tied to optional trade tags + tickers + dates.
Builds a searchable log of thesis evolution: 'why I liked this trade on
day 1, what changed at day 12, why I closed it at day 30'.

Data: `data/trade_journal.json` — append-only.

This is a workflow tool — not subscriber-facing. Use it to sustain the
disciplined-thinker brand: every TotW pick should have a journal trail
explaining the why, not just the trade name.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import init_session_state, password_gate, is_admin

st.set_page_config(page_title="Journal", page_icon="📓", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Journal")

st.title("📓 Trade Journal")
st.caption(
    "Append-only log of trade thinking. Tag entries by trade, theme, or "
    "regime — search later when you're writing a Substack post about how "
    "your view evolved."
)
st.divider()

if not is_admin():
    st.warning("Admin only. Logging is private to the dashboard owner.")
    st.stop()


STORE = Path(__file__).parent.parent.parent / "data" / "trade_journal.json"


def _load() -> list[dict]:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text())
        except Exception:
            return []
    return []


def _save(rows: list[dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(rows, indent=2, default=str))


COMMON_TAGS = [
    "FOMC", "NFP", "CPI", "auction", "carry", "rolldown",
    "front-end", "belly", "long-end",
    "outright", "curve", "fly",
    "thesis-update", "exit-plan", "pre-mortem", "post-mortem",
]


# ── New entry form ───────────────────────────────────────────────────────
with st.expander("➕ New entry", expanded=True):
    with st.form("journal_new"):
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            note = st.text_area(
                "Note", height=120,
                placeholder=("e.g. 'Belly flies looking attractive — Fed pricing "
                              "looks complacent ahead of CPI on Tuesday. "
                              "Watching 2Y/5Y/10Y in particular if Z falls below -1.5.'"),
            )
        with col2:
            related_trade = st.text_input(
                "Related trade (optional)",
                placeholder="e.g. 2Y/5Y/10Y fly",
                help="Free-form. Use to link entries about the same trade across time.",
            )
            mood = st.selectbox(
                "Conviction",
                ["—", "exploratory", "watching", "active", "exit-pending"],
                help="Tracks where you are in the thesis lifecycle.",
            )
        with col3:
            tags = st.multiselect("Tags", COMMON_TAGS,
                                    placeholder="pick relevant tags")
            visibility = st.selectbox("Visibility", ["private", "shareable"],
                                       help="'shareable' shows up on the public "
                                            "performance page if linked to a "
                                            "Trade-of-Week pick.")

        if st.form_submit_button("📝 Save entry", type="primary",
                                  use_container_width=True):
            if not note.strip():
                st.error("Note is required.")
            else:
                row = {
                    "id":            datetime.now().strftime("%Y%m%d-%H%M%S"),
                    "ts":            datetime.now().isoformat(),
                    "date":          str(date.today()),
                    "note":          note.strip(),
                    "trade":         related_trade.strip(),
                    "mood":          mood if mood != "—" else "",
                    "tags":          tags,
                    "visibility":    visibility,
                }
                rows = _load()
                rows.append(row)
                _save(rows)
                st.success("Saved.")
                st.rerun()


# ── Entries view ─────────────────────────────────────────────────────────
entries = sorted(_load(), key=lambda r: r.get("ts", ""), reverse=True)

if not entries:
    st.info("No entries yet — write your first one above.")
    st.stop()

# Filters
fc1, fc2, fc3 = st.columns(3)
with fc1:
    q = st.text_input("🔎 Search (note + trade + tags)",
                       placeholder="e.g. CPI, 2Y/5Y, FOMC")
with fc2:
    tag_filter = st.multiselect("Filter tags", COMMON_TAGS)
with fc3:
    days_back = st.slider("Show last N days", 7, 365, 90)


cutoff = (date.today() - pd.Timedelta(days=days_back)).isoformat()
view = [e for e in entries
        if e.get("date", "") >= cutoff
        and (not tag_filter or any(t in (e.get("tags") or []) for t in tag_filter))
        and (not q.strip() or
             q.lower() in (e.get("note", "") + " " + e.get("trade", "") + " "
                           + " ".join(e.get("tags") or [])).lower())]

st.subheader(f"📜 {len(view)} entr{'ies' if len(view)!=1 else 'y'}")

# Group by date
from itertools import groupby
for d, group in groupby(view, key=lambda e: e.get("date", "")):
    st.markdown(f"#### {d}")
    for e in group:
        mood_color = {"active":"#4ade80","watching":"#fbbf24",
                       "exit-pending":"#f87171","exploratory":"#a78bfa"}.get(
                           e.get("mood",""), "#94a8c9")
        tags_html = " ".join(
            f'<span style="background:#1a3056;color:#4fc3f7;padding:2px 8px;'
            f'border-radius:10px;font-size:11px;margin-right:4px">{t}</span>'
            for t in (e.get("tags") or [])
        )
        trade_html = (f'<span style="color:#4fc3f7;font-weight:700">'
                       f'· {e["trade"]} ·</span>' if e.get("trade") else "")
        mood_html = (f'<span style="color:{mood_color};font-weight:700;'
                      f'font-size:11px;letter-spacing:1px">{e["mood"].upper()}</span>'
                      if e.get("mood") else "")
        st.markdown(
            f"""
            <div style="background:#122340;border-left:3px solid {mood_color};
                        padding:12px 16px;border-radius:6px;margin:8px 0">
            <div style="font-size:11px;color:#94a8c9;margin-bottom:6px">
                {e.get('ts','')[:16].replace('T',' ')}  {trade_html}  {mood_html}
            </div>
            <div style="color:#e8eef9;font-size:14px;line-height:1.5;
                        white-space:pre-wrap">{e['note']}</div>
            <div style="margin-top:8px">{tags_html}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ── Export ───────────────────────────────────────────────────────────────
with st.expander("⬇️ Export"):
    csv_rows = []
    for e in entries:
        csv_rows.append({
            "date":    e.get("date", ""),
            "ts":      e.get("ts", ""),
            "trade":   e.get("trade", ""),
            "mood":    e.get("mood", ""),
            "tags":    ", ".join(e.get("tags") or []),
            "note":    e.get("note", ""),
        })
    csv = pd.DataFrame(csv_rows).to_csv(index=False)
    st.download_button("⬇️ Download all entries (CSV)",
                       data=csv,
                       file_name=f"trade_journal_{date.today()}.csv",
                       mime="text/csv",
                       use_container_width=True)
