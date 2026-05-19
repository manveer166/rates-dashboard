"""Beta broadcast — personalised mail merge for the Beta Admin page.

Template syntax (Mustache-ish, no logic — just variable substitution):

    Hi {{first_name}},
    Saw you logged {{n_views}} page views across {{n_pages}} distinct pages.
    Your top page is {{top_page}}. Keep going.

Supported variables:

    {{name}}          — full name from beta_signups.json
    {{first_name}}    — name.split()[0]
    {{email}}         — login email
    {{organisation}}  — firm
    {{role}}          — job title
    {{linkedin}}      — LinkedIn URL (if provided)

    {{n_views}}       — total page views (from activity log)
    {{n_pages}}       — distinct pages visited
    {{top_page}}      — most-used page
    {{last_seen}}     — UTC timestamp of last activity, formatted as YYYY-MM-DD

Anything not in this list is left as-is so accidental {{typos}} don't crash
the render.

Outputs:
  • personalize_for_all(subject_template, body_template, testers)
      → list of {email, name, subject, body} dicts
  • broadcast_csv(messages) → CSV string for mail-merge tools
  • send_via_smtp(messages, smtp_user, smtp_password)
      → list of {email, ok, error} — uses Gmail SMTP, no third-party deps

Always logs the broadcast to data/beta_broadcasts.jsonl for audit.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Optional


_ROOT = Path(__file__).parent.parent.parent
BROADCAST_LOG = _ROOT / "data" / "beta_broadcasts.jsonl"


# ── Variable lookup ──────────────────────────────────────────────────────
def _first_name(full_name: str) -> str:
    if not full_name:
        return ""
    return str(full_name).strip().split()[0]


def _format_ts(ts) -> str:
    """Normalize a timestamp (string / pandas Timestamp / datetime) to YYYY-MM-DD."""
    if ts is None or ts == "" or ts == "—":
        return "—"
    try:
        if hasattr(ts, "strftime"):
            return ts.strftime("%Y-%m-%d")
        # ISO string
        return str(ts)[:10]
    except Exception:
        return str(ts)[:10]


def _build_context(tester: dict, usage: Optional[dict] = None) -> dict:
    """Merge a beta_signups record + their usage stats into one flat dict."""
    usage = usage or {}
    return {
        "name":         tester.get("name", "") or "",
        "first_name":   _first_name(tester.get("name", "")),
        "email":        tester.get("email", "") or "",
        "organisation": tester.get("organisation", "") or tester.get("org", "") or "",
        "role":         tester.get("role", "") or "",
        "linkedin":     tester.get("linkedin", "") or "",
        "n_views":      str(usage.get("total_views", 0) or 0),
        "n_pages":      str(usage.get("distinct_pages", 0) or 0),
        "top_page":     usage.get("top_page", "—") or "—",
        "last_seen":    _format_ts(usage.get("last_seen", "—")),
    }


# ── Template rendering ───────────────────────────────────────────────────
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render_template(template: str, context: dict) -> str:
    """Replace {{var}} with context[var]. Unknown variables are left as-is
    so a typo doesn't crash the render — you see the literal {{typo}} in
    the preview and fix it."""
    if not template:
        return ""
    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key in context:
            return str(context[key])
        return m.group(0)   # leave unknown vars literal
    return _VAR_RE.sub(repl, template)


def variables_used(template: str) -> list[str]:
    """List of variable names referenced in a template (for the preview UI)."""
    return sorted(set(_VAR_RE.findall(template or "")))


# ── Personalisation across many testers ──────────────────────────────────
def personalize_for_all(
    subject_template: str,
    body_template:    str,
    testers:          list[dict],
    usage_by_email:   Optional[dict] = None,
) -> list[dict]:
    """For each tester, render subject + body. Returns one dict per tester
    with keys: email, name, subject, body.
    """
    usage_by_email = usage_by_email or {}
    out = []
    for t in testers:
        email = (t.get("email") or "").strip().lower()
        if not email:
            continue
        ctx = _build_context(t, usage_by_email.get(email, {}))
        out.append({
            "email":   email,
            "name":    t.get("name", ""),
            "subject": render_template(subject_template, ctx),
            "body":    render_template(body_template,    ctx),
        })
    return out


# ── CSV export (for Gmail multi-send / external mail merge) ──────────────
def broadcast_csv(messages: list[dict]) -> str:
    """Build a CSV: email, name, subject, body. UTF-8. Excel-safe."""
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    w.writerow(["email", "name", "subject", "body"])
    for m in messages:
        w.writerow([m["email"], m.get("name", ""), m["subject"], m["body"]])
    return buf.getvalue()


# ── SMTP send (optional, requires GMAIL_USER + GMAIL_APP_PASSWORD) ──────
def send_via_smtp(
    messages:       list[dict],
    smtp_user:      str,
    smtp_password:  str,
    from_name:      str = "Manveer Sahota",
    dry_run:        bool = False,
) -> list[dict]:
    """Send each message via Gmail SMTP. Returns per-message status.

    Set dry_run=True to log + return without actually sending. Useful for
    confirming what would go out.
    """
    results = []
    if dry_run:
        for m in messages:
            results.append({"email": m["email"], "ok": True, "error": "dry-run"})
        return results

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(smtp_user, smtp_password)
            for m in messages:
                try:
                    msg = EmailMessage()
                    msg["From"]    = f"{from_name} <{smtp_user}>"
                    msg["To"]      = m["email"]
                    msg["Subject"] = m["subject"]
                    msg.set_content(m["body"])
                    srv.send_message(msg)
                    results.append({"email": m["email"], "ok": True, "error": None})
                except Exception as e:
                    results.append({"email": m["email"], "ok": False,
                                    "error": str(e)[:200]})
    except Exception as e:
        # SMTP-level failure (auth, network) — fail every message uniformly
        for m in messages:
            results.append({"email": m["email"], "ok": False,
                            "error": f"SMTP setup failed: {e}"})
    return results


# ── Audit log ────────────────────────────────────────────────────────────
def log_broadcast(
    subject_template: str,
    body_template:    str,
    recipient_count:  int,
    sent_results:     Optional[list[dict]] = None,
    note:             str = "",
) -> None:
    """Append one entry per broadcast to data/beta_broadcasts.jsonl."""
    rec = {
        "ts":               datetime.utcnow().isoformat() + "Z",
        "subject_template": subject_template,
        "body_preview":     (body_template or "")[:200],
        "recipient_count":  int(recipient_count),
        "n_ok":             sum(1 for r in (sent_results or []) if r.get("ok")),
        "n_fail":           sum(1 for r in (sent_results or []) if not r.get("ok")),
        "note":             note,
    }
    try:
        BROADCAST_LOG.parent.mkdir(parents=True, exist_ok=True)
        with BROADCAST_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


# ── Convenience: built-in templates for the common cohort emails ────────
TEMPLATES = {
    "week_1_check_in": {
        "subject": "Macro Manv beta — first-week check-in",
        "body": """\
Hi {{first_name}},

Quick check-in halfway through the beta.

I'm seeing {{n_views}} page views from you across {{n_pages}} distinct pages. Most-used: {{top_page}}. Real engagement — thank you.

Three things I shipped this week from cohort feedback:
1. [FILL IN]
2. [FILL IN]
3. [FILL IN]

If you're stuck on anything, just hit reply. Couple of asks for the back half:
- Have you tried the Backtester yet? It's the page where most feedback has been concentrated.
- The Methodology page documents every formula — would love your eye on any clause that's vague or wrong.

Calendly link for a 30-min feedback call (optional but valuable): [PASTE_CALENDLY_URL]

Six days to go.

— Manv""",
    },
    "day_12_feedback_form": {
        "subject": "Macro Manv beta — 20 mins of feedback (and the Founding Seat offer)",
        "body": """\
Hi {{first_name}},

Two days left in the beta. Here's the structured form I promised — about 20 minutes, every question matters. Even the "this is useless" answers are useful.

[PASTE_FORM_LINK]

Once you submit I'll have your Founding Seat offer ready within 24 hours.

— Manv""",
    },
    "day_4_quick_nudge": {
        "subject": "How's the beta going?",
        "body": """\
Hi {{first_name}},

Quick nudge — you've logged {{n_views}} views so far across {{n_pages}} pages. Going OK? Anything broken?

Reply to this if you're stuck on anything. If you haven't logged in this week, no judgement, just a reminder that the beta wraps in 10 days and the Founding Seat at $29/mo (locked for 10 years) is only on offer to engaged testers.

— Manv""",
    },
}
