"""
12_Alerts.py — Email alert configuration and manual trigger.

Configure daily/weekly scanner alerts that email the top trades by Sharpe,
z-score extremes, and big movers. Alerts can be triggered manually or via cron.
"""

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from analysis.alert_body import build_body as _build_alert_body_new

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.state import password_gate, get_master_df, init_session_state, is_admin
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header

st.set_page_config(page_title="Alerts", page_icon="🔔", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Alerts")

st.title("🔔 Email Alerts")
st.caption("Get the top trade ideas delivered to your inbox every Monday and Friday.")

ALERTS_CONFIG = Path(__file__).parent.parent.parent / "data" / "alerts_config.json"
ALERTS_LOG = Path(__file__).parent.parent.parent / "data" / "alerts_log.csv"
SUBSCRIBERS_FILE = Path(__file__).parent.parent.parent / "data" / "subscribers.json"

# ── Load / save config ────────────────────────────────────────────────────

def _load_config():
    if ALERTS_CONFIG.exists():
        return json.loads(ALERTS_CONFIG.read_text())
    return {
        "enabled": True,
        "email": "manveer166@gmail.com",
        "frequency": "mon_fri",
        "top_n": 10,
        "include_z_extremes": True,
        "z_threshold": 2.0,
        "include_big_movers": True,
        "mover_threshold_bps": 10,
        "trade_types": ["Outright", "Curve", "Fly"],
    }

def _save_config(cfg):
    ALERTS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    ALERTS_CONFIG.write_text(json.dumps(cfg, indent=2))

def _load_subscribers():
    if SUBSCRIBERS_FILE.exists():
        return json.loads(SUBSCRIBERS_FILE.read_text())
    return []

def _save_subscribers(subs):
    SUBSCRIBERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUBSCRIBERS_FILE.write_text(json.dumps(subs, indent=2))


cfg = _load_config()

st.divider()

# ══════════════════════════════════════════════════════════════════════════
# VIEWER: simple email subscribe
# ══════════════════════════════════════════════════════════════════════════
if not is_admin():
    st.subheader("Subscribe to Alerts")
    st.markdown(
        "Enter your email to receive the **top trade ideas by Sharpe**, "
        "z-score extremes, and big movers every **Monday and Friday morning**."
    )
    with st.form("subscribe_form"):
        sub_email = st.text_input("Your email", placeholder="name@example.com")
        if st.form_submit_button("Subscribe", use_container_width=True, type="primary"):
            if not sub_email.strip() or "@" not in sub_email:
                st.error("Please enter a valid email address.")
            else:
                subs = _load_subscribers()
                emails = [s["email"] for s in subs]
                if sub_email.strip().lower() in [e.lower() for e in emails]:
                    st.info("You're already subscribed.")
                else:
                    subs.append({
                        "email": sub_email.strip(),
                        "subscribed_at": datetime.now().isoformat(),
                    })
                    _save_subscribers(subs)
                    st.success(f"Subscribed {sub_email.strip()} — you'll get alerts every Monday and Friday.")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════
# ADMIN: full configuration
# ══════════════════════════════════════════════════════════════════════════
st.subheader("Alert Configuration")

with st.form("alert_config"):
    c1, c2 = st.columns(2)
    with c1:
        enabled = st.toggle("Alerts enabled", value=cfg.get("enabled", True))
        email = st.text_input("Primary recipient email", value=cfg.get("email", ""))
        frequency = st.selectbox("Frequency", ["mon_fri", "daily", "weekly"],
                                  index=["mon_fri", "daily", "weekly"].index(
                                      cfg.get("frequency", "mon_fri")))
    with c2:
        top_n = st.number_input("Top N trades by Sharpe", min_value=3, max_value=50,
                                 value=cfg.get("top_n", 10))
        z_thresh = st.number_input("Z-score extreme threshold", min_value=1.0, max_value=4.0,
                                    value=cfg.get("z_threshold", 2.0), step=0.25)
        mover_thresh = st.number_input("Big mover threshold (bps/wk)", min_value=1, max_value=50,
                                        value=cfg.get("mover_threshold_bps", 10))

    include_z = st.checkbox("Include z-score extremes", value=cfg.get("include_z_extremes", True))
    include_movers = st.checkbox("Include big weekly movers", value=cfg.get("include_big_movers", True))
    trade_types = st.multiselect("Trade types to include",
                                  ["Outright", "Curve", "Curve*", "Fly", "Fly*"],
                                  default=cfg.get("trade_types", ["Outright", "Curve", "Fly"]))

    if st.form_submit_button("Save Configuration", use_container_width=True):
        new_cfg = {
            "enabled": enabled, "email": email, "frequency": frequency,
            "top_n": top_n, "z_threshold": z_thresh,
            "include_z_extremes": include_z, "include_big_movers": include_movers,
            "mover_threshold_bps": mover_thresh, "trade_types": trade_types,
        }
        _save_config(new_cfg)
        cfg = new_cfg
        st.success("Configuration saved.")

# ── Subscriber list ──────────────────────────────────────────────────────
st.divider()
st.subheader("Subscribers")
subs = _load_subscribers()
if subs:
    sub_df = pd.DataFrame(subs)
    st.dataframe(sub_df, use_container_width=True, hide_index=True)
    st.caption(f"{len(subs)} subscriber(s)")
else:
    st.info("No subscribers yet. Viewers can subscribe from this page.")

st.divider()

# ── Preview / Send ────────────────────────────────────────────────────────
st.subheader("Preview & Send")

@st.cache_data(ttl=3600, show_spinner=False)
def _build_scanner_df():
    """Build a lightweight version of the scanner results for alerts."""
    fi = __import__("fixed_income")
    df = get_master_df()
    if df.empty:
        return pd.DataFrame()

    ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
    TY = fi.TENOR_YEARS
    avail = [t for t in ALL_TENORS if t in df.columns]
    rdf = df[avail].ffill(limit=3).dropna(how="all")

    if len(rdf) < 252:
        return pd.DataFrame()

    on_rate = 5.3
    for col in ["SOFR", "DFF", "EFFR"]:
        if col in df.columns:
            s = df[col].dropna()
            if len(s): on_rate = float(s.iloc[-1]); break

    curve = {}
    row = rdf.iloc[-1]
    for t in avail:
        if not pd.isna(row[t]):
            curve[t] = float(row[t])

    def dv01(t):
        return fi.approx_dv01(TY.get(t, 10.0), curve.get(t, 4.0))

    rows = []

    # Outrights
    for t in avail:
        s = rdf[t].dropna()
        if len(s) < 252: continue
        cr = fi.forward_carry_rolldown(curve, on_rate, "outright", t)
        z = fi.zscore_current(s, 252)
        chg = s.diff().dropna() * 100
        rvol = float(chg.tail(63).std() * np.sqrt(252)) if len(chg) >= 63 else np.nan
        ann_cr = cr["total"] * 12
        sharpe = ann_cr / rvol if rvol and rvol > 0 else np.nan
        d1w = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0
        rows.append({"Trade": f"Rcv {t}", "Type": "Outright", "Sharpe": round(sharpe, 2),
                      "Z": round(z, 2), "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1),
                      "D1W": d1w})

    # Curves
    pairs = [(avail[i], avail[j]) for i in range(len(avail)) for j in range(i+1, len(avail))]
    for t1, t2 in pairs:
        d1, d2 = dv01(t1), dv01(t2)
        ratio = d2 / d1 if d1 > 0 else 1.0
        s = (rdf[t2] - ratio * rdf[t1]).dropna()
        if len(s) < 252: continue
        cr = fi.forward_carry_rolldown(curve, on_rate, "spread", t2, t1)
        z = fi.zscore_current(s, 252)
        chg = s.diff().dropna() * 100
        rvol = float(chg.tail(63).std() * np.sqrt(252)) if len(chg) >= 63 else np.nan
        ann_cr = cr["total"] * 12
        sharpe = ann_cr / rvol if rvol and rvol > 0 else np.nan
        d1w = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0
        rows.append({"Trade": f"Rcv {t1}/{t2}", "Type": "Curve", "Sharpe": round(sharpe, 2),
                      "Z": round(z, 2), "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1),
                      "D1W": d1w})

    # Flies
    flies = [(avail[i], avail[j], avail[k])
             for i in range(len(avail)) for j in range(i+1, len(avail)) for k in range(j+1, len(avail))]
    for w1, b, w2 in flies:
        dw1, db, dw2 = dv01(w1), dv01(b), dv01(w2)
        wb = 2.0 * (dw1/db) if db > 0 else 2.0
        ww2 = dw1/dw2 if dw2 > 0 else 1.0
        s = (wb * rdf[b] - rdf[w1] - ww2 * rdf[w2]).dropna()
        if len(s) < 252: continue
        cr = fi.forward_carry_rolldown(curve, on_rate, "fly", w1, b, w2)
        z = fi.zscore_current(s, 252)
        chg = s.diff().dropna() * 100
        rvol = float(chg.tail(63).std() * np.sqrt(252)) if len(chg) >= 63 else np.nan
        ann_cr = cr["total"] * 12
        sharpe = ann_cr / rvol if rvol and rvol > 0 else np.nan
        d1w = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0
        rows.append({"Trade": f"Rcv {w1}/{b}/{w2}", "Type": "Fly", "Sharpe": round(sharpe, 2),
                      "Z": round(z, 2), "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1),
                      "D1W": d1w})

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _build_alert_body(scanner_df, cfg):
    """Delegate to the shared alert body builder in analysis/alert_body.py."""
    return _build_alert_body_new(scanner_df, cfg)


if st.button("Preview Alert", use_container_width=True):
    with st.spinner("Building scanner..."):
        sdf = _build_scanner_df()
    body = _build_alert_body(sdf, cfg)
    st.code(body, language="text")

st.divider()

def _send_alert_gmail(recipients, body):
    """Send alert to all recipients via Gmail SMTP."""
    from dashboard.state import _secret
    gmail_user = _secret("GMAIL_USER", "")
    gmail_pass = _secret("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass:
        return 0, "Gmail credentials not configured in secrets."

    import smtplib
    from email.mime.text import MIMEText
    sent = 0
    for addr in recipients:
        try:
            msg = MIMEText(body)
            msg["Subject"] = f"Rates Alert — {datetime.now().strftime('%d %b %Y')}"
            msg["From"] = gmail_user
            msg["To"] = addr
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
                s.login(gmail_user, gmail_pass)
                s.send_message(msg)
            sent += 1
        except Exception:
            pass
    return sent, None


if st.button("Send Alert Now", type="primary", use_container_width=True):
    with st.spinner("Building scanner and sending..."):
        sdf = _build_scanner_df()
        body = _build_alert_body(sdf, cfg)

        # Collect all recipients: primary + subscribers
        recipients = set()
        if cfg.get("email"):
            recipients.add(cfg["email"])
        for sub in _load_subscribers():
            recipients.add(sub["email"])

        if not recipients:
            st.error("No recipients — add a primary email or wait for subscribers.")
        else:
            sent, err = _send_alert_gmail(list(recipients), body)
            if err:
                st.warning(err)
                st.code(body, language="text")
            elif sent:
                st.success(f"Alert sent to {sent} recipient(s).")
            else:
                st.error("Failed to send to any recipient.")

            ALERTS_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(ALERTS_LOG, "a", newline="") as f:
                csv.writer(f).writerow([datetime.now().isoformat(), len(recipients), sent])
