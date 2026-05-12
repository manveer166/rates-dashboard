"""Page 22 — Subscriber Growth (admin only).

Aggregates the local sources we have:
  • data/page_email_access.json  — approved emails per gated page
  • data/alerts_log.csv          — alert send / preview events
  • data/subscribers.csv (lazy)  — native registrations from auth.py

Substack subscriber counts live behind their dashboard / API and are not
pulled in here — a 'last counted on' field lets you paste them in manually.
"""

import csv
import json
import sys
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

st.set_page_config(page_title="Subscriber Growth", page_icon="📈", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Subscriber Growth")

st.title("📈 Subscriber Growth")
st.caption("Audience size, gated-page approvals, and alert activity.")

if not is_admin():
    st.warning("Admin only.")
    st.stop()

st.divider()

ROOT = Path(__file__).parent.parent.parent
ACCESS_FILE = ROOT / "data" / "page_email_access.json"
ALERTS_LOG  = ROOT / "data" / "alerts_log.csv"
SUBS_CSV    = ROOT / "data" / "subscribers.csv"
SUBS_NUM    = ROOT / "data" / "substack_subscriber_count.json"

# ── Substack count (manually entered) ─────────────────────────────────────
def _load_substack():
    if SUBS_NUM.exists():
        try:
            return json.loads(SUBS_NUM.read_text())
        except Exception:
            return {}
    return {}

def _save_substack(data: dict) -> None:
    SUBS_NUM.parent.mkdir(parents=True, exist_ok=True)
    SUBS_NUM.write_text(json.dumps(data, indent=2))

ss = _load_substack()
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Substack — total",  ss.get("total", "—"),
              help="Manually entered. See entry form below.")
with c2:
    st.metric("Substack — paid",   ss.get("paid", "—"))
with c3:
    st.metric("Substack — free",   ss.get("free", "—"))
with c4:
    if "as_of" in ss:
        st.metric("As of", ss["as_of"])
    else:
        st.metric("As of", "—")

st.caption(
    "💡 Substack's subscriber count isn't exposed via a free public API. "
    "Update the numbers here whenever you check your dashboard."
)

with st.expander("✏️ Update Substack counts"):
    with st.form("ss_form"):
        a, b, c = st.columns(3)
        total = a.number_input("Total subscribers", min_value=0, value=int(ss.get("total", 0)))
        paid  = b.number_input("Paid",              min_value=0, value=int(ss.get("paid", 0)))
        free  = c.number_input("Free",              min_value=0, value=int(ss.get("free", 0)))
        if st.form_submit_button("Save", use_container_width=True, type="primary"):
            history = ss.get("history", [])
            history.append({
                "as_of": datetime.today().strftime("%Y-%m-%d"),
                "total": int(total), "paid": int(paid), "free": int(free),
            })
            _save_substack({
                "total": int(total), "paid": int(paid), "free": int(free),
                "as_of": datetime.today().strftime("%Y-%m-%d"),
                "history": history,
            })
            st.success("Saved.")
            st.rerun()

# ── Substack growth chart from history ────────────────────────────────────
hist = ss.get("history", [])
if len(hist) >= 2:
    hdf = pd.DataFrame(hist)
    hdf["as_of"] = pd.to_datetime(hdf["as_of"])
    hdf = hdf.drop_duplicates(subset=["as_of"], keep="last").sort_values("as_of")

    st.subheader("📊 Substack growth")
    fig = go.Figure()
    for col, name, color in [("total", "Total", "#4fc3f7"),
                             ("paid",  "Paid",  "#4ade80"),
                             ("free",  "Free",  "#fbbf24")]:
        if col in hdf:
            fig.add_trace(go.Scatter(x=hdf["as_of"], y=hdf[col], name=name,
                                     mode="lines+markers",
                                     line=dict(color=color, width=2)))
    fig.update_layout(template=PLOTLY_THEME, height=320, hovermode="x unified",
                      margin=dict(l=10, r=10, t=10, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ── Page-gate approvals ───────────────────────────────────────────────────
st.subheader("🔐 Approved emails per gated page")
if ACCESS_FILE.exists():
    try:
        access = json.loads(ACCESS_FILE.read_text())
    except Exception:
        access = {}
    rows = []
    for slug, cfg in access.items():
        rows.append({
            "Page":     cfg.get("display_name", slug),
            "Slug":     slug,
            "Enabled":  "✓" if cfg.get("enabled") else "—",
            "Emails":   len(cfg.get("emails", [])),
        })
    rows = sorted(rows, key=lambda r: r["Emails"], reverse=True)
    pf = pd.DataFrame(rows).set_index("Page")
    st.dataframe(pf, use_container_width=True)

    # Bar chart by page
    enabled_rows = [r for r in rows if r["Enabled"] == "✓" and r["Emails"] > 0]
    if enabled_rows:
        bar = go.Figure(go.Bar(
            x=[r["Page"] for r in enabled_rows],
            y=[r["Emails"] for r in enabled_rows],
            marker_color="#4fc3f7",
        ))
        bar.update_layout(template=PLOTLY_THEME, height=280,
                          margin=dict(l=10, r=10, t=10, b=10),
                          yaxis_title="Approved emails", showlegend=False)
        st.plotly_chart(bar, use_container_width=True)
else:
    st.info("No page_email_access.json yet — set up gates from the Admin page.")

st.divider()

# ── Alerts activity from log ──────────────────────────────────────────────
st.subheader("🔔 Alert activity (last 90 days)")
if ALERTS_LOG.exists():
    try:
        rows = []
        with open(ALERTS_LOG) as f:
            for r in csv.reader(f):
                if not r:
                    continue
                # tolerate variable shapes — first col is always timestamp
                rows.append(r)
        if rows:
            log = pd.DataFrame(rows)
            log = log.rename(columns={0: "ts", 1: "to", 2: "kind"})
            log["ts"] = pd.to_datetime(log["ts"], errors="coerce")
            log = log.dropna(subset=["ts"]).sort_values("ts")
            log_recent = log[log["ts"] >= pd.Timestamp.now() - pd.Timedelta(days=90)]
            colA, colB = st.columns([1, 2])
            with colA:
                st.metric("Sends in 90d", len(log_recent))
                st.metric("Unique recipients", log_recent.get("to", pd.Series()).nunique())
            with colB:
                if len(log_recent):
                    daily = log_recent.set_index("ts").resample("D").size()
                    fig = go.Figure(go.Bar(x=daily.index, y=daily.values,
                                            marker_color="#fbbf24"))
                    fig.update_layout(template=PLOTLY_THEME, height=220,
                                      margin=dict(l=10, r=10, t=10, b=10),
                                      yaxis_title="Sends", showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)
            with st.expander("Recent log entries"):
                st.dataframe(log_recent.tail(20).iloc[::-1], use_container_width=True)
    except Exception as e:
        st.warning(f"Could not parse alerts_log.csv: {e}")
else:
    st.info("No alerts_log.csv yet — sends will be logged here automatically.")

st.divider()

# ── Native subscribers (auth.py CSV) ──────────────────────────────────────
st.subheader("👥 Native registrations (auth.py)")
if SUBS_CSV.exists():
    try:
        subs = pd.read_csv(SUBS_CSV)
        st.metric("Total registered", len(subs))
        if "tier" in subs.columns:
            tiers = subs["tier"].value_counts().reset_index()
            tiers.columns = ["Tier", "Count"]
            st.dataframe(tiers, use_container_width=True, hide_index=True)
        if "created" in subs.columns:
            subs["created"] = pd.to_datetime(subs["created"], errors="coerce")
            cum = subs.dropna(subset=["created"]).sort_values("created")
            cum["count"] = range(1, len(cum) + 1)
            fig = go.Figure(go.Scatter(x=cum["created"], y=cum["count"],
                                        line=dict(color="#a78bfa", width=2),
                                        fill="tozeroy",
                                        fillcolor="rgba(167,139,250,0.10)"))
            fig.update_layout(template=PLOTLY_THEME, height=240,
                              margin=dict(l=10, r=10, t=10, b=10),
                              yaxis_title="Cumulative registrations")
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.warning(f"Could not read subscribers.csv: {e}")
else:
    st.info("No native registrations yet — auth.py will create the CSV on first signup.")
