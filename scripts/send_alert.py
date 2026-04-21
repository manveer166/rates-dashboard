#!/usr/bin/env python3
"""
Standalone alert sender — run via cron on Monday & Friday mornings.

This script runs OUTSIDE Streamlit, so it reads secrets from the
.streamlit/secrets.toml file directly and uses the same scanner logic
as the dashboard's Alerts page.

Usage:
    python3 scripts/send_alert.py

Google Apps Script cron (free, no server needed):
    See scripts/google_apps_script.js

Local crontab (if you have a machine that's always on):
    # Mon & Fri at 07:00 ET (12:00 UTC)
    0 12 * * 1,5 cd /path/to/rates-dashboard && python3 scripts/send_alert.py >> /tmp/rates_alert.log 2>&1
"""

import json
import logging
import smtplib
import sys
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Ensure project root is importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Read secrets from .streamlit/secrets.toml ────────────────────────────
try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # pip install tomli for <3.11
    except ImportError:
        import toml as tomllib  # pip install toml

SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
if SECRETS_PATH.exists():
    with open(SECRETS_PATH, "rb") as f:
        try:
            SECRETS = tomllib.load(f)
        except Exception:
            # toml (not tomli) uses .load(f) with text mode
            with open(SECRETS_PATH, "r") as ft:
                import toml
                SECRETS = toml.load(ft)
else:
    logger.error(f"No secrets file at {SECRETS_PATH}")
    sys.exit(1)

GMAIL_USER = SECRETS.get("GMAIL_USER", "")
GMAIL_PASS = SECRETS.get("GMAIL_APP_PASSWORD", "")


# ── Load alert config + subscribers ──────────────────────────────────────
ALERTS_CONFIG = ROOT / "data" / "alerts_config.json"
SUBSCRIBERS_FILE = ROOT / "data" / "subscribers.json"

def load_config():
    if ALERTS_CONFIG.exists():
        return json.loads(ALERTS_CONFIG.read_text())
    return {"enabled": True, "email": "manveer166@gmail.com", "top_n": 10,
            "include_z_extremes": True, "z_threshold": 2.0,
            "include_big_movers": True, "mover_threshold_bps": 10,
            "trade_types": ["Outright", "Curve", "Fly"]}

def load_subscribers():
    if SUBSCRIBERS_FILE.exists():
        return json.loads(SUBSCRIBERS_FILE.read_text())
    return []


# ── Build scanner ────────────────────────────────────────────────────────
def build_scanner():
    """Minimal scanner — same logic as the dashboard Alerts page."""
    import numpy as np
    import pandas as pd
    import fixed_income as fi
    from data.fetchers.base import CACHE_DIR

    master = CACHE_DIR / "master.parquet"
    if not master.exists():
        logger.error("No cached data — run the dashboard first to fetch data.")
        return pd.DataFrame()

    df = pd.read_parquet(master)
    df.index = pd.to_datetime(df.index)
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
    for t in avail:
        s = rdf[t].dropna()
        if len(s) < 252: continue
        cr = fi.forward_carry_rolldown(curve, on_rate, "outright", t)
        z = fi.zscore_current(s, 252)
        chg = s.diff().dropna() * 100
        rvol = float(chg.tail(63).std() * np.sqrt(252)) if len(chg) >= 63 else float("nan")
        ann_cr = cr["total"] * 12
        sharpe = ann_cr / rvol if rvol and rvol > 0 else float("nan")
        d1w = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0
        rows.append({"Trade": f"Rcv {t}", "Type": "Outright", "Sharpe": round(sharpe, 2),
                      "Z": round(z, 2), "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1), "D1W": d1w})

    pairs = [(avail[i], avail[j]) for i in range(len(avail)) for j in range(i+1, len(avail))]
    for t1, t2 in pairs:
        d1, d2 = dv01(t1), dv01(t2)
        ratio = d2 / d1 if d1 > 0 else 1.0
        s = (rdf[t2] - ratio * rdf[t1]).dropna()
        if len(s) < 252: continue
        cr = fi.forward_carry_rolldown(curve, on_rate, "spread", t2, t1)
        z = fi.zscore_current(s, 252)
        chg = s.diff().dropna() * 100
        rvol = float(chg.tail(63).std() * np.sqrt(252)) if len(chg) >= 63 else float("nan")
        ann_cr = cr["total"] * 12
        sharpe = ann_cr / rvol if rvol and rvol > 0 else float("nan")
        d1w = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0
        rows.append({"Trade": f"Rcv {t1}/{t2}", "Type": "Curve", "Sharpe": round(sharpe, 2),
                      "Z": round(z, 2), "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1), "D1W": d1w})

    flies = [(avail[i], avail[j], avail[k])
             for i in range(len(avail)) for j in range(i+1, len(avail)) for k in range(j+1, len(avail))]
    for w1, b, w2 in flies:
        dw1, db, dw2 = dv01(w1), dv01(b), dv01(w2)
        wb = 2.0 * (dw1 / db) if db > 0 else 2.0
        ww2 = dw1 / dw2 if dw2 > 0 else 1.0
        s = (wb * rdf[b] - rdf[w1] - ww2 * rdf[w2]).dropna()
        if len(s) < 252: continue
        cr = fi.forward_carry_rolldown(curve, on_rate, "fly", w1, b, w2)
        z = fi.zscore_current(s, 252)
        chg = s.diff().dropna() * 100
        rvol = float(chg.tail(63).std() * np.sqrt(252)) if len(chg) >= 63 else float("nan")
        ann_cr = cr["total"] * 12
        sharpe = ann_cr / rvol if rvol and rvol > 0 else float("nan")
        d1w = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0
        rows.append({"Trade": f"Rcv {w1}/{b}/{w2}", "Type": "Fly", "Sharpe": round(sharpe, 2),
                      "Z": round(z, 2), "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1), "D1W": d1w})

    return pd.DataFrame(rows) if rows else pd.DataFrame()


from analysis.alert_body import build_body  # noqa: F401  (re-exported for __main__)
from analysis.weekly_pdf import build_weekly_pdf


def _monday_of_week():
    from datetime import date, timedelta
    d = date.today()
    return d - timedelta(days=d.weekday())


def send(recipients, body_text: str, pdf_path=None):
    if not GMAIL_USER or not GMAIL_PASS:
        logger.error("Gmail credentials missing from secrets.toml")
        return 0

    from datetime import date, timedelta
    monday = _monday_of_week()
    is_friday = datetime.now().weekday() == 4
    day_label = "Recap" if is_friday else "Setup"
    subject = (
        f"Rates Weekly — Macro Manv · {monday.strftime('%-d %b %Y')} · {day_label}"
    )

    sent = 0
    for addr in recipients:
        try:
            if pdf_path:
                msg = MIMEMultipart()
                msg.attach(MIMEText(
                    "Your Rates Weekly PDF is attached.\n\n" + body_text[:800]
                    + "\n\n[See attached PDF for full report]"
                ))
                with open(pdf_path, "rb") as f:
                    part = MIMEApplication(f.read(), _subtype="pdf")
                    part["Content-Disposition"] = (
                        f'attachment; filename="{pdf_path.name}"'
                    )
                    msg.attach(part)
            else:
                msg = MIMEMultipart()
                msg.attach(MIMEText(body_text))

            msg["Subject"] = subject
            msg["From"]    = GMAIL_USER
            msg["To"]      = addr

            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
                s.login(GMAIL_USER, GMAIL_PASS)
                s.send_message(msg)
            sent += 1
            logger.info(f"Sent to {addr}")
        except Exception as e:
            logger.error(f"Failed to send to {addr}: {e}")
    return sent


if __name__ == "__main__":
    import pandas as pd
    from data.fetchers.base import CACHE_DIR

    cfg = load_config()
    if not cfg.get("enabled", True):
        logger.info("Alerts disabled in config — exiting.")
        sys.exit(0)

    logger.info("Building scanner...")
    sdf = build_scanner()
    body = build_body(sdf, cfg)

    # Load master history for curve table
    hist_df = None
    master_path = CACHE_DIR / "master.parquet"
    if master_path.exists():
        try:
            hist_df = pd.read_parquet(master_path)
            hist_df.index = pd.to_datetime(hist_df.index)
        except Exception as e:
            logger.warning(f"Could not load master cache: {e}")

    # Build PDF
    pdf_path = None
    try:
        logger.info("Building PDF...")
        pdf_path = build_weekly_pdf(sdf, hist_df, cfg)
        logger.info(f"PDF ready: {pdf_path}")
    except Exception as e:
        logger.warning(f"PDF build failed (will send text only): {e}")

    recipients = set()
    if cfg.get("email"):
        recipients.add(cfg["email"])
    for sub in load_subscribers():
        recipients.add(sub["email"])

    if not recipients:
        logger.error("No recipients configured.")
        sys.exit(1)

    logger.info(f"Sending to {len(recipients)} recipient(s)...")
    sent = send(list(recipients), body, pdf_path=pdf_path)
    logger.info(f"Done — {sent}/{len(recipients)} sent.")
