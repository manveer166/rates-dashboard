"""Page 31 — CTA / UTM Link Audit (admin).

Walks the briefs/ directory for every UTM-tagged URL the dashboard has
emitted, groups by campaign, and lets admin paste in manual click counts
from Substack / GA4 since we don't have a tracking endpoint.

This is the buildable half of the original 'CTA click attribution' brief —
the missing piece (click capture) requires hosted infra. This page gives
you a clean ledger so you know exactly what to look up in your analytics.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import init_session_state, password_gate, is_admin

st.set_page_config(page_title="CTA Audit", page_icon="🔗", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="CTA Audit")

st.title("🔗 CTA / UTM Link Audit")
st.caption(
    "Every UTM-tagged link the dashboard has emitted in the briefs/ directory, "
    "grouped by campaign. Click data isn't auto-captured (no tracking endpoint), "
    "so paste counts manually from Substack / GA4 below."
)
st.divider()

if not is_admin():
    st.warning("Admin only.")
    st.stop()

ROOT       = Path(__file__).parent.parent.parent
BRIEFS_DIR = ROOT / "briefs"
STORE      = ROOT / "data" / "cta_audit.json"

UTM_RE = re.compile(
    r"https?://[^\s\)\]]+?\?[^\s\)\]]*utm_campaign=[^\s\)\]&]+",
    flags=re.IGNORECASE,
)


# ── Walk briefs/ for UTM links ────────────────────────────────────────────
def _scan_briefs() -> pd.DataFrame:
    if not BRIEFS_DIR.exists():
        return pd.DataFrame()

    rows = []
    for md_path in BRIEFS_DIR.rglob("brief.md"):
        try:
            txt = md_path.read_text(errors="ignore")
        except Exception:
            continue
        for url in UTM_RE.findall(txt):
            # Strip trailing punctuation that regex sometimes catches
            url = url.rstrip(").,;'\"")
            params = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&")
                          if "=" in p)
            rows.append({
                "Campaign":   params.get("utm_campaign", "—"),
                "Source":     params.get("utm_source", "—"),
                "Medium":     params.get("utm_medium", "—"),
                "Content":    params.get("utm_content", "—"),
                "Destination": url.split("?", 1)[0],
                "Brief":      str(md_path.relative_to(BRIEFS_DIR)),
                "URL":        url,
            })
    return pd.DataFrame(rows)


def _load_clicks() -> dict:
    if STORE.exists():
        try: return json.loads(STORE.read_text())
        except Exception: return {}
    return {}


def _save_clicks(d: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, indent=2))


df = _scan_briefs()
if df.empty:
    st.info("No UTM links found yet — generate a brief first "
            "(`python3 scripts/daily_brief.py`).")
    st.stop()

clicks = _load_clicks()

# ── Summary by campaign ──────────────────────────────────────────────────
st.subheader("📊 Summary by campaign")
camp_groups = df.groupby("Campaign").agg(
    times_emitted=("URL", "count"),
    distinct_destinations=("Destination", "nunique"),
    first_brief=("Brief", "min"),
    last_brief=("Brief", "max"),
).reset_index()
camp_groups["clicks (manual)"] = [clicks.get(f"campaign:{c}", 0) for c in camp_groups["Campaign"]]
camp_groups["CTR (manual)"] = [
    f"{(clicks.get(f'campaign:{c}', 0) / max(n, 1) * 100):.1f}%"
    for c, n in zip(camp_groups["Campaign"], camp_groups["times_emitted"])
]
st.dataframe(camp_groups, use_container_width=True, hide_index=True)

# ── Manual click-count entry ─────────────────────────────────────────────
with st.expander("📝 Update manual click counts (from Substack / GA4)"):
    edited_clicks = {}
    for c in sorted(camp_groups["Campaign"].unique()):
        key = f"campaign:{c}"
        edited_clicks[key] = st.number_input(
            f"Clicks for `{c}`",
            value=int(clicks.get(key, 0)),
            min_value=0, step=1, key=f"clk_{c}",
        )
    if st.button("💾 Save click counts", use_container_width=True, type="primary"):
        clicks.update(edited_clicks)
        _save_clicks(clicks)
        st.success("Saved.")
        st.rerun()

st.divider()

# ── Full link ledger ─────────────────────────────────────────────────────
st.subheader("📋 Full link ledger")
filt_camp = st.selectbox(
    "Filter by campaign",
    options=["(all)"] + sorted(df["Campaign"].unique().tolist()),
)
view = df if filt_camp == "(all)" else df[df["Campaign"] == filt_camp]

# Show distinct (campaign, destination, content) triples and how often
pretty = (view.groupby(["Campaign", "Destination", "Content", "Source", "Medium"])
              .size().reset_index(name="emitted"))
pretty = pretty.sort_values(["Campaign", "emitted"], ascending=[True, False])
st.dataframe(pretty, use_container_width=True, hide_index=True)

# ── Raw distinct URLs (for copying into analytics) ───────────────────────
with st.expander("🔍 Distinct URLs (paste into GA4 / Substack analytics)"):
    distinct = sorted(df["URL"].unique())
    st.caption(f"{len(distinct)} distinct UTM-tagged URLs across {len(df)} emissions.")
    st.code("\n".join(distinct), language=None)

st.divider()
st.caption(
    "**To upgrade this to real click capture:** stand up a redirect endpoint "
    "(Cloudflare Worker, Vercel function, simple Flask app on Fly.io). All "
    "outbound UTM links route through it; it logs each click then 302s onward. "
    "Pipe the log into this page and the manual-entry box becomes auto-populated."
)
