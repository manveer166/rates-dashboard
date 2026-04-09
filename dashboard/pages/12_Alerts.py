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

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.state import password_gate, get_master_df, init_session_state
from dashboard.components.controls import render_sidebar_controls

st.set_page_config(page_title="Alerts", page_icon="🔔", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()

st.title("🔔 Email Alerts")
st.caption("Configure automated scanner alerts — delivered to your inbox.")

ALERTS_CONFIG = Path(__file__).parent.parent.parent / "data" / "alerts_config.json"
ALERTS_LOG = Path(__file__).parent.parent.parent / "data" / "alerts_log.csv"

# ── Load / save config ────────────────────────────────────────────────────

def _load_config():
    if ALERTS_CONFIG.exists():
        return json.loads(ALERTS_CONFIG.read_text())
    return {
        "enabled": False,
        "email": "",
        "frequency": "daily",
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


cfg = _load_config()

st.divider()

# ── Configuration form ────────────────────────────────────────────────────
st.subheader("Alert Configuration")

with st.form("alert_config"):
    c1, c2 = st.columns(2)
    with c1:
        enabled = st.toggle("Alerts enabled", value=cfg.get("enabled", False))
        email = st.text_input("Recipient email", value=cfg.get("email", ""))
        frequency = st.selectbox("Frequency", ["daily", "weekly"],
                                  index=["daily", "weekly"].index(cfg.get("frequency", "daily")))
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
    """Build plain-text alert email body."""
    if scanner_df.empty:
        return "No scanner data available."

    filt = scanner_df[scanner_df["Type"].isin(cfg.get("trade_types", []))].copy()
    lines = [f"Rates Dashboard Alert — {datetime.now().strftime('%d %b %Y')}", "=" * 50, ""]

    # Top N by Sharpe
    top = filt.dropna(subset=["Sharpe"]).nlargest(cfg.get("top_n", 10), "Sharpe")
    if not top.empty:
        lines.append(f"TOP {len(top)} TRADES BY SHARPE:")
        lines.append("-" * 40)
        for _, r in top.iterrows():
            lines.append(f"  {r['Trade']:20s}  Sharpe={r['Sharpe']:+.2f}  Z={r['Z']:+.2f}  "
                        f"E[Ret]={r['E[Ret]']:+.0f}  Risk={r['Risk']:.0f}  D1W={r['D1W']:+.1f}")
        lines.append("")

    # Z-score extremes
    if cfg.get("include_z_extremes"):
        thresh = cfg.get("z_threshold", 2.0)
        cheap = filt[filt["Z"] < -thresh].sort_values("Z")
        rich = filt[filt["Z"] > thresh].sort_values("Z", ascending=False)
        if not cheap.empty:
            lines.append(f"Z-SCORE EXTREMES (cheap, Z < -{thresh}):")
            lines.append("-" * 40)
            for _, r in cheap.head(10).iterrows():
                lines.append(f"  {r['Trade']:20s}  Z={r['Z']:+.2f}  Sharpe={r['Sharpe']:+.2f}")
            lines.append("")
        if not rich.empty:
            lines.append(f"Z-SCORE EXTREMES (rich, Z > +{thresh}):")
            lines.append("-" * 40)
            for _, r in rich.head(10).iterrows():
                lines.append(f"  {r['Trade']:20s}  Z={r['Z']:+.2f}  Sharpe={r['Sharpe']:+.2f}")
            lines.append("")

    # Big movers
    if cfg.get("include_big_movers"):
        thresh = cfg.get("mover_threshold_bps", 10)
        movers = filt[filt["D1W"].abs() > thresh].sort_values("D1W", key=abs, ascending=False)
        if not movers.empty:
            lines.append(f"BIG WEEKLY MOVERS (|D1W| > {thresh} bps):")
            lines.append("-" * 40)
            for _, r in movers.head(15).iterrows():
                lines.append(f"  {r['Trade']:20s}  D1W={r['D1W']:+.1f}  Z={r['Z']:+.2f}")
            lines.append("")

    lines.append("— Macro Manv Rates Dashboard")
    return "\n".join(lines)


if st.button("Preview Alert", use_container_width=True):
    with st.spinner("Building scanner..."):
        sdf = _build_scanner_df()
    body = _build_alert_body(sdf, cfg)
    st.code(body, language="text")

st.divider()

if st.button("Send Alert Now", type="primary", use_container_width=True):
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    to_email = cfg.get("email", "")

    if not to_email:
        st.error("No recipient email configured.")
    elif not smtp_host:
        st.warning("SMTP not configured — generating preview only.")
        with st.spinner("Building scanner..."):
            sdf = _build_scanner_df()
        body = _build_alert_body(sdf, cfg)
        st.code(body, language="text")

        # Log it
        ALERTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ALERTS_LOG, "a", newline="") as f:
            csv.writer(f).writerow([datetime.now().isoformat(), to_email, "preview_only", len(body)])
        st.info("Alert preview generated. Configure SMTP_HOST/SMTP_USER/SMTP_PASS to enable sending.")
    else:
        with st.spinner("Building and sending..."):
            sdf = _build_scanner_df()
            body = _build_alert_body(sdf, cfg)
            try:
                import smtplib
                from email.mime.text import MIMEText
                msg = MIMEText(body)
                msg["Subject"] = f"Rates Alert — {datetime.now().strftime('%d %b %Y')}"
                msg["From"] = smtp_user
                msg["To"] = to_email
                with smtplib.SMTP(smtp_host, int(os.getenv("SMTP_PORT", "587"))) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_user, [to_email], msg.as_string())
                st.success(f"Alert sent to {to_email}")
            except Exception as e:
                st.error(f"Failed to send: {e}")

        with open(ALERTS_LOG, "a", newline="") as f:
            csv.writer(f).writerow([datetime.now().isoformat(), to_email, "sent", len(body)])

st.divider()
st.markdown("""
**Automated scheduling:** To send alerts automatically, set up a cron job:
```bash
# Daily at 7am
0 7 * * * curl http://localhost:8501/Alerts?send=1
```
Or use the dashboard's scheduled tasks system.
""")
