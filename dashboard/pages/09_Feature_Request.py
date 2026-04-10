"""
09_Feature_Request.py — Feature request / feedback form.

Sends an email to ratesteam@macromanv.com via Gmail SMTP using
manveer166@gmail.com as the sender. Falls back to a local CSV if
the Gmail credentials are missing or the send fails.

Required Streamlit secrets (or environment variables):
    GMAIL_USER          = manveer166@gmail.com
    GMAIL_APP_PASSWORD  = <16-char Google App Password>

Generate the App Password at:
    https://myaccount.google.com/apppasswords
(Requires 2-Step Verification to be enabled.)
"""

import csv
import os
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
from dashboard.state import password_gate
from dashboard.components.header import render_page_header

st.set_page_config(page_title="Feature Request", page_icon="💡", layout="wide")
password_gate()
render_page_header(current="Home")

TO_EMAIL = "ratesteam@macromanv.com"
DEFAULT_FROM = "manveer166@gmail.com"


def _get_gmail_creds() -> tuple[str, str]:
    """Read Gmail credentials from Streamlit secrets first, then env vars."""
    user, pwd = "", ""
    try:
        user = st.secrets.get("GMAIL_USER", "") or ""
        pwd = st.secrets.get("GMAIL_APP_PASSWORD", "") or ""
    except Exception:
        pass
    if not user:
        user = os.getenv("GMAIL_USER", "")
    if not pwd:
        pwd = os.getenv("GMAIL_APP_PASSWORD", "")
    return user or DEFAULT_FROM, pwd


def _send_via_gmail(subject_line: str, body: str) -> tuple[bool, str]:
    """Send the feature-request email via Gmail SMTP. Returns (ok, message)."""
    sender, app_pwd = _get_gmail_creds()
    if not app_pwd:
        return False, "Gmail App Password not configured (set GMAIL_APP_PASSWORD)."
    try:
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(body)
        msg["Subject"] = subject_line
        msg["From"] = sender
        msg["To"] = TO_EMAIL
        msg["Reply-To"] = sender

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, app_pwd)
            server.sendmail(sender, [TO_EMAIL], msg.as_string())
        return True, "Email sent."
    except Exception as exc:
        return False, f"SMTP error: {exc}"


st.title("💡 Feature Request & Feedback")
st.caption(f"Have an idea for the dashboard? It will be emailed straight to {TO_EMAIL}.")

st.divider()

# ── Form ──────────────────────────────────────────────────────────────────
with st.form("feature_request", clear_on_submit=True):
    name = st.text_input("Your name (optional)")
    email = st.text_input("Your email (optional, for follow-up)")
    category = st.selectbox("Category", [
        "New Feature",
        "Enhancement",
        "Bug Report",
        "Data Source Request",
        "UI / UX Feedback",
        "Other",
    ])
    subject = st.text_input("Subject", placeholder="Brief summary of your request")
    details = st.text_area("Details", height=180,
                           placeholder="Describe the feature, enhancement, or issue in detail...")
    priority = st.slider(
        "Priority (1 = nice-to-have, 10 = critical)",
        min_value=1, max_value=10, value=5, step=1,
    )
    submitted = st.form_submit_button("Submit Request", use_container_width=True)

if submitted:
    if not subject.strip() or not details.strip():
        st.error("Please fill in both the subject and details fields.")
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        body = (
            f"Feature Request — {category}\n"
            f"{'='*50}\n\n"
            f"From:     {name or 'Anonymous'}\n"
            f"Email:    {email or 'N/A'}\n"
            f"Priority: {priority} / 10\n"
            f"Time:     {timestamp}\n\n"
            f"Subject:  {subject}\n\n"
            f"{details}\n"
        )
        subject_line = f"[Dashboard] [{priority}/10] {category}: {subject}"

        ok, info = _send_via_gmail(subject_line, body)

        # ── Always save a local CSV copy as backup ────────────────────
        csv_path = Path(__file__).parent.parent.parent / "data" / "feature_requests.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = csv_path.exists()
        try:
            with open(csv_path, "a", newline="") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["timestamp", "name", "email", "category",
                                     "priority", "subject", "details", "email_sent"])
                writer.writerow([timestamp, name, email, category, priority,
                                 subject, details, "yes" if ok else "no"])
        except Exception:
            pass  # CSV failure is non-fatal in cloud deployments

        if ok:
            st.success(f"✅ Request emailed to {TO_EMAIL}. Thank you!")
        else:
            st.error(
                f"❌ Could not send the email — {info}\n\n"
                "Your request was saved locally as a backup."
            )

st.divider()
st.caption("Requests are reviewed by the [Macro Manv](https://manveersahota.substack.com) team.")
