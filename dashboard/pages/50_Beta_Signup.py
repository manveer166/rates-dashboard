"""Page 50 — Beta Signup (public).

Profile-based signup form for the Macro Manv Pro beta. Anyone with the
URL can fill it out — but submissions land in a pending queue and only
go live after Manveer approves them on the Admin page.

No auth required. This page deliberately bypasses password_gate so a
prospective tester can reach it from a Substack post link without
hitting a paywall first.
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from dashboard.components.beta_users import (
    submit_signup, get_signup_by_email,
)

st.set_page_config(page_title="Beta Signup", page_icon="🪶", layout="centered")

st.title("🪶 Apply for the Macro Manv Pro beta")
st.markdown(
    '<p style="color:#94a8c9;font-size:15px;margin-top:-4px;">'
    "Twenty seats. Two weeks. Real engagement expected. If you make the "
    "cut you keep a Founding Seat at $29/mo (locked for 10 years) when "
    "the public tier opens at $49/mo."
    "</p>",
    unsafe_allow_html=True,
)

st.divider()


# ── Pre-conditions reminder ──────────────────────────────────────────────
with st.expander("Before you apply — pre-requisites", expanded=False):
    st.markdown(
        """
You should be able to truthfully say yes to all of:

- I hold an **active paid subscription** to the *Macro Manv* Substack
  (free-tier readers aren't eligible — the beta is for people who've
  already shown they value the writing).
- I'm a **rates / fixed-income / macro professional** (buy side,
  sell side, hedge fund, prop, asset manager, or comparable research
  role).
- I can commit to using the dashboard **at least three times a week**
  during the 2-week beta and filling in a structured feedback form
  covering each major page.
- I'm willing to sign a **standard NDA + Beta Terms** before access
  is issued. Both documents will be emailed to me after approval.
        """
    )


# ── Form ────────────────────────────────────────────────────────────────
st.subheader("Your profile")
with st.form("beta_signup", clear_on_submit=False):
    c1, c2 = st.columns(2)
    with c1:
        name = st.text_input(
            "Full name *",
            placeholder="Jane Smith",
        )
        email = st.text_input(
            "Work or personal email *",
            placeholder="jane@example.com",
            help="We'll send credentials and the NDA to this address.",
        )
        organisation = st.text_input(
            "Organisation / firm *",
            placeholder="Some Capital Management",
        )
    with c2:
        role = st.text_input(
            "Role *",
            placeholder="Senior Rates Strategist",
        )
        linkedin = st.text_input(
            "LinkedIn URL (optional)",
            placeholder="https://www.linkedin.com/in/...",
        )
        substack_email = st.text_input(
            "Substack subscriber email",
            placeholder="If different from above — used to verify your sub.",
        )

    st.write("")
    experience = st.text_area(
        "What kind of rates work do you do? *",
        placeholder=(
            "e.g. 'Run a relative-value book in USD swaps. Use BRT + "
            "SWPM daily. Looking for faster ways to surface curve "
            "dislocations.'"
        ),
        height=110,
    )
    why_beta = st.text_area(
        "Why do you want in on this beta? *",
        placeholder=(
            "e.g. 'I've been reading Macro Manv for 6 months and the "
            "regime page sounds exactly like what I've been building "
            "myself in Excel.'"
        ),
        height=110,
    )

    st.write("")
    agreed_terms = st.checkbox(
        "I confirm I'll sign the NDA and Beta Terms before access "
        "is issued, and I understand the beta is private and "
        "screenshots aren't permitted. *"
    )
    agreed_sub = st.checkbox(
        "I confirm I hold an active **paid** Macro Manv subscription "
        "(or will subscribe before access starts). *"
    )

    submitted = st.form_submit_button(
        "📨 Submit application",
        type="primary",
        use_container_width=True,
    )


# ── Submit ──────────────────────────────────────────────────────────────
def _required(v: str) -> bool:
    return bool((v or "").strip())


if submitted:
    errors = []
    if not _required(name):         errors.append("Name is required.")
    if not _required(email):        errors.append("Email is required.")
    elif "@" not in email or "." not in email.split("@")[-1]:
        errors.append("Email looks invalid.")
    if not _required(organisation): errors.append("Organisation is required.")
    if not _required(role):         errors.append("Role is required.")
    if not _required(experience):
        errors.append("Tell us briefly what kind of rates work you do.")
    if not _required(why_beta):
        errors.append("Tell us briefly why you want in.")
    if not agreed_terms:
        errors.append("You must confirm willingness to sign the NDA & Beta Terms.")
    if not agreed_sub:
        errors.append("You must confirm your paid Macro Manv subscription.")

    if errors:
        for e in errors:
            st.error(e)
    elif get_signup_by_email(email):
        st.warning(
            f"There's already an application on file for **{email}**. "
            "If you didn't submit it, or want to update your details, "
            "reply to your last email from Manveer or DM on LinkedIn."
        )
    else:
        try:
            user_id = submit_signup({
                "name":            name,
                "email":           email,
                "organisation":    organisation,
                "role":            role,
                "linkedin":        linkedin,
                "substack_email":  substack_email or email,
                "experience":      experience,
                "why_beta":        why_beta,
                "agreed_terms":    agreed_terms and agreed_sub,
            })
            st.success(
                f"✅ Application received — thanks, {name.split()[0]}."
            )
            st.balloons()
            st.markdown(
                f"""
**What happens next:**

1. I review every application personally (usually within 24 hours).
2. If you make the cut, you'll get an email with:
   - the NDA and Beta Terms (PDF) to sign and return;
   - your dashboard URL and a one-time password.
3. Once both documents come back signed, your account goes live for
   the full 2-week beta window.

If your application isn't a fit for this round, I'll write back to
let you know — and I'll keep you on the list for the next round.

Your application ID: `{user_id[:8]}` — quote this if you reply to
the confirmation email.
                """
            )
        except ValueError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Something went wrong saving your application: {e}")
            st.info("Try again, or DM Manveer on LinkedIn / Twitter.")


st.divider()
st.caption(
    "Macro Manv is run by Manveer Sahota. All data submitted on this "
    "form is used only to evaluate your beta application and contact "
    "you about it. No third-party sharing. You can request deletion at "
    "any time."
)
