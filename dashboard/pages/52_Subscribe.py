"""Page 52 — Subscribe (public).

Hosted Stripe Checkout entry point. User picks a tier, enters email,
clicks Subscribe → redirected to Stripe → after payment → comes back
to /?stripe_session=cs_xxx → dashboard/state.py callback handler flips
their tier and queues the Substack comp.

No auth required. This page deliberately bypasses password_gate so
anyone can reach it from a Substack post or LinkedIn link.
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from dashboard.components.stripe_integration import (
    create_checkout_session, stripe_configured, TIER_CONFIG,
)

st.set_page_config(page_title="Subscribe", page_icon="💎", layout="centered")

st.title("💎 Subscribe to Macro Manv Pro")
st.markdown(
    '<p style="color:#94a8c9;font-size:15px;margin-top:-4px;">'
    "Research-grade rates RV analytics. Same login, same dashboard, full "
    "Pro tier unlocked instantly. Bundle includes a complimentary paid "
    "Macro Manv newsletter subscription."
    "</p>",
    unsafe_allow_html=True,
)
st.divider()


# ── Hard-fail early if Stripe is not configured ─────────────────────────
if not stripe_configured():
    st.error(
        "💳 **Subscribe is not yet wired up.** Stripe API keys are not "
        "configured for this deployment. If you reached this page from a "
        "post promising the beta is live, please email "
        "**manveer@macromanv.com** — the link should be working again soon."
    )
    st.caption(
        "Admin: set `STRIPE_SECRET_KEY` and the Price IDs in your "
        "Streamlit Cloud secrets per `legal/STRIPE_SETUP.md`."
    )
    st.stop()


# ── Tier picker ──────────────────────────────────────────────────────────
st.subheader("Pick your tier")
col_found, col_pro = st.columns(2)

with col_found:
    st.markdown(
        """
        <div style="background:#1a3056;border-left:4px solid #a78bfa;
                    padding:16px 18px;border-radius:8px;height:100%;">
          <div style="color:#a78bfa;font-size:11px;letter-spacing:1.5px;
                      font-weight:700;margin-bottom:6px">
            🔒 FOUNDING — LIMITED TO 100
          </div>
          <div style="color:#e8eef9;font-size:32px;font-weight:700;
                      margin:6px 0">$29<span style="font-size:13px;
                      color:#94a8c9">&nbsp;/ month</span></div>
          <div style="color:#94a8c9;font-size:12px;line-height:1.5">
            Locked at $29/mo for <b>10 years</b> as long as your
            subscription stays continuously active.<br><br>
            Same access as Pro. Different price. After the first 100,
            this rate is gone.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col_pro:
    st.markdown(
        """
        <div style="background:#0e1f3a;border-left:4px solid #4fc3f7;
                    padding:16px 18px;border-radius:8px;height:100%;">
          <div style="color:#4fc3f7;font-size:11px;letter-spacing:1.5px;
                      font-weight:700;margin-bottom:6px">
            ⚡ PRO — STANDARD
          </div>
          <div style="color:#e8eef9;font-size:32px;font-weight:700;
                      margin:6px 0">$49<span style="font-size:13px;
                      color:#94a8c9">&nbsp;/ month</span></div>
          <div style="color:#94a8c9;font-size:12px;line-height:1.5">
            Full Pro tier — Scanner, Backtester, Trade Builder,
            Regime, PCA Backtest, Vol Surface, Watchlist + the paid
            Macro Manv newsletter.<br><br>
            Standard monthly subscription. Cancel any time.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.write("")

tier = st.radio(
    "Select tier",
    options=["founding", "pro"],
    format_func=lambda t: (
        f"🔒 Founding — $29/mo (10-yr lock)" if t == "founding"
        else "⚡ Pro — $49/mo (standard)"
    ),
    horizontal=True,
    label_visibility="collapsed",
)

st.write("")


# ── Email + checkout ────────────────────────────────────────────────────
st.subheader("Your email")
email = st.text_input(
    "Email",
    placeholder="you@example.com",
    help=("This becomes your login. It's also the email we use to gift "
          "you a complimentary paid Macro Manv newsletter subscription."),
    label_visibility="collapsed",
)

st.caption(
    "💡 **What's included:**  "
    "✓ Full Pro dashboard access  ·  "
    "✓ Complimentary paid Substack subscription  ·  "
    "✓ Cancel anytime via Stripe."
)

st.write("")

if st.button(
    f"💳 Subscribe — pay via Stripe",
    type="primary",
    use_container_width=True,
    disabled=(not email.strip() or "@" not in email),
):
    if "@" not in email or "." not in email.split("@")[-1]:
        st.error("That email looks invalid. Try again.")
    else:
        try:
            with st.spinner("Creating checkout session..."):
                checkout_url = create_checkout_session(email.strip(), tier)
            st.success("Redirecting to Stripe...")
            # Use a meta-refresh + link as fallback
            st.markdown(
                f'<meta http-equiv="refresh" content="0; url={checkout_url}">'
                f'<p>If you are not redirected, '
                f'<a href="{checkout_url}" target="_self">click here to '
                f'open Stripe Checkout</a>.</p>',
                unsafe_allow_html=True,
            )
            st.stop()
        except Exception as e:
            st.error(f"Could not create checkout session: {e}")
            st.info(
                "If this keeps failing, email **manveer@macromanv.com** "
                "and I'll set you up manually."
            )

st.divider()


# ── FAQ ──────────────────────────────────────────────────────────────────
with st.expander("FAQ — billing, cancellation, the Substack bundle"):
    st.markdown(
        """
**How does the Substack subscription work?**
After payment, your email goes into a complimentary-subscription queue.
I bulk-upload to Substack daily — your free paid Macro Manv subscription
typically activates within 24 hours. You'll get a Substack email
confirming.

**Can I cancel?**
Yes, any time, via Stripe Customer Portal (link in your receipt email).
You keep access until the end of the current billing period.

**What if I'm already a paid Substack subscriber?**
Reply to the welcome email — I'll either credit you a month on Substack
or refund the overlap.

**What does the 10-year Founding price lock mean?**
As long as your subscription stays continuously active, your rate stays
at $29/mo for 10 years. If you cancel and re-subscribe later, you join
at the then-current public rate ($49 or higher).

**Is this regulated financial advice?**
No. See the Methodology page and the Pro Terms — Macro Manv is a
research-grade analytics product. Not investment advice. You're a
sophisticated user.

**Refund policy?**
Cancel within 7 days of first payment for a full refund, no questions
asked. After that, standard month-to-month — cancel any time, no
refunds for partial months.
        """
    )

st.caption(
    "Macro Manv is run by Manveer Sahota. Payment processing by Stripe. "
    "Newsletter delivery via Substack. Dashboard hosted on Streamlit Cloud."
)
