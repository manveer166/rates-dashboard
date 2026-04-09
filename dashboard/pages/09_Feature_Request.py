"""
09_Feature_Request.py — Feature request / feedback form.

Sends an email to ratesteam@macromanv.com via SMTP, with a local fallback
that saves requests to a CSV file if SMTP is not configured.
"""

import csv
import os
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
from dashboard.state import password_gate

st.set_page_config(page_title="Feature Request", page_icon="💡", layout="wide")
password_gate()

st.title("💡 Feature Request & Feedback")
st.caption("Have an idea for the dashboard? Let us know below.")

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
    priority = st.select_slider("Priority", options=["Low", "Medium", "High"], value="Medium")
    submitted = st.form_submit_button("Submit Request", use_container_width=True)

if submitted:
    if not subject.strip() or not details.strip():
        st.error("Please fill in both the subject and details fields.")
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ── Try SMTP ──────────────────────────────────────────────────
        smtp_host = os.getenv("SMTP_HOST", "")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_pass = os.getenv("SMTP_PASS", "")
        to_email = "ratesteam@macromanv.com"

        email_sent = False
        if smtp_host and smtp_user and smtp_pass:
            try:
                import smtplib
                from email.mime.text import MIMEText

                body = (
                    f"Feature Request — {category}\n"
                    f"{'='*50}\n\n"
                    f"From: {name or 'Anonymous'}\n"
                    f"Email: {email or 'N/A'}\n"
                    f"Priority: {priority}\n"
                    f"Time: {timestamp}\n\n"
                    f"Subject: {subject}\n\n"
                    f"{details}\n"
                )
                msg = MIMEText(body)
                msg["Subject"] = f"[Dashboard] {category}: {subject}"
                msg["From"] = smtp_user
                msg["To"] = to_email

                with smtplib.SMTP(smtp_host, smtp_port) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_user, [to_email], msg.as_string())
                email_sent = True
            except Exception:
                email_sent = False

        # ── Fallback: save to CSV ─────────────────────────────────────
        csv_path = Path(__file__).parent.parent.parent / "data" / "feature_requests.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = csv_path.exists()

        with open(csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "name", "email", "category", "priority", "subject", "details"])
            writer.writerow([timestamp, name, email, category, priority, subject, details])

        if email_sent:
            st.success("Request submitted and emailed to the team. Thank you!")
        else:
            st.success("Request saved. Thank you for your feedback!")
            if not smtp_host:
                st.info("Email delivery is not configured yet — your request has been saved locally.")

st.divider()
st.caption("Requests are reviewed by the [Macro Manv](https://manveersahota.substack.com) team.")
