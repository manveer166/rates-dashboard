"""Page 30 — Email A/B Test Console (admin).

Create and view A/B tests for the weekly alert. The framework lives in
analysis/ab_test.py; this page just renders the UI for it.

Workflow:
  1. Admin creates a test with two variants (subject / body / CTA).
  2. send_alert.py uses assign_variant() to split recipients deterministically.
  3. Admin marks opens / clicks here as data comes in.
  4. Page shows live two-proportion z-test and a clear winner once n is enough.
"""

import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from analysis.ab_test import (
    compute_stats, get_or_create_test, list_tests, log_event,
)
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import (
    init_session_state, password_gate, is_admin,
)

st.set_page_config(page_title="A/B Tests", page_icon="🧪", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="A/B Tests")

st.title("🧪 Email A/B Test Console")
st.caption(
    "Configure subject-line / body / CTA tests for the weekly alert and "
    "track which variant wins on opens and click-throughs."
)
st.divider()

if not is_admin():
    st.warning("This page is admin-only.")
    st.stop()

# ── Create new test ───────────────────────────────────────────────────────
with st.expander("➕ Create new test", expanded=False):
    with st.form("ab_create"):
        name = st.text_input("Test name (unique)",
                              placeholder="e.g. 2026-W19 weekly subject")
        kind = st.selectbox("What's being tested",
                             ["subject", "body", "cta"])
        cA, cB = st.columns(2)
        with cA:
            variant_a = st.text_area("Variant A", height=120,
                                      placeholder="A is the control / current default")
        with cB:
            variant_b = st.text_area("Variant B", height=120,
                                      placeholder="B is the challenger")
        if st.form_submit_button("Create test", type="primary",
                                  use_container_width=True):
            if not name.strip() or not variant_a.strip() or not variant_b.strip():
                st.error("Name + both variants are required.")
            else:
                t = get_or_create_test(name.strip(), variant_a.strip(),
                                        variant_b.strip(), kind=kind)
                st.success(f"Created/updated **{t['name']}**.")
                st.rerun()

st.divider()

# ── List existing tests ───────────────────────────────────────────────────
tests = list_tests()
if not tests:
    st.info("No tests yet — create one above.")
    st.stop()

st.subheader(f"📊 {len(tests)} test{'s' if len(tests) != 1 else ''}")

for t in sorted(tests, key=lambda x: x.get("started_on", ""), reverse=True):
    with st.container(border=True):
        head_l, head_r = st.columns([3, 1])
        head_l.markdown(f"### {t['name']}")
        head_r.caption(f"Started {t.get('started_on', '?')}  ·  {t.get('kind', '?')}")

        # Variant text + send counts
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Variant A**")
            st.code(t["variant_a"], language=None)
        with c2:
            st.markdown("**Variant B**")
            st.code(t["variant_b"], language=None)

        # Stats
        stats = compute_stats(t)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Sends A", t.get("sends_a", 0))
        m2.metric("Sends B", t.get("sends_b", 0))
        m3.metric(
            "Open rate A",
            f"{stats['open_rate_a'] * 100:.1f}%" if t.get('sends_a') else "—",
        )
        m4.metric(
            "Open rate B",
            f"{stats['open_rate_b'] * 100:.1f}%" if t.get('sends_b') else "—",
        )

        m5, m6, m7, m8 = st.columns(4)
        m5.metric(
            "Click rate A",
            f"{stats['click_rate_a'] * 100:.1f}%" if t.get('sends_a') else "—",
        )
        m6.metric(
            "Click rate B",
            f"{stats['click_rate_b'] * 100:.1f}%" if t.get('sends_b') else "—",
        )
        m7.metric(
            "Open p-value",
            f"{stats['open_p']:.3f}" if t.get('sends_a') and t.get('sends_b') else "—",
        )
        m8.metric(
            "Click p-value",
            f"{stats['click_p']:.3f}" if t.get('sends_a') and t.get('sends_b') else "—",
        )

        # Winner banner
        if stats["open_significant"]:
            st.success(
                f"**Winner on opens: Variant {stats['open_winner']}** "
                f"(p = {stats['open_p']:.3f}, n_A = {t['sends_a']}, n_B = {t['sends_b']})"
            )
        elif stats["click_significant"]:
            st.success(
                f"**Winner on clicks: Variant {stats['click_winner']}** "
                f"(p = {stats['click_p']:.3f})"
            )
        elif (t.get("sends_a", 0) >= 30 and t.get("sends_b", 0) >= 30):
            st.info(
                "No statistically significant winner yet. Keep collecting data, "
                "or pick the variant with the better point estimate if you need to commit."
            )
        else:
            st.warning("Not enough sends to call it (need 30+ per variant).")

        # Manual event logging (until tracking pixel is wired)
        with st.expander("Log an event manually"):
            ec1, ec2, ec3 = st.columns([3, 1, 1])
            with ec1:
                em = st.text_input("Email", key=f"em_{t['name']}")
            with ec2:
                ev = st.selectbox("Event", ["open", "click"], key=f"ev_{t['name']}")
            with ec3:
                st.write("")
                if st.button("Log", key=f"btn_{t['name']}"):
                    if em.strip():
                        log_event(t["name"], em.strip().lower(), ev)
                        st.success(f"Logged {ev} for {em}")
                        st.rerun()
                    else:
                        st.error("Email required.")

        with st.expander("Recent log entries"):
            log = t.get("log", [])
            if log:
                df = pd.DataFrame(log[-50:])
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.caption("_No events logged yet._")
