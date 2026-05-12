"""Page 23 — Reader Polls.

Lightweight JSON-backed poll system for the weekly alert.  Admin creates a
poll with question + options; readers vote (1 vote per session).  Closed
polls show results; live polls show the live tally.

Storage: data/polls.json.  Each poll is keyed by a slug and stored as:
  {
    "slug": "2026-w19-trade-of-week",
    "question": "Which trade has the cleanest setup right now?",
    "options": ["Receive 5Y", "Receive 2s10s", "Pay 5Y/30Y fly", ...],
    "votes": {"Receive 5Y": 12, ...},
    "voters": ["session_id_a", "session_id_b", ...],
    "status": "live" | "closed",
    "created": "2026-05-06",
  }
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import init_session_state, password_gate, is_admin

st.set_page_config(page_title="Reader Polls", page_icon="🗳️", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Reader Polls")

st.title("🗳️ Reader Polls")
st.caption("Quick polls for subscribers — one click to vote, results visible to all.")
st.divider()

STORE = Path(__file__).parent.parent.parent / "data" / "polls.json"

# ── Storage ───────────────────────────────────────────────────────────────
def _load() -> dict:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text())
        except Exception:
            return {"polls": []}
    return {"polls": []}

def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2))

# Stable per-session voter ID — prevents double-voting in the same session
if "_poll_voter_id" not in st.session_state:
    st.session_state["_poll_voter_id"] = str(uuid.uuid4())
voter_id = st.session_state["_poll_voter_id"]

data = _load()
polls = data.get("polls", [])

# ── Render helper (defined here so loops below can call it) ──────────────
def _render_results(poll):
    votes = poll.get("votes", {})
    total = sum(votes.values()) or 1
    rows = [{"Option": opt, "Votes": votes.get(opt, 0),
             "Pct": votes.get(opt, 0) / total * 100} for opt in poll["options"]]
    rows = sorted(rows, key=lambda r: r["Votes"], reverse=True)
    fig = go.Figure(go.Bar(
        x=[r["Votes"] for r in rows],
        y=[r["Option"] for r in rows],
        orientation="h",
        text=[f"{r['Votes']} ({r['Pct']:.0f}%)" for r in rows],
        marker_color="#4fc3f7",
        textposition="outside",
    ))
    fig.update_layout(template=PLOTLY_THEME, height=max(180, 60 + 32 * len(rows)),
                      margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_title="Votes", showlegend=False,
                      yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Total votes: {sum(votes.values())}")


# ── Live poll display ─────────────────────────────────────────────────────
live = [p for p in polls if p.get("status") == "live"]
closed = [p for p in polls if p.get("status") == "closed"]

if live:
    st.subheader("🟢 Open polls")
    for poll in sorted(live, key=lambda p: p.get("created", ""), reverse=True):
        with st.container(border=True):
            st.markdown(f"**{poll['question']}**")
            st.caption(f"Created {poll.get('created', '')}  ·  "
                       f"{sum(poll.get('votes', {}).values())} votes")

            already_voted = voter_id in poll.get("voters", [])
            if already_voted:
                st.caption("✓ You've voted in this poll. Live results below:")
                _render_results(poll)
            else:
                choice = st.radio(
                    "Pick one:", poll["options"],
                    key=f"poll_choice_{poll['slug']}",
                    label_visibility="collapsed",
                )
                if st.button("🗳️ Submit vote", key=f"poll_vote_{poll['slug']}",
                             use_container_width=True):
                    fresh = _load()
                    for p in fresh["polls"]:
                        if p["slug"] == poll["slug"]:
                            if voter_id in p.get("voters", []):
                                st.warning("Already voted in this session.")
                                break
                            p.setdefault("votes", {})
                            p["votes"][choice] = p["votes"].get(choice, 0) + 1
                            p.setdefault("voters", []).append(voter_id)
                            break
                    _save(fresh)
                    st.success("Vote recorded.")
                    st.rerun()

if closed:
    st.divider()
    st.subheader("📕 Closed polls")
    for poll in sorted(closed, key=lambda p: p.get("created", ""), reverse=True)[:8]:
        with st.expander(f"{poll.get('created', '')}  ·  {poll['question']}"):
            _render_results(poll)

if not live and not closed:
    st.info("No polls yet.")

# ── Admin: create / close polls ──────────────────────────────────────────
if is_admin():
    st.divider()
    with st.expander("✏️ Admin — create or close a poll", expanded=False):
        tab_new, tab_close = st.tabs(["New poll", "Close existing"])

        with tab_new:
            with st.form("new_poll"):
                question = st.text_input("Question", placeholder="Which fly has the cleanest setup?")
                slug = st.text_input("Slug (URL-safe ID)",
                                     placeholder="2026-w19-best-fly",
                                     help="Unique identifier — lowercase + hyphens.")
                opts_text = st.text_area(
                    "Options (one per line, 2–8)",
                    placeholder="Receive 2Y5Y30Y\nReceive 3Y5Y30Y\nPay 5Y/7Y/30Y\n…",
                    height=140,
                )
                if st.form_submit_button("📤 Publish poll", use_container_width=True,
                                         type="primary"):
                    options = [o.strip() for o in opts_text.split("\n") if o.strip()]
                    if not question.strip() or not slug.strip():
                        st.error("Question and slug are required.")
                    elif not (2 <= len(options) <= 8):
                        st.error("Need 2–8 options.")
                    elif any(p["slug"] == slug.strip() for p in polls):
                        st.error("Slug already exists.")
                    else:
                        fresh = _load()
                        fresh.setdefault("polls", []).append({
                            "slug":     slug.strip(),
                            "question": question.strip(),
                            "options":  options,
                            "votes":    {},
                            "voters":   [],
                            "status":   "live",
                            "created":  datetime.today().strftime("%Y-%m-%d"),
                        })
                        _save(fresh)
                        st.success("Published.")
                        st.rerun()

        with tab_close:
            if not live:
                st.info("No live polls to close.")
            else:
                target_slug = st.selectbox(
                    "Pick a live poll to close",
                    [p["slug"] for p in live],
                    format_func=lambda s: next(p["question"] for p in live if p["slug"] == s),
                )
                if st.button("✓ Close poll", use_container_width=True):
                    fresh = _load()
                    for p in fresh["polls"]:
                        if p["slug"] == target_slug:
                            p["status"] = "closed"
                            p["closed"] = datetime.today().strftime("%Y-%m-%d")
                    _save(fresh)
                    st.success("Closed.")
                    st.rerun()
