"""Page 51 — Beta Admin (admin only).

Manveer's control panel for the beta cohort. Three tabs:

  1. Pending — review applications, approve or deny
  2. Approved users — see who's in, per-user usage stats, revoke / reissue
  3. Activity log — recent events with filters + Excel export

All data is read from data/beta_signups.json and data/beta_activity.jsonl
via dashboard/components/beta_users.py.
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
from dashboard.components.beta_users import (
    list_signups, approve_signup, deny_signup, revoke_access,
    mark_credentials_sent, reissue_password,
    load_activity_df, user_usage_stats, export_to_excel,
)
from dashboard.components.beta_credentials import (
    slot_status, free_slots, assign_slot_to_tester,
    mark_credentials_sent as mark_slot_creds_sent,
    unassign_slot, build_welcome_email_text, col_or,
)

st.set_page_config(page_title="Beta Admin", page_icon="🪶", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Beta Admin")

st.title("🪶 Beta Admin")
st.caption(
    "Pending applications · approved users · activity log. "
    "Everything on this page is admin-only."
)

if not is_admin():
    st.error("Admin login required to view this page.")
    st.stop()


# ── Top KPI strip ────────────────────────────────────────────────────────
all_signups = list_signups()
n_pending  = sum(1 for r in all_signups if r["status"] == "pending")
n_approved = sum(1 for r in all_signups if r["status"] == "approved")
n_denied   = sum(1 for r in all_signups if r["status"] == "denied")
n_revoked  = sum(1 for r in all_signups if r["status"] == "revoked")
activity_df = load_activity_df()
n_events   = len(activity_df)
n_active_7d = (
    int(activity_df.assign(ts=pd.to_datetime(activity_df["ts"], utc=True))
        .loc[lambda d: d["ts"] >= pd.Timestamp.utcnow() - pd.Timedelta(days=7)]
        ["user_email"].nunique())
    if not activity_df.empty else 0
)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Pending",   n_pending,
          delta=f"{n_denied} denied" if n_denied else None)
k2.metric("Approved",  n_approved,
          delta=f"{n_revoked} revoked" if n_revoked else None)
k3.metric("Active (7d)", n_active_7d)
k4.metric("Activity events", f"{n_events:,}")
k5.metric("Total applications", len(all_signups))
st.divider()


# ── SMTP / login-email diagnostic ──────────────────────────────────────
with st.expander("🧪 Test login-email plumbing", expanded=False):
    import os as _os
    import smtplib as _smtplib
    from email.message import EmailMessage as _EmailMessage

    def _sec(k):
        try:
            return st.secrets.get(k, "")
        except Exception:
            return _os.environ.get(k, "")

    _smtp_user = _sec("GMAIL_USER")
    _smtp_pw   = _sec("GMAIL_APP_PASSWORD")
    _notify_to = _sec("BETA_NOTIFY_TO") or _smtp_user

    dc1, dc2, dc3 = st.columns(3)
    dc1.metric("GMAIL_USER (sender)",
               "✅ set" if _smtp_user else "❌ missing",
               delta=(_smtp_user if _smtp_user else None))
    dc2.metric("GMAIL_APP_PASSWORD",
               "✅ set" if _smtp_pw else "❌ missing",
               delta=(f"{len(_smtp_pw)} chars" if _smtp_pw else None))
    dc3.metric("BETA_NOTIFY_TO (recipient)",
               "✅ overridden" if _sec("BETA_NOTIFY_TO") else "default → sender",
               delta=(_notify_to if _notify_to else None))

    if _smtp_pw and " " in _smtp_pw:
        st.warning(
            "⚠️ Your `GMAIL_APP_PASSWORD` contains spaces. Google shows "
            "the app password as `xxxx xxxx xxxx xxxx` but you must "
            "strip the spaces when pasting into secrets — should be 16 "
            "chars exactly, no spaces."
        )

    if _smtp_user and _smtp_pw:
        if st.button("📨 Send a test email NOW", type="primary"):
            try:
                with st.spinner("Connecting to smtp.gmail.com..."):
                    msg = _EmailMessage()
                    msg["From"]    = _smtp_user
                    msg["To"]      = _notify_to
                    msg["Subject"] = "TEST: Macro Manv login-email plumbing"
                    msg.set_content(
                        f"This is a synchronous test from /Beta_Admin.\n\n"
                        f"Sent from:  {_smtp_user}\n"
                        f"Sent to:    {_notify_to}\n"
                        f"Sent at:    {datetime.utcnow().isoformat()}Z\n\n"
                        f"If you're reading this, the plumbing is working — "
                        f"every successful login from now on will land in "
                        f"the same inbox."
                    )
                    with _smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as srv:
                        srv.login(_smtp_user, _smtp_pw)
                        srv.send_message(msg)
                st.success(
                    f"✅ Sent test email to **{_notify_to}**. Check that "
                    "inbox (and spam / Promotions / Updates tabs). If it's "
                    "there, real logins will arrive the same way."
                )
            except _smtplib.SMTPAuthenticationError as e:
                st.error(
                    f"❌ Gmail rejected the login.\n\n```\n{e}\n```\n\n"
                    "Most likely: your App Password is wrong, has spaces "
                    "in it, or 2-Step Verification isn't on for the "
                    f"account `{_smtp_user}`. Regenerate at "
                    "https://myaccount.google.com/apppasswords"
                )
            except Exception as e:
                st.error(
                    f"❌ Send failed: `{type(e).__name__}: {e}`\n\n"
                    "Check the GMAIL_USER value (must be your full "
                    "Gmail address) and that the account allows SMTP."
                )
    else:
        st.info(
            "Add `GMAIL_USER` and `GMAIL_APP_PASSWORD` to Streamlit Cloud "
            "secrets first. See [myaccount.google.com/apppasswords]"
            "(https://myaccount.google.com/apppasswords) to generate the "
            "app password (need 2-Step Verification on first)."
        )


# Compute free-slot count for the Slots tab header
try:
    _free_count = len(free_slots())
except Exception:
    _free_count = 0

# ── Tabs ────────────────────────────────────────────────────────────────
(tab_pending, tab_approved, tab_slots, tab_activity, tab_broadcast,
 tab_export) = st.tabs([
    f"⏳ Pending ({n_pending})",
    f"✅ Approved ({n_approved})",
    f"📋 Slots ({_free_count} free)",
    "📈 Activity",
    f"📣 Broadcast ({n_approved})",
    "📤 Export",
])


# ── Tab 1: Pending ──────────────────────────────────────────────────────
with tab_pending:
    pending = list_signups("pending")
    if not pending:
        st.success("No pending applications. 🎉")
    else:
        st.caption(
            "Review each application. **Approve** issues a one-time "
            "password (shown ONCE — copy it before closing the dialog) "
            "that you email to the applicant along with the signed-NDA "
            "request."
        )
        for r in pending:
            with st.expander(
                f"📝 {r['name']} · {r['email']} · {r['organisation']} "
                f"({r.get('role', '—')}) · "
                f"submitted {r['requested_at'][:16].replace('T', ' ')}",
                expanded=False,
            ):
                c1, c2 = st.columns([3, 2])
                with c1:
                    st.markdown(f"**Email:** {r['email']}")
                    st.markdown(f"**Org:** {r['organisation']}")
                    st.markdown(f"**Role:** {r.get('role','—')}")
                    if r.get("linkedin"):
                        st.markdown(f"**LinkedIn:** {r['linkedin']}")
                    if r.get("substack_email"):
                        st.markdown(
                            f"**Substack email:** `{r['substack_email']}` "
                            "(verify against your subscriber list)"
                        )
                    st.markdown("**Rates experience:**")
                    st.markdown(f"> {r.get('experience','—')}")
                    st.markdown("**Why this beta:**")
                    st.markdown(f"> {r.get('why_beta','—')}")
                    st.caption(
                        f"Agreed to terms checkbox: "
                        f"**{'yes' if r.get('agreed_terms') else 'NO'}**"
                    )

                with c2:
                    st.markdown("**Decide:**")
                    if st.button("✅ Approve",
                                  key=f"appr_{r['id']}",
                                  type="primary",
                                  use_container_width=True):
                        pw = approve_signup(r["id"], approved_by="admin")
                        if pw:
                            st.success(
                                f"Approved. **One-time password:**\n\n"
                                f"```\n{pw}\n```\n\n"
                                "⚠️ Copy this NOW. It cannot be retrieved "
                                "later — only reissued."
                            )
                            st.info(
                                "**Next steps:**\n"
                                "1. Email the NDA + Beta Terms PDFs.\n"
                                "2. Email this password + the dashboard URL.\n"
                                "3. Mark credentials-sent once you've sent them."
                            )
                        else:
                            st.error("Could not approve. Reload the page.")

                    reason = st.text_input(
                        "Denial reason (optional)",
                        key=f"reason_{r['id']}",
                        placeholder="e.g. not a paid subscriber",
                    )
                    if st.button("❌ Deny",
                                  key=f"deny_{r['id']}",
                                  use_container_width=True):
                        if deny_signup(r["id"], reason=reason):
                            st.warning(f"Denied: {r['email']}")
                            st.rerun()
                        else:
                            st.error("Could not deny.")


# ── Tab 2: Approved users ──────────────────────────────────────────────
with tab_approved:
    approved = list_signups("approved")
    usage = user_usage_stats() if not activity_df.empty else pd.DataFrame()

    if not approved:
        st.info("No approved users yet.")
    else:
        # Build a single roster table joining signups + usage
        rows = []
        usage_by_email = {r["email"]: r for r in usage.to_dict("records")} \
                          if not usage.empty else {}
        for r in approved:
            u = usage_by_email.get(r["email"], {})
            rows.append({
                "Name":          r["name"],
                "Email":         r["email"],
                "Org":           r["organisation"],
                "Role":          r.get("role", "—"),
                "Approved":      (r.get("approved_at") or "")[:10],
                "Creds sent":    "✓" if r.get("credentials_sent_at") else "—",
                "Last login":    (r.get("last_login_at") or "—")[:16].replace("T", " "),
                "Views":         u.get("total_views", 0),
                "Pages":         u.get("distinct_pages", 0),
                "Last seen":     (str(u["last_seen"])[:16] if u.get("last_seen") is not None else "—"),
                "Top page":      u.get("top_page", "—"),
            })
        roster_df = pd.DataFrame(rows)
        st.dataframe(roster_df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Per-user actions")
        sel = st.selectbox(
            "Select an approved user",
            options=[(r["id"], f"{r['name']} <{r['email']}>") for r in approved],
            format_func=lambda x: x[1],
        )
        if sel:
            sel_id = sel[0]
            sel_user = next(r for r in approved if r["id"] == sel_id)
            ac1, ac2, ac3 = st.columns(3)
            with ac1:
                if st.button("✉️ Mark credentials sent",
                              key="mark_sent",
                              use_container_width=True):
                    if mark_credentials_sent(sel_id):
                        st.success("Marked.")
                        st.rerun()
            with ac2:
                if st.button("🔁 Reissue password",
                              key="reissue",
                              use_container_width=True):
                    new_pw = reissue_password(sel_id)
                    if new_pw:
                        st.success(
                            f"New password:\n\n```\n{new_pw}\n```\n\n"
                            "⚠️ Copy now. Email to user."
                        )
            with ac3:
                if st.button("⛔ Revoke access",
                              key="revoke",
                              use_container_width=True):
                    if revoke_access(sel_id):
                        st.warning(f"Revoked: {sel_user['email']}")
                        st.rerun()


# ── Tab 3: Slots — quick-add tester ────────────────────────────────────
with tab_slots:
    st.subheader("Pre-allocated credential slots")
    st.caption(
        "20 slots were generated in advance and pre-approved in the auth "
        "store. When a signed NDA comes back from a tester, assign them "
        "the next free slot here — the welcome-email card below is "
        "ready to paste into Gmail."
    )

    _slots = slot_status()
    if _slots.empty:
        st.error(
            "No credential slots exist yet. Run from a terminal:\n\n"
            "```\npython scripts/generate_beta_credentials.py 20\n```"
        )
    else:
        # ── Status overview ──────────────────────────────────────────────
        _free = (_slots["status"] == "🟢 free").sum()
        _assigned = (_slots["status"] == "✅ assigned").sum()
        _sent = (_slots["credentials_sent_at"].astype(str).str.strip() != "").sum()

        c1, c2, c3 = st.columns(3)
        c1.metric("🟢 Free", _free)
        c2.metric("✅ Assigned", _assigned)
        c3.metric("📨 Credentials sent", _sent)
        st.write("")

        # ── Pending replies banner ───────────────────────────────────────
        _replied_col = col_or(_slots, "email_replied", "Email Replied")
        if _replied_col is not None:
            _pending_mask = (
                _slots[_replied_col].astype(str).str.upper().isin(["TRUE", "1", "YES", "Y", "✓"])
                & (_slots["assigned_to_real_email"].astype(str).str.strip() == "")
            )
            _n_pending = int(_pending_mask.sum())
            if _n_pending > 0:
                _sent_col = col_or(_slots, "email_sent", "Email Sent")
                _hint = ""
                if _sent_col:
                    _names = _slots.loc[_pending_mask, _sent_col].astype(str).tolist()
                    _hint = " — " + ", ".join(_names[:3])
                    if len(_names) > 3:
                        _hint += f" + {len(_names) - 3} more"
                st.warning(
                    f"📩 **{_n_pending} replied but not yet assigned**{_hint}. "
                    "Pick the matching slot from the dropdown below to assign."
                )

        # ── Quick-add form ───────────────────────────────────────────────
        if _free > 0:
            with st.expander("➕ Assign a slot to a tester", expanded=True):
                # Build the slot picker options. Free slots only.
                _free_df = _slots[_slots["status"] == "🟢 free"]
                _sent_col = col_or(_free_df, "email_sent", "Email Sent")

                def _label_slot(s: str) -> str:
                    if not s:
                        return "🎯 Auto-pick next free"
                    if _sent_col:
                        sent = _free_df.loc[_free_df["slot"] == s, _sent_col]
                        sent_val = sent.iloc[0] if not sent.empty else ""
                        if str(sent_val).strip():
                            return f"{s}  →  {sent_val}"
                    return s

                _slot_options = [""] + _free_df["slot"].tolist()

                with st.form("assign_slot_form", clear_on_submit=True):
                    _pick = st.selectbox(
                        "Slot to assign",
                        options=_slot_options,
                        format_func=_label_slot,
                        help=("Pick the slot whose 'Email Sent' matches the "
                              "tester who just replied, or leave on Auto-pick "
                              "to take the next free slot."),
                    )
                    fc1, fc2, fc3 = st.columns([2, 2, 2])
                    _real_name  = fc1.text_input(
                        "Full name *", placeholder="Alice Smith")
                    _real_email = fc2.text_input(
                        "Real email *", placeholder="alice@goldman.com",
                        help="Tester's real reply-to email — for your CSV only, never goes to git or to Streamlit Cloud.")
                    _org        = fc3.text_input(
                        "Organisation", placeholder="Goldman Sachs")
                    _submit = st.form_submit_button(
                        "Assign →",
                        type="primary",
                        use_container_width=True,
                    )

                if _submit:
                    try:
                        _row = assign_slot_to_tester(
                            _real_name,
                            _real_email,
                            _org,
                            slot=(_pick or None),
                        )
                        st.session_state["_last_assigned_slot"] = _row
                        st.success(
                            f"✅ Assigned **{_row['slot']}** "
                            f"({_row['login_email']}) to "
                            f"**{_row['assigned_to_real_name']}**."
                        )
                        st.rerun()
                    except ValueError as e:
                        st.error(f"❌ {e}")
        else:
            st.warning(
                "All 20 slots are assigned. Generate more from terminal:\n\n"
                "```\npython scripts/generate_beta_credentials.py 10\n```"
            )

        # ── Welcome-email card for last-assigned slot ───────────────────
        _last = st.session_state.get("_last_assigned_slot")
        if _last:
            st.divider()
            st.subheader("📨 Welcome email — copy + paste into Gmail")

            _subject, _body = build_welcome_email_text(
                real_name    = _last["assigned_to_real_name"],
                login_email  = _last["login_email"],
                password     = _last["password"],
                organisation = _last.get("organisation", ""),
            )

            _to_field = _last["assigned_to_real_email"]
            cc1, cc2 = st.columns([1, 4])
            cc1.metric("To", _to_field)
            cc2.metric("Subject", _subject)

            st.text_area(
                "Email body — copy this directly",
                value=_body,
                height=420,
                key="welcome_body",
            )

            mc1, mc2 = st.columns(2)
            if mc1.button("📨 Mark credentials sent",
                          use_container_width=True,
                          type="primary"):
                mark_slot_creds_sent(_last["slot"])
                st.session_state.pop("_last_assigned_slot", None)
                st.success(f"Marked {_last['slot']} as sent.")
                st.rerun()
            if mc2.button("✕ Clear (don't mark sent)",
                          use_container_width=True):
                st.session_state.pop("_last_assigned_slot", None)
                st.rerun()

        # ── All slots table ─────────────────────────────────────────────
        st.divider()
        st.subheader("All slots")
        # Show every column from the CSV except `password` (no cleartext
        # passwords in the admin table — those come out only via the
        # welcome-email card after Assign).
        _display = _slots.loc[:, [c for c in _slots.columns if c.lower() != "password"]]
        # Put status first if present
        if "status" in _display.columns:
            _cols = ["status"] + [c for c in _display.columns if c != "status"]
            _display = _display[_cols]
        st.dataframe(_display, use_container_width=True, hide_index=True)
        st.caption(
            "Passwords are deliberately hidden here — they appear in the "
            "welcome-email card right after you click Assign. Edit `Email "
            "Sent` / `Email Replied` columns directly in your CSV in Excel "
            "if you maintain those locally."
        )

        # ── Unassign (rare) ─────────────────────────────────────────────
        with st.expander("⚠️ Unassign a slot (rare)"):
            _assigned_slots = _slots[_slots["status"] == "✅ assigned"]["slot"].tolist()
            if not _assigned_slots:
                st.caption("No slots to unassign.")
            else:
                _ua = st.selectbox(
                    "Slot to unassign",
                    options=[""] + _assigned_slots,
                    format_func=lambda s: "Pick a slot..." if not s else s,
                )
                if _ua and st.button(
                    f"Unassign {_ua}", type="secondary"):
                    unassign_slot(_ua)
                    st.warning(f"Unassigned {_ua}.")
                    st.rerun()


# ── Tab 4: Activity log ────────────────────────────────────────────────
with tab_activity:
    if activity_df.empty:
        st.info("No activity events recorded yet.")
    else:
        st.caption(
            f"Last 200 events (of {len(activity_df):,} total). "
            "Every page view by an authenticated beta user appears here."
        )
        # Filters
        fc1, fc2, fc3 = st.columns([2, 2, 1])
        with fc1:
            emails = ["(all)"] + sorted(activity_df["user_email"].unique().tolist())
            email_filter = st.selectbox("Filter by user", emails)
        with fc2:
            pages = ["(all)"] + sorted(activity_df["page"].unique().tolist())
            page_filter = st.selectbox("Filter by page", pages)
        with fc3:
            days = st.slider("Last N days", 1, 30, 7)

        # Apply filters
        cutoff = pd.Timestamp.utcnow() - pd.Timedelta(days=days)
        f_df = activity_df.copy()
        f_df["ts"] = pd.to_datetime(f_df["ts"], utc=True)
        f_df = f_df[f_df["ts"] >= cutoff]
        if email_filter != "(all)":
            f_df = f_df[f_df["user_email"] == email_filter]
        if page_filter != "(all)":
            f_df = f_df[f_df["page"] == page_filter]

        st.dataframe(f_df.head(200), use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Per-page usage in the filtered window")
        if not f_df.empty:
            page_counts = (f_df.groupby("page")["user_email"]
                           .agg(["count", "nunique"])
                           .rename(columns={"count": "views",
                                            "nunique": "unique users"})
                           .sort_values("views", ascending=False))
            st.dataframe(page_counts, use_container_width=True)


# ── Tab 4: Broadcast (personalised mail merge) ─────────────────────────
with tab_broadcast:
    from dashboard.components.beta_broadcast import (
        TEMPLATES, personalize_for_all, broadcast_csv,
        send_via_smtp, log_broadcast, variables_used, render_template,
        find_placeholders, _build_context,
    )
    import os as _os

    if not approved:
        st.info(
            "No approved testers yet. Once you've approved some applicants "
            "from the Pending tab, you can broadcast to them here."
        )
    else:
        st.caption(
            "Personalised mail merge. Use `{{first_name}}`, `{{name}}`, "
            "`{{organisation}}`, `{{role}}`, `{{n_views}}`, `{{n_pages}}`, "
            "`{{top_page}}`, `{{last_seen}}` in your template. Each tester "
            "gets a 1:1 email — no BCC, no group thread."
        )

        # ── Template picker / editor ─────────────────────────────────
        tmpl_options = ["(custom)"] + list(TEMPLATES.keys())
        tmpl_choice = st.selectbox(
            "Start from a template",
            options=tmpl_options,
            format_func=lambda k: (
                "✏️ Custom (write your own)" if k == "(custom)"
                else f"📄 {k.replace('_', ' ').title()}"
            ),
            key="bcast_template",
        )

        if tmpl_choice == "(custom)":
            default_subj = ""
            default_body = ""
        else:
            default_subj = TEMPLATES[tmpl_choice]["subject"]
            default_body = TEMPLATES[tmpl_choice]["body"]

        subj_template = st.text_input(
            "Subject (supports {{vars}})",
            value=default_subj,
            key="bcast_subject",
        )
        body_template = st.text_area(
            "Body (supports {{vars}})",
            value=default_body,
            height=300,
            key="bcast_body",
        )

        # ── Recipient picker ─────────────────────────────────────────
        recipient_emails = st.multiselect(
            "Send to which approved testers?",
            options=[r["email"] for r in approved],
            default=[r["email"] for r in approved],
            format_func=lambda e: next(
                (f"{r['name']} <{e}>" for r in approved if r["email"] == e), e
            ),
            key="bcast_recipients",
        )

        selected_testers = [r for r in approved if r["email"] in recipient_emails]

        # Build a per-email usage dict so {{n_views}} etc. fill in
        usage = user_usage_stats() if not activity_df.empty else pd.DataFrame()
        usage_by_email = (
            {row["email"]: row for row in usage.to_dict("records")}
            if not usage.empty else {}
        )

        # ── Live preview ─────────────────────────────────────────────
        if selected_testers and (subj_template or body_template):
            messages = personalize_for_all(
                subj_template, body_template,
                selected_testers, usage_by_email,
            )

            with st.expander(
                f"🔍 Preview rendered emails ({len(messages)} total)",
                expanded=False,
            ):
                for m in messages[:5]:
                    st.markdown(
                        f"**To:** `{m['email']}`  ·  **Subject:** {m['subject']}"
                    )
                    st.code(m["body"], language=None)
                    st.divider()
                if len(messages) > 5:
                    st.caption(f"…and {len(messages) - 5} more "
                               "(download CSV to see them all)")

            vars_seen = variables_used(subj_template + " " + body_template)
            if vars_seen:
                st.caption(f"Variables used in template: "
                           f"`{', '.join('{{' + v + '}}' for v in vars_seen)}`")

            # ── Placeholder safety check ────────────────────────────
            # Scan EVERY rendered message — a tester-specific render may
            # still contain a [FILL IN] that the user forgot to replace.
            _all_placeholders: set[str] = set()
            for _m in messages:
                _all_placeholders.update(find_placeholders(_m["subject"]))
                _all_placeholders.update(find_placeholders(_m["body"]))

            _has_placeholders = bool(_all_placeholders)
            if _has_placeholders:
                _shown = ", ".join(f"`{p}`" for p in sorted(_all_placeholders))
                st.error(
                    "✋ **Template still has unfilled placeholders — Send and "
                    f"Dry-run are blocked.** Found: {_shown}. Replace these "
                    "with real content (or remove the bracketed text) and "
                    "the buttons will re-enable."
                )

            st.write("")

            # ── Three send options ─────────────────────────────────
            sc1, sc2, sc3 = st.columns(3)

            with sc1:
                st.download_button(
                    "⬇️ Download CSV",
                    data=broadcast_csv(messages),
                    file_name=f"beta_broadcast_{datetime.utcnow().date()}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    disabled=_has_placeholders,
                    help=("CSV with one row per tester. Use with Gmail "
                          "Multi-Send, Mailmerge.app, or any external "
                          "mail-merge tool."
                          if not _has_placeholders
                          else "Blocked: template has unfilled placeholders."),
                )

            smtp_user = (_os.getenv("GMAIL_USER", "")
                         or st.secrets.get("GMAIL_USER", "")
                         if hasattr(st, "secrets") else "")
            smtp_pw   = (_os.getenv("GMAIL_APP_PASSWORD", "")
                         or st.secrets.get("GMAIL_APP_PASSWORD", "")
                         if hasattr(st, "secrets") else "")
            smtp_configured = bool(smtp_user and smtp_pw)

            with sc2:
                if st.button(
                    "📨 Dry-run (log without sending)",
                    use_container_width=True,
                    disabled=_has_placeholders,
                    help=("Logs the broadcast to "
                          "data/beta_broadcasts.jsonl but doesn't send "
                          "anything. Useful for confirming you're about "
                          "to email the right people."
                          if not _has_placeholders
                          else "Blocked: template has unfilled placeholders."),
                ):
                    log_broadcast(
                        subj_template, body_template,
                        recipient_count=len(messages),
                        sent_results=[{"email": m["email"], "ok": True,
                                       "error": "dry-run"} for m in messages],
                        note="dry-run from /Beta_Admin",
                    )
                    st.success(
                        f"✅ Logged dry-run for {len(messages)} recipient(s). "
                        "Nothing sent."
                    )

            with sc3:
                send_disabled = (not smtp_configured) or _has_placeholders
                if _has_placeholders:
                    btn_label = "🚀 SEND (placeholders unfilled)"
                    _send_help = "Blocked: template has unfilled placeholders."
                elif not smtp_configured:
                    btn_label = "🚀 SEND (SMTP not configured)"
                    _send_help = ("Set GMAIL_USER + GMAIL_APP_PASSWORD in "
                                  "Streamlit Cloud secrets to enable.")
                else:
                    btn_label = "🚀 SEND NOW via Gmail SMTP"
                    _send_help = ("Sends each personalised email via Gmail "
                                  "SMTP. Requires GMAIL_USER + "
                                  "GMAIL_APP_PASSWORD in secrets.")
                if st.button(
                    btn_label,
                    use_container_width=True,
                    type="primary",
                    disabled=send_disabled,
                    help=_send_help,
                ):
                    confirm_key = "_bcast_confirm"
                    if not st.session_state.get(confirm_key):
                        st.session_state[confirm_key] = True
                        st.warning(
                            f"⚠️ About to send **{len(messages)}** "
                            f"personalised emails via SMTP. Click the "
                            "button again to confirm."
                        )
                    else:
                        st.session_state[confirm_key] = False
                        with st.spinner(f"Sending {len(messages)} emails…"):
                            results = send_via_smtp(
                                messages, smtp_user, smtp_pw,
                                from_name="Manveer Sahota",
                            )
                        n_ok   = sum(1 for r in results if r["ok"])
                        n_fail = len(results) - n_ok
                        log_broadcast(
                            subj_template, body_template,
                            recipient_count=len(messages),
                            sent_results=results,
                            note="SMTP send from /Beta_Admin",
                        )
                        if n_fail == 0:
                            st.success(f"✅ Sent {n_ok} email(s) successfully.")
                        else:
                            st.warning(
                                f"⚠️ Sent {n_ok} ok, {n_fail} failed. "
                                "Failures:"
                            )
                            for r in results:
                                if not r["ok"]:
                                    st.text(f"  {r['email']}: {r['error']}")

            if not smtp_configured:
                st.info(
                    "💡 **SMTP send is disabled** because `GMAIL_USER` and "
                    "`GMAIL_APP_PASSWORD` aren't in secrets. Use the CSV "
                    "download with Gmail Multi-Send for now — works in any "
                    "Gmail account without code. To enable one-click send: "
                    "set the two secrets on Streamlit Cloud "
                    "(see `legal/STRIPE_SETUP.md` for the secrets workflow)."
                )


# ── Tab 5: Export ───────────────────────────────────────────────────────
# (Note: Broadcast tab inserted as Tab 4 above, Export is now Tab 5)
with tab_export:
    st.subheader("Excel export")
    st.caption(
        "One .xlsx with three sheets: Signups (all applications, "
        "without password hashes), Activity (every event), Usage "
        "(per-user roll-up)."
    )

    if st.button("📤 Generate Excel", type="primary"):
        try:
            tmp_path = Path("/tmp/beta_export.xlsx")
            export_to_excel(tmp_path)
            with tmp_path.open("rb") as f:
                data = f.read()
            st.success("Excel ready.")
            st.download_button(
                "⬇️ Download beta_export.xlsx",
                data=data,
                file_name=f"beta_export_{datetime.utcnow().date()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Export failed: {e}")

    st.divider()
    st.subheader("Raw data preview")
    if all_signups:
        prev_df = pd.DataFrame(all_signups)
        # Strip sensitive columns
        for c in ("password_hash", "password_salt"):
            if c in prev_df.columns:
                prev_df = prev_df.drop(columns=[c])
        st.dataframe(prev_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No signups yet.")
