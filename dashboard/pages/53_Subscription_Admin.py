"""Page 53 — Subscription Admin (admin only).

Three sections:

  1. Subscribers — everyone who's paid via Stripe, current tier, status
  2. Substack comp queue — pending emails to gift, one-click CSV download
  3. Manual tier flip — admin override for refunds, comps, beta-tester
                        upgrades, anyone who needs a tier without paying

The Substack comp queue is the one manual step in an otherwise fully
automated payment funnel: copy the emails from here → paste into
Substack's bulk-add complimentary subscribers UI → click "Mark comped"
to clear them from the queue.
"""

from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import init_session_state, password_gate, is_admin
from dashboard.components.stripe_integration import (
    list_subscribers_with_status,
    pending_substack_comps,
    mark_comps_processed,
    comp_queue_csv,
    set_subscriber_tier,
    get_subscriber_tier,
    stripe_configured,
    TIER_CONFIG,
)

st.set_page_config(page_title="Subscription Admin", page_icon="💳",
                    layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Subscription Admin")

st.title("💳 Subscription Admin")
st.caption(
    "Stripe subscribers · Substack comp queue · manual tier overrides. "
    "Admin-only."
)

if not is_admin():
    st.error("Admin login required to view this page.")
    st.stop()


# ── Top KPI strip ────────────────────────────────────────────────────────
subs    = list_subscribers_with_status()
pending = pending_substack_comps()
n_subs       = sum(1 for s in subs if s.get("status") == "processed")
n_pending    = len(pending)
n_founding   = sum(1 for s in subs if s.get("current_tier") == "founding")
n_pro        = sum(1 for s in subs if s.get("current_tier") == "pro")
mrr = n_founding * 29 + n_pro * 49   # rough — doesn't account for churn

k1, k2, k3, k4 = st.columns(4)
k1.metric("Active subscribers",  n_subs)
k2.metric("Founding seats taken",
          f"{n_founding}/100",
          delta=f"{100 - n_founding} left")
k3.metric("Estimated MRR",       f"${mrr}")
k4.metric("Substack comps pending", n_pending,
          delta="manual upload to Substack required" if n_pending else "queue empty")

if not stripe_configured():
    st.warning(
        "⚠️ Stripe is not yet configured. Secrets `STRIPE_SECRET_KEY`, "
        "`STRIPE_FOUNDING_PRICE_ID`, and `STRIPE_PRO_PRICE_ID` need to be "
        "set on Streamlit Cloud. See `legal/STRIPE_SETUP.md` for the "
        "step-by-step. Until then, the Subscribe page errors out and the "
        "tabs below are empty."
    )

st.divider()


# ── Tabs ────────────────────────────────────────────────────────────────
tab_subs, tab_comps, tab_manual = st.tabs([
    f"💳 Subscribers ({n_subs})",
    f"🪶 Substack comp queue ({n_pending})",
    "⚙️ Manual tier flip",
])


# ── Tab 1: Subscribers ─────────────────────────────────────────────────
with tab_subs:
    if not subs:
        st.info(
            "No Stripe checkouts yet. Once subscribers start paying via "
            "the `/Subscribe` page, they appear here automatically."
        )
    else:
        df = pd.DataFrame(subs)
        # Friendly column order
        cols = [c for c in ["email", "current_tier", "tier_at_pay",
                            "status", "updated_at", "session_id"]
                if c in df.columns]
        st.dataframe(df[cols], use_container_width=True, hide_index=True)


# ── Tab 2: Substack comp queue ─────────────────────────────────────────
with tab_comps:
    st.markdown(
        """
**The one manual step.** Substack has no public API for gifting paid
subscriptions, so once an email lands in this queue you have a ~30-second
manual flow to comp them:

1. Click **Download CSV** below
2. Open Substack → your publication → **Settings → Subscribers**
3. Click **"Add complimentary subscribers"** (or similar — UI varies)
4. Paste the email list, set duration (12 months works), confirm
5. Come back here and click **"Mark all comped"**
        """
    )
    st.write("")

    if not pending:
        st.success("🎉 Queue is empty — nothing to comp right now.")
    else:
        # Display the queue
        qdf = pd.DataFrame(pending)
        for col in ("queued_at",):
            if col in qdf.columns:
                qdf[col] = pd.to_datetime(qdf[col], errors="coerce")
        st.dataframe(
            qdf[[c for c in ("email", "tier", "queued_at", "source_session")
                 if c in qdf.columns]],
            use_container_width=True, hide_index=True,
        )

        st.write("")
        cc1, cc2 = st.columns([1, 1])
        with cc1:
            st.download_button(
                "⬇️ Download CSV (just emails, Substack-ready)",
                data=comp_queue_csv(),
                file_name=f"substack_comps_{datetime.utcnow().date()}.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True,
            )
        with cc2:
            if st.button("✅ Mark all comped", use_container_width=True):
                n = mark_comps_processed([e["email"] for e in pending])
                st.success(
                    f"Marked **{n}** email(s) as comped on Substack. "
                    "They won't appear in the queue again."
                )
                st.rerun()

        st.divider()
        st.subheader("Or mark individual emails")
        emails_to_mark = st.multiselect(
            "Pick the emails you've comped (don't mark them all if you "
            "didn't actually upload them yet)",
            options=[e["email"] for e in pending],
        )
        if st.button("Mark selected as comped",
                      disabled=not emails_to_mark):
            n = mark_comps_processed(emails_to_mark)
            st.success(f"Marked {n} email(s) as comped.")
            st.rerun()


# ── Tab 3: Manual tier flip ────────────────────────────────────────────
with tab_manual:
    st.markdown(
        """
Use cases for the manual override:

- **Beta-tester upgrades** — comp the cohort to Pro at $0
- **Refunds** — drop someone back to free without going through Stripe
- **Comp seats** — friends, family, advisors, the journalist who's writing
  about you next week
- **Manual catch-up** — Stripe payment cleared but the webhook callback
  was missed (rare, but happens if Streamlit Cloud was asleep)

Changes here write straight to `data/subscriber_tiers.json` — they take
effect on the user's next page load.
        """
    )

    target_email = st.text_input(
        "Email", placeholder="user@example.com"
    )
    if target_email.strip():
        current = get_subscriber_tier(target_email) or "free"
        st.info(f"Current tier for `{target_email}`: **{current}**")

    target_tier = st.selectbox(
        "Set to tier",
        options=["free", "substack", "pro", "founding"],
        index=2,
    )
    also_queue_comp = st.checkbox(
        "Also queue this email for a Substack complimentary "
        "subscription",
        value=True,
        help=("Adds them to the comp queue above so they get the paid "
              "Macro Manv newsletter at next bulk upload."),
    )

    if st.button(
        f"⚙️ Set `{target_email or '...'}` → **{target_tier}**",
        type="primary",
        use_container_width=True,
        disabled=not (target_email.strip() and "@" in target_email),
    ):
        try:
            set_subscriber_tier(target_email.strip(), target_tier)
            if also_queue_comp and target_tier in ("substack", "pro", "founding"):
                from dashboard.components.stripe_integration import (
                    queue_substack_comp,
                )
                queue_substack_comp(target_email.strip(), target_tier,
                                     source_session="manual_admin")
            st.success(
                f"✅ Set `{target_email.strip()}` → **{target_tier}**. "
                + ("Queued for Substack comp." if also_queue_comp
                   and target_tier != "free" else "")
            )
            st.rerun()
        except Exception as e:
            st.error(f"Could not update tier: {e}")
