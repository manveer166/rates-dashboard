"""
daily_alert.py — Standalone morning briefing script.

Runs outside of Streamlit (called by cron at 06:30 on weekdays).
Builds the plain-text + HTML morning alert from live data and emails it.

Usage (from project root):
    python3 -m dashboard.scripts.daily_alert

Cron entry (weekdays 06:30 local time):
    30 6 * * 1-5  cd /Users/manveer/rates-dashboard && python3 -m dashboard.scripts.daily_alert >> /tmp/daily_alert.log 2>&1
"""

import sys
import smtplib
import logging
from datetime import date, datetime
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger("daily_alert")


# ── Config helpers ─────────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    import json
    cfg_path = Path(__file__).resolve().parent.parent.parent / "data" / "alerts_config.json"
    try:
        return json.loads(cfg_path.read_text())
    except Exception:
        return {"email": "", "top_n": 5}


def _load_subscribers() -> list:
    import json
    sub_path = Path(__file__).resolve().parent.parent.parent / "data" / "subscribers.json"
    try:
        return json.loads(sub_path.read_text())
    except Exception:
        return []


def _secret(key: str, default: str = "") -> str:
    """Read from streamlit secrets.toml or environment."""
    import os
    if key in os.environ:
        return os.environ[key]
    try:
        import toml
        secrets_path = Path(__file__).resolve().parent.parent.parent / ".streamlit" / "secrets.toml"
        secrets = toml.loads(secrets_path.read_text())
        return secrets.get(key, default)
    except Exception:
        return default


# ── Data loader ────────────────────────────────────────────────────────────────

def _load_scanner_df() -> pd.DataFrame:
    """Build the scanner DataFrame from cached master data."""
    import fixed_income as fi
    from data.fetchers.base import load_cache
    from pathlib import Path as P

    cache_dir = P(__file__).resolve().parent.parent.parent / "data" / "cache"
    master_path = cache_dir / "master.parquet"
    if not master_path.exists():
        log.warning("master.parquet not found — returning empty DataFrame")
        return pd.DataFrame()

    df = pd.read_parquet(master_path)
    if df.empty:
        return pd.DataFrame()

    ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
    TY = fi.TENOR_YEARS
    avail = [t for t in ALL_TENORS if t in df.columns]
    rdf = df[avail].ffill(limit=3).dropna(how="all")

    if len(rdf) < 252:
        log.warning("Not enough history for scanner — need 252 rows")
        return pd.DataFrame()

    on_rate = 5.3
    for col in ["SOFR", "DFF", "EFFR"]:
        if col in df.columns:
            s = df[col].dropna()
            if len(s):
                on_rate = float(s.iloc[-1])
                break

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
        if len(s) < 252:
            continue
        cr    = fi.forward_carry_rolldown(curve, on_rate, "outright", t)
        z     = fi.zscore_current(s, 252)
        chg   = s.diff().dropna() * 100
        rvol  = float(chg.tail(63).std() * np.sqrt(252)) if len(chg) >= 63 else np.nan
        ann_cr = cr["total"] * 12
        sharpe = ann_cr / rvol if rvol and rvol > 0 else np.nan
        d1w   = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0
        rows.append({"Trade": f"Rcv {t}", "Type": "Outright",
                     "Sharpe": round(sharpe, 2), "Z": round(z, 2),
                     "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1), "D1W": d1w})

    pairs = [(avail[i], avail[j]) for i in range(len(avail)) for j in range(i + 1, len(avail))]
    for t1, t2 in pairs:
        d1, d2 = dv01(t1), dv01(t2)
        ratio  = d2 / d1 if d1 > 0 else 1.0
        s      = (rdf[t2] - ratio * rdf[t1]).dropna()
        if len(s) < 252:
            continue
        cr    = fi.forward_carry_rolldown(curve, on_rate, "spread", t2, t1)
        z     = fi.zscore_current(s, 252)
        chg   = s.diff().dropna() * 100
        rvol  = float(chg.tail(63).std() * np.sqrt(252)) if len(chg) >= 63 else np.nan
        ann_cr = cr["total"] * 12
        sharpe = ann_cr / rvol if rvol and rvol > 0 else np.nan
        d1w   = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0
        rows.append({"Trade": f"Rcv {t1}/{t2}", "Type": "Curve",
                     "Sharpe": round(sharpe, 2), "Z": round(z, 2),
                     "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1), "D1W": d1w})

    return pd.DataFrame(rows)


# ── Alert builders ─────────────────────────────────────────────────────────────

def build_plain(sdf: pd.DataFrame, cfg: dict) -> str:
    today = date.today().strftime("%a %d %b %Y")
    lines = [
        f"Macro Manv · Rates Morning Briefing · {today}",
        "=" * 54,
        "",
    ]

    if sdf is None or sdf.empty:
        lines.append("No scanner data available.")
        return "\n".join(lines)

    top_n = cfg.get("top_n", 5)
    filt  = sdf.dropna(subset=["Sharpe"]).copy()

    # ── Composite score: adaptive non-linear amplification ───────────────
    # sign(x)*|x|^p before min-max: extreme values dominate within each dimension
    def _amp(s: pd.Series, power: float) -> pd.Series:
        raw = s.map(lambda x: float(np.sign(x) * abs(x) ** power) if pd.notna(x) else np.nan)
        mn, mx = raw.min(), raw.max()
        if abs(mx - mn) < 1e-9:
            return pd.Series(0.5, index=s.index)
        return (raw - mn) / (mx - mn)

    if len(filt) >= 3:
        _risk = filt["Risk"] if "Risk" in filt.columns else pd.Series(np.nan, index=filt.index)
        _risk_f = _risk.fillna(_risk.max() if _risk.notna().any() else 99.0)
        sh_norm = _amp(filt["Sharpe"], 2.0)
        z_norm  = _amp(-filt["Z"],     1.5)
        rk_norm = _amp(-_risk_f,       1.0)
        filt["Score"] = (
            0.50 * sh_norm + 0.30 * z_norm + 0.20 * rk_norm
        ).mul(100).round(0).astype(int)
    else:
        filt["Score"] = np.nan

    # ── TOP 5 COMPOSITE ───────────────────────────────────────────────────
    lines.append("TOP 5 COMPOSITE SCORE  [adaptive · Sh^2 50% · Z^1.5-cheap 30% · Risk 20%]")
    lines.append("-" * 46)
    for _, r in filt.nlargest(5, "Score").iterrows():
        name  = str(r.get("Trade", ""))
        score = r.get("Score", float("nan"))
        sh_s  = f"{r['Sharpe']:+.2f}" if pd.notna(r.get("Sharpe")) else "—"
        z_s   = f"{r['Z']:+.2f}"      if pd.notna(r.get("Z"))      else "—"
        sc_s  = f"{int(score):>3}"    if pd.notna(score)            else " — "
        lines.append(f"  [{sc_s}] {name:<22} Sh {sh_s}  Z(1Y) {z_s}")
    lines.append("")

    top   = filt.nlargest(top_n, "Sharpe")
    lines.append(f"TOP {top_n} TRADES BY SHARPE  (63d ann. vol)")
    lines.append("-" * 38)
    for _, r in top.iterrows():
        name  = str(r.get("Trade", ""))
        sh_s  = f"{r['Sharpe']:+.2f}" if pd.notna(r.get("Sharpe")) else "—"
        z_s   = f"{r['Z']:+.2f}"      if pd.notna(r.get("Z"))      else "—"
        ret_s = f"{r['E[Ret]']:+.0f}" if pd.notna(r.get("E[Ret]")) else "—"
        d1w_s = f"{r['D1W']:+.1f}"    if pd.notna(r.get("D1W"))    else "—"
        lines.append(f"  {name:<22} Sh(63d) {sh_s}  Z(1Y) {z_s}  E[Ret] {ret_s}bps  ΔWk {d1w_s}bps")
    lines.append("")

    movers = filt.dropna(subset=["D1W"]).copy()
    movers["abs_d1w"] = movers["D1W"].abs()
    top_movers = movers.nlargest(5, "abs_d1w")
    if not top_movers.empty:
        lines.append("BIGGEST WEEKLY MOVERS")
        lines.append("-" * 38)
        for _, r in top_movers.iterrows():
            arrow = "▲" if r["D1W"] > 0 else "▼"
            lines.append(f"  {arrow} {str(r['Trade']):<22} {r['D1W']:+.1f} bps")
        lines.append("")

    extreme = filt[filt["Z"].abs() >= 1.5].sort_values("Z")
    if not extreme.empty:
        lines.append("EXTREME Z-SCORES  (|Z(1Y)| ≥ 1.5)")
        lines.append("-" * 38)
        for _, r in extreme.iterrows():
            tag = "CHEAP" if r["Z"] < 0 else "RICH"
            lines.append(f"  {str(r['Trade']):<22} Z(1Y)={r['Z']:+.2f}  [{tag}]")
        lines.append("")

    DISC = "─" * 57
    lines += [
        DISC,
        "DISCLAIMER",
        "This content provides rates market analysis and trade",
        "ideas for sophisticated market participants. It is not",
        "regulated investment advice and should not be treated",
        "as a personal recommendation. Carry and rolldown",
        "figures are model-based and historically calibrated;",
        "forward-looking outcomes will differ. Z-scores reflect",
        "historical data only. Investments can go up as well as",
        "down — you may get back less than you invest.",
        "The author accepts no liability for any losses.",
        "While care is taken, errors or omissions may occur.",
        DISC,
        "Macro Manv · macroManv.substack.com",
        "Unsubscribe: reply STOP",
    ]
    return "\n".join(lines)


def build_html(plain_text: str) -> str:
    BG, PANEL, TEXT1, TEXT2, ACCENT = "#0a1628", "#122340", "#e8eef9", "#94a8c9", "#4fc3f7"
    _section_starts = ("TOP", "BIG", "EXTREME", "Macro Manv ·", "=" * 10)
    rows = ""
    for ln in plain_text.split("\n"):
        is_header = any(ln.startswith(s) for s in _section_starts) or ln.startswith("=")
        color = ACCENT if is_header else TEXT1
        safe = ln.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") or "&nbsp;"
        rows += (
            f"<tr><td style='padding:2px 0;font-family:\"Courier New\",monospace;"
            f"font-size:12px;color:{color}'>{safe}</td></tr>"
        )
    return (
        f"<html><body style='background:{BG};color:{TEXT1};"
        f"font-family:\"Courier New\",monospace;padding:24px;max-width:600px;margin:0 auto'>"
        f"<table style='width:100%;background:{PANEL};border-radius:8px;"
        f"padding:16px;border-collapse:collapse'>{rows}</table>"
        f"<p style='color:{TEXT2};font-size:10px;margin-top:16px;line-height:1.5'>"
        f"<strong>DISCLAIMER</strong> — This content provides rates market analysis and trade ideas "
        f"for sophisticated market participants. It is not regulated investment advice and should not "
        f"be treated as a personal recommendation. Carry and rolldown figures are model-based and "
        f"historically calibrated; forward-looking outcomes will differ. Z-scores reflect historical "
        f"data only. Investments can go up as well as down — you may get back less than you invest. "
        f"While care is taken, errors or omissions in the data or models may occur. "
        f"The author accepts no liability for any losses arising from use of this content.</p>"
        f"<p style='color:{TEXT2};font-size:10px;margin-top:8px'>"
        f"Macro Manv · macroManv.substack.com · Unsubscribe: reply STOP</p>"
        f"</body></html>"
    )


# ── Sender ─────────────────────────────────────────────────────────────────────

def send(recipients: list, plain: str, html: str) -> int:
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    gmail_user = _secret("GMAIL_USER")
    gmail_pass = _secret("GMAIL_APP_PASSWORD")
    if not gmail_user or not gmail_pass:
        log.error("Gmail credentials not set — add GMAIL_USER and GMAIL_APP_PASSWORD to secrets.toml or env")
        return 0

    today   = date.today().strftime("%-d %b %Y")
    subject = f"📈 Rates Morning · Macro Manv · {today}"
    sent    = 0

    for addr in recipients:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = gmail_user
            msg["To"]      = addr
            msg.attach(MIMEText(plain, "plain"))
            msg.attach(MIMEText(html,  "html"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
                s.login(gmail_user, gmail_pass)
                s.send_message(msg)
            sent += 1
            log.info(f"Sent to {addr}")
        except Exception as e:
            log.error(f"Failed to send to {addr}: {e}")
    return sent


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=== Daily alert starting ===")

    cfg  = _load_cfg()
    subs = _load_subscribers()

    recipients = set()
    if cfg.get("email"):
        recipients.add(cfg["email"])
    for sub in subs:
        if sub.get("email"):
            recipients.add(sub["email"])

    if not recipients:
        log.warning("No recipients configured — exiting")
        sys.exit(0)

    log.info(f"Recipients: {sorted(recipients)}")

    sdf   = _load_scanner_df()
    plain = build_plain(sdf, cfg)
    html  = build_html(plain)

    log.info("Alert body built — sending…")
    n = send(sorted(recipients), plain, html)
    log.info(f"Done — sent to {n}/{len(recipients)} recipients")
