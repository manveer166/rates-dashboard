"""
12_Alerts.py — Email alert configuration and manual trigger.

Configure daily/weekly scanner alerts that email the top trades by Sharpe,
z-score extremes, and big movers. Alerts can be triggered manually or via cron.
"""

from __future__ import annotations  # PEP 604 unions on Python 3.9

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

    # Last-week curve (6 trading days ago)
    curve_lw = {}
    if len(rdf) >= 7:
        row_lw = rdf.iloc[-6]
        for t in avail:
            if not pd.isna(row_lw[t]):
                curve_lw[t] = float(row_lw[t])

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
        vol_1d = float(chg.tail(63).std())
        rvol = vol_1d * np.sqrt(252) if vol_1d > 0 else np.nan
        ann_cr = cr["total"] * 12
        sharpe = round(ann_cr / rvol, 2) if (rvol and rvol > 0) else np.nan
        d1w = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0.0
        d1d = round((float(s.iloc[-1]) - float(s.iloc[-2])) * 100, 1) if len(s) > 1 else 0.0
        z_d1d = round(d1d / vol_1d, 2) if vol_1d > 0 else 0.0
        z_d1w = round(d1w / (vol_1d * np.sqrt(5)), 2) if vol_1d > 0 else 0.0
        sharpe_lw = np.nan
        z_lw = np.nan
        if curve_lw:
            try:
                cr_lw = fi.forward_carry_rolldown(curve_lw, on_rate, "outright", t)
                ann_cr_lw = cr_lw["total"] * 12
                sharpe_lw = round(ann_cr_lw / rvol, 2) if (rvol and rvol > 0) else np.nan
                z_lw = round(float(fi.zscore_current(s.iloc[:-5], 252)), 2) if len(s) > 257 else np.nan
            except Exception:
                pass
        rows.append({
            "Trade": f"Rcv {t}", "Type": "Outright",
            "Sharpe": sharpe, "Z": round(z, 2),
            "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1) if pd.notna(rvol) else np.nan,
            "D1W": d1w, "D1D": d1d, "Z_D1W": z_d1w, "Z_D1D": z_d1d,
            "Sharpe_LW": sharpe_lw, "Z_LW": z_lw,
        })

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
        vol_1d = float(chg.tail(63).std())
        rvol = vol_1d * np.sqrt(252) if vol_1d > 0 else np.nan
        ann_cr = cr["total"] * 12
        sharpe = round(ann_cr / rvol, 2) if (rvol and rvol > 0) else np.nan
        d1w = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0.0
        d1d = round((float(s.iloc[-1]) - float(s.iloc[-2])) * 100, 1) if len(s) > 1 else 0.0
        z_d1d = round(d1d / vol_1d, 2) if vol_1d > 0 else 0.0
        z_d1w = round(d1w / (vol_1d * np.sqrt(5)), 2) if vol_1d > 0 else 0.0
        sharpe_lw = np.nan
        z_lw = np.nan
        if curve_lw:
            try:
                cr_lw = fi.forward_carry_rolldown(curve_lw, on_rate, "spread", t2, t1)
                ann_cr_lw = cr_lw["total"] * 12
                sharpe_lw = round(ann_cr_lw / rvol, 2) if (rvol and rvol > 0) else np.nan
                z_lw = round(float(fi.zscore_current(s.iloc[:-5], 252)), 2) if len(s) > 257 else np.nan
            except Exception:
                pass
        rows.append({
            "Trade": f"Rcv {t1}/{t2}", "Type": "Curve",
            "Sharpe": sharpe, "Z": round(z, 2),
            "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1) if pd.notna(rvol) else np.nan,
            "D1W": d1w, "D1D": d1d, "Z_D1W": z_d1w, "Z_D1D": z_d1d,
            "Sharpe_LW": sharpe_lw, "Z_LW": z_lw,
        })

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
        vol_1d = float(chg.tail(63).std())
        rvol = vol_1d * np.sqrt(252) if vol_1d > 0 else np.nan
        ann_cr = cr["total"] * 12
        sharpe = round(ann_cr / rvol, 2) if (rvol and rvol > 0) else np.nan
        d1w = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0.0
        d1d = round((float(s.iloc[-1]) - float(s.iloc[-2])) * 100, 1) if len(s) > 1 else 0.0
        z_d1d = round(d1d / vol_1d, 2) if vol_1d > 0 else 0.0
        z_d1w = round(d1w / (vol_1d * np.sqrt(5)), 2) if vol_1d > 0 else 0.0
        sharpe_lw = np.nan
        z_lw = np.nan
        if curve_lw:
            try:
                cr_lw = fi.forward_carry_rolldown(curve_lw, on_rate, "fly", w1, b, w2)
                ann_cr_lw = cr_lw["total"] * 12
                sharpe_lw = round(ann_cr_lw / rvol, 2) if (rvol and rvol > 0) else np.nan
                z_lw = round(float(fi.zscore_current(s.iloc[:-5], 252)), 2) if len(s) > 257 else np.nan
            except Exception:
                pass
        rows.append({
            "Trade": f"Rcv {w1}/{b}/{w2}", "Type": "Fly",
            "Sharpe": sharpe, "Z": round(z, 2),
            "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1) if pd.notna(rvol) else np.nan,
            "D1W": d1w, "D1D": d1d, "Z_D1W": z_d1w, "Z_D1D": z_d1d,
            "Sharpe_LW": sharpe_lw, "Z_LW": z_lw,
        })

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)

    # Compute AbsScore (same formula as 06_Analysis.py)
    def _sig(x, c, k): return 100.0 / (1.0 + np.exp(-k * (x - c)))
    def _abs(row):
        sh = row.get("Sharpe"); z = row.get("Z"); rk = row.get("Risk")
        if pd.isna(sh) or pd.isna(z):
            return 0
        sh_d  = _sig(sh, 0.0, 4.00) * 2 - 100
        z_d   = _sig(z,  0.0, 1.33) * 2 - 100
        rk_q  = _sig(-(rk if pd.notna(rk) else 25.0), -25.0, 0.133) / 100
        raw   = 0.625 * sh_d + 0.375 * z_d
        return int(np.clip(round(raw * (0.4 + 0.6 * rk_q)), -100, 100))
    df["AbsScore"] = df.apply(_abs, axis=1)
    return df


_ABS_SNAPSHOT_FILE = Path(__file__).parent.parent.parent / "data" / "abscore_snapshot.json"
_TRADE_LOG_FILE    = Path(__file__).parent.parent.parent / "data" / "trade_log.csv"


def _load_open_trades_with_levels() -> "pd.DataFrame":
    """Load open trades from trade_log.csv and compute current unrealized P&L."""
    if not _TRADE_LOG_FILE.exists():
        return pd.DataFrame()
    try:
        trades = pd.read_csv(_TRADE_LOG_FILE, dtype={"id": str})
        open_t = trades[trades["status"] == "Open"].copy()
        if open_t.empty:
            return pd.DataFrame()
        # Build current levels from master data (same logic as Trade Tracker page)
        fi = __import__("fixed_income")
        mdf = get_master_df()
        if mdf.empty:
            return open_t
        ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
        avail = [t for t in ALL_TENORS if t in mdf.columns]
        rdf = mdf[avail].ffill(limit=3).dropna(how="all")
        if rdf.empty:
            return open_t
        curve = {t: float(rdf[t].iloc[-1]) for t in avail if not pd.isna(rdf[t].iloc[-1])}
        def _dv01(t):
            return fi.approx_dv01(fi.TENOR_YEARS.get(t, 10.0), curve.get(t, 4.0))
        catalog: dict = {}
        for t in avail:
            if t in curve:
                catalog[f"Rcv {t}"] = round(curve[t], 4)
        for i, t1 in enumerate(avail):
            for t2 in avail[i+1:]:
                if t1 in curve and t2 in curve:
                    ratio = _dv01(t2) / _dv01(t1) if _dv01(t1) > 0 else 1.0
                    lvl = float((rdf[t2].iloc[-1] - ratio * rdf[t1].iloc[-1]) * 100)
                    catalog[f"Rcv {t1}/{t2}"] = round(lvl, 2)
        for i, w1 in enumerate(avail):
            for j, b in enumerate(avail[i+1:], i+1):
                for w2 in avail[j+1:]:
                    if all(x in curve for x in [w1, b, w2]):
                        dw1, db, dw2 = _dv01(w1), _dv01(b), _dv01(w2)
                        wb, ww2 = (2.0 * dw1 / db if db > 0 else 2.0), (dw1 / dw2 if dw2 > 0 else 1.0)
                        lvl = float((wb * rdf[b].iloc[-1] - rdf[w1].iloc[-1] - ww2 * rdf[w2].iloc[-1]) * 100)
                        catalog[f"Rcv {w1}/{b}/{w2}"] = round(lvl, 2)
        currents, unreals = [], []
        for _, row in open_t.iterrows():
            key = str(row["trade"])
            curr = catalog.get(key, float("nan"))
            entry = float(row["entry_level"]) if pd.notna(row.get("entry_level")) else float("nan")
            d_mult = 1.0 if str(row.get("direction", "Receive")) == "Receive" else -1.0
            if pd.notna(curr) and pd.notna(entry):
                ttype = str(row.get("type", "Outright"))
                unreal = round((entry - curr) * 100 * d_mult, 1) if ttype == "Outright" \
                         else round((entry - curr) * d_mult, 1)
            else:
                unreal = float("nan")
            currents.append(curr)
            unreals.append(unreal)
        open_t = open_t.copy()
        open_t["current"] = currents
        open_t["unreal_bps"] = unreals
        return open_t
    except Exception:
        return pd.DataFrame()


def _build_alert_body(scanner_df, cfg):
    """Delegate to the shared alert body builder in analysis/alert_body.py."""
    return _build_alert_body_new(scanner_df, cfg)


# ── Rates MPL chart builders (embedded in email as inline images) ─────────────

import io as _io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as _plt

def _mpl_bytes(fig) -> bytes:
    buf = _io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="#0a1628")
    buf.seek(0)
    return buf.read()

def _mpl_sharpe_scatter(sdf: "pd.DataFrame") -> bytes:
    """Expected Sharpe vs Z-score bubble chart — bubble = |weekly move|."""
    if sdf is None or sdf.empty:
        return b""
    df = sdf.dropna(subset=["Sharpe", "Z", "D1W"]).copy()
    if df.empty:
        return b""
    fig, ax = _plt.subplots(figsize=(11, 6), facecolor="#0a1628")
    ax.set_facecolor("#0a1628")
    colors_map = {"Outright": "#4fc3f7", "Curve": "#f59e0b", "Fly": "#a78bfa",
                  "Curve*": "#fb923c", "Fly*": "#c084fc"}
    max_d = df["D1W"].abs().max() or 1
    sizes = (df["D1W"].abs() / max_d * 900 + 30)
    for ttype in ["Outright", "Curve", "Fly", "Curve*", "Fly*"]:
        sub = df[df["Type"] == ttype]
        if sub.empty:
            continue
        ax.scatter(sub["Z"], sub["Sharpe"],
                   s=sizes[sub.index], c=colors_map.get(ttype, "#94a8c9"),
                   alpha=0.75, edgecolors="white", linewidths=0.5,
                   zorder=3, label=ttype)
    ax.axhline(0, color="white", lw=0.5, ls="--", alpha=0.3)
    ax.axvline(0, color="white", lw=0.5, ls="--", alpha=0.3)
    ax.set_title("Expected Sharpe vs Z-score", color="#e8eef9", fontsize=12, fontweight="bold")
    ax.set_xlabel("Z-score  (low = cheap)", color="#94a8c9", fontsize=9)
    ax.set_ylabel("Expected Sharpe", color="#94a8c9", fontsize=9)
    ax.tick_params(colors="#94a8c9")
    for sp in ax.spines.values():
        sp.set_color("#233e6e")
    ax.grid(True, color="#1a3056", alpha=0.5, ls="--")
    ax.legend(title="Type", title_fontsize=8, fontsize=8, loc="upper left",
              framealpha=0.4, edgecolor="#233e6e", labelcolor="#e8eef9",
              facecolor="#122340").get_title().set_color("#94a8c9")
    ax.text(0.01, -0.06, "Bubble size = |1-week move| (bps) — larger = moved more last week",
            transform=ax.transAxes, color="#6a7e9e", fontsize=8)
    _plt.tight_layout()
    b = _mpl_bytes(fig); _plt.close(fig); return b

def _mpl_return_vs_risk(sdf: "pd.DataFrame") -> bytes:
    """Expected Return vs Risk scatter."""
    if sdf is None or sdf.empty:
        return b""
    df = sdf.dropna(subset=["E[Ret]", "Risk"]).copy()
    if df.empty:
        return b""
    fig, ax = _plt.subplots(figsize=(10, 6), facecolor="#0a1628")
    ax.set_facecolor("#0a1628")
    colors_map = {"Outright": "#4fc3f7", "Curve": "#f59e0b", "Fly": "#a78bfa",
                  "Curve*": "#fb923c", "Fly*": "#c084fc"}
    max_d = df["D1W"].abs().max() if "D1W" in df.columns else 1
    sizes = ((df["D1W"].abs() / (max_d or 1) * 600 + 30) if "D1W" in df.columns
             else pd.Series([60] * len(df), index=df.index))
    for ttype in ["Outright", "Curve", "Fly", "Curve*", "Fly*"]:
        sub = df[df["Type"] == ttype]
        if sub.empty:
            continue
        ax.scatter(sub["Risk"], sub["E[Ret]"],
                   s=sizes[sub.index], c=colors_map.get(ttype, "#94a8c9"),
                   alpha=0.75, edgecolors="white", linewidths=0.5, zorder=3, label=ttype)
    ax.set_title("Expected Return vs Risk", color="#e8eef9", fontsize=12, fontweight="bold")
    ax.set_xlabel("Risk (bps/yr)", color="#94a8c9", fontsize=9)
    ax.set_ylabel("E[Return] (bps/yr)", color="#94a8c9", fontsize=9)
    ax.tick_params(colors="#94a8c9")
    for sp in ax.spines.values():
        sp.set_color("#233e6e")
    ax.grid(True, color="#1a3056", alpha=0.5, ls="--")
    ax.legend(title="Type", title_fontsize=8, fontsize=8, loc="upper left",
              framealpha=0.4, edgecolor="#233e6e", labelcolor="#e8eef9",
              facecolor="#122340").get_title().set_color("#94a8c9")
    _plt.tight_layout()
    b = _mpl_bytes(fig); _plt.close(fig); return b

def _mpl_top_movers(sdf: "pd.DataFrame", top_n: int = 12) -> bytes:
    """Biggest weekly movers bar chart (top + bottom by D1W)."""
    if sdf is None or sdf.empty:
        return b""
    df = sdf.dropna(subset=["D1W"]).copy()
    if df.empty:
        return b""
    df["_abs"] = df["D1W"].abs()
    top = df.nlargest(top_n, "_abs")
    top = top.sort_values("D1W")
    from analysis.alert_body import format_trade_plain
    labels = [format_trade_plain(r["Trade"], r["Type"]) for _, r in top.iterrows()]
    values = top["D1W"].tolist()
    colors = ["#4ade80" if v < 0 else "#f87171" for v in values]
    fig, ax = _plt.subplots(figsize=(10, max(4, len(labels) * 0.45)), facecolor="#0a1628")
    ax.set_facecolor("#0a1628")
    ax.barh(labels, values, color=colors, edgecolor="none", height=0.7)
    ax.axvline(0, color="white", lw=0.5, alpha=0.3)
    ax.set_title(f"Top {top_n} Biggest Weekly Movers (bps)", color="#e8eef9",
                 fontsize=12, fontweight="bold")
    ax.set_xlabel("1-week change (bps)  — green = tightening/richer", color="#94a8c9", fontsize=9)
    ax.tick_params(colors="#94a8c9")
    for sp in ax.spines.values():
        sp.set_color("#233e6e")
    ax.grid(True, color="#1a3056", alpha=0.5, axis="x", ls="--")
    _plt.tight_layout()
    b = _mpl_bytes(fig); _plt.close(fig); return b

def _mpl_curve_snapshot(hist_df: "pd.DataFrame") -> bytes:
    """Yield curve snapshot: current, 1W ago, 1M ago."""
    if hist_df is None or hist_df.empty:
        return b""
    tenors_label = [c for c in ["1M","3M","6M","1Y","2Y","3Y","5Y","7Y","10Y","20Y","30Y"]
                    if c in hist_df.columns]
    if len(tenors_label) < 3:
        return b""
    tenor_x = {"1M": 1/12, "3M": 3/12, "6M": 6/12, "1Y": 1, "2Y": 2, "3Y": 3,
               "5Y": 5, "7Y": 7, "10Y": 10, "20Y": 20, "30Y": 30}
    xs = [tenor_x[t] for t in tenors_label]

    def _snap(shift):
        if len(hist_df) <= shift:
            return None
        row = hist_df.iloc[-(shift + 1)]
        return [float(row[t]) if t in row and pd.notna(row[t]) else None for t in tenors_label]

    cur  = _snap(0)
    w1   = _snap(5)
    m1   = _snap(21)

    def _valid(series):
        return series is not None and any(v is not None for v in series)

    if not _valid(cur):
        return b""

    fig, ax = _plt.subplots(figsize=(10, 5), facecolor="#0a1628")
    ax.set_facecolor("#0a1628")
    def _plot(series, color, label, lw, ls="-"):
        if not _valid(series):
            return
        xy = [(x, v) for x, v in zip(xs, series) if v is not None]
        if xy:
            _xs, _ys = zip(*xy)
            ax.plot(_xs, _ys, color=color, lw=lw, ls=ls, label=label, marker="o",
                    markersize=4)
    _plot(cur, "#4fc3f7", "Current", 2.5)
    _plot(w1,  "#94a8c9", "1W ago",  1.5, "--")
    _plot(m1,  "#6a7e9e", "1M ago",  1.2, ":")
    ax.set_title("Yield Curve Snapshot", color="#e8eef9", fontsize=12, fontweight="bold")
    ax.set_xlabel("Tenor (years)", color="#94a8c9", fontsize=9)
    ax.set_ylabel("Rate (%)", color="#94a8c9", fontsize=9)
    ax.set_xscale("log"); ax.set_xticks(xs)
    ax.set_xticklabels(tenors_label, rotation=45)
    ax.tick_params(colors="#94a8c9")
    for sp in ax.spines.values():
        sp.set_color("#233e6e")
    ax.grid(True, color="#1a3056", alpha=0.5, ls="--")
    ax.legend(fontsize=9, framealpha=0.4, edgecolor="#233e6e",
              labelcolor="#e8eef9", facecolor="#122340")
    _plt.tight_layout()
    b = _mpl_bytes(fig); _plt.close(fig); return b

def _build_rates_chart_images(sdf, hist_df) -> dict:
    """
    Build all rates MPL chart images.
    Returns {chart_id: bytes} — only non-empty entries.
    """
    charts = {
        "rates_curve":   _mpl_curve_snapshot(hist_df),
        "rates_sharpe":  _mpl_sharpe_scatter(sdf),
        "rates_return":  _mpl_return_vs_risk(sdf),
        "rates_movers":  _mpl_top_movers(sdf),
    }
    return {k: v for k, v in charts.items() if v}


def _build_weekly_html(sdf, hist_df, cfg, personal_comment: str = "",
                       section_notes: dict | None = None,
                       chart_images: dict | None = None,
                       use_data_uris: bool = False,
                       open_trades_df: "pd.DataFrame | None" = None) -> str:
    """
    Rich HTML email body — rates-focused, with embedded chart images.
    use_data_uris=True embeds charts as base64 data URIs (for Streamlit preview);
    False (default) uses cid: references suitable for MIME email clients.
    Monday: highest conviction trade + narrative + theme + top-15 table + charts.
    Friday: scorecard + movers + refreshed signals + charts.
    """
    from datetime import date, timedelta
    from analysis.alert_body import (
        format_trade_plain, describe_valuation, derive_tags, theme_summary,
    )

    today  = date.today()
    monday = today - timedelta(days=today.weekday())
    is_fri = today.weekday() == 4
    week_str = monday.strftime("%-d %B %Y")

    BG      = "#0a1628"
    PANEL   = "#122340"
    PANEL2  = "#1a3056"
    ACCENT  = "#4fc3f7"
    ACCENT2 = "#4ade80"
    TEXT1   = "#e8eef9"
    TEXT2   = "#94a8c9"
    TEXT3   = "#6a7e9e"
    RED     = "#f87171"
    DIVIDER = "#233e6e"

    _sn = section_notes or {}

    def _note_html(key: str) -> str:
        text = _sn.get(key, "").strip()
        if not text:
            return ""
        return (
            f"<div style='border-left:3px solid {ACCENT};background:#0e1f3a;"
            f"border-radius:0 4px 4px 0;padding:6px 14px;margin:0 0 8px'>"
            f"<p style='color:{ACCENT};font-size:11px;font-style:italic;margin:0'>"
            f"✏️ {text}</p></div>"
        )

    if sdf is None or sdf.empty:
        return f"<html><body style='background:{BG};color:{TEXT1};font-family:Arial,sans-serif;padding:24px'><p>No scanner data available.</p></body></html>"

    trade_types = cfg.get("trade_types", ["Outright", "Curve", "Fly"])
    filt = sdf[sdf["Type"].isin(trade_types)].dropna(subset=["Sharpe"])
    if filt.empty:
        return f"<html><body style='background:{BG};color:{TEXT1};font-family:Arial,sans-serif;padding:24px'><p>No scanner data available.</p></body></html>"

    # ── HTML helpers ──────────────────────────────────────────────────────

    def _z_bg(z):
        try:
            v = float(str(z).replace("+", ""))
            if v > 2.0:  return "#7f1d1d"
            if v > 1.0:  return "#4a0e0e"
            if v > 0.5:  return "#431407"
            if v < -2.0: return "#166534"
            if v < -1.0: return "#14532d"
            if v < -0.5: return "#052e16"
        except Exception:
            pass
        return PANEL

    def _z_txt(z):
        try:
            if abs(float(str(z).replace("+", ""))) > 1.0:
                return "#ffffff"
        except Exception:
            pass
        return TEXT1

    def _sharpe_bg(s):
        try:
            v = float(str(s).replace("+", ""))
            if v > 1.0:  return "#166534"
            if v > 0.5:  return "#14532d"
            if v < -0.5: return "#7f1d1d"
        except Exception:
            pass
        return PANEL

    def _th(t, al="center"):
        return (f"<th style='background:{PANEL2};color:{ACCENT};padding:6px 10px;"
                f"text-align:{al};font-size:12px;border:1px solid {DIVIDER}'>{t}</th>")

    def _td(t, bg=PANEL, fg=TEXT1, al="center", bold=False):
        fw = "bold" if bold else "normal"
        return (f"<td style='background:{bg};color:{fg};padding:5px 10px;"
                f"text-align:{al};font-size:12px;border:1px solid {DIVIDER};"
                f"font-weight:{fw}'>{t}</td>")

    def section(title):
        return (f"<p style='color:{ACCENT};font-weight:bold;font-size:13px;"
                f"margin:22px 0 8px;letter-spacing:0.5px;text-transform:uppercase'>{title}</p>")

    def body_p(html):
        return (f"<p style='color:{TEXT1};font-size:13px;line-height:1.65;"
                f"margin:6px 0'>{html}</p>")

    def cap(html):
        return f"<p style='color:{TEXT3};font-size:11px;margin:4px 0'>{html}</p>"

    def scanner_table(df, top_n=15, sort_col="Sharpe"):
        rows = df.dropna(subset=[sort_col]).nlargest(top_n, sort_col)
        t = (f"<table style='width:100%;border-collapse:collapse;margin:8px 0'>"
             f"<thead><tr>")
        t += _th("Trade", "left") + _th("Type") + _th("Z") + _th("E[Ret]<br>bps/yr") + _th("Risk<br>bps/yr") + _th("Sharpe") + _th("ΔW<br>bps")
        t += "</tr></thead><tbody>"
        for _, r in rows.iterrows():
            z_s  = f"{r['Z']:+.2f}"    if pd.notna(r.get("Z"))       else "—"
            s_s  = f"{r['Sharpe']:+.2f}" if pd.notna(r.get("Sharpe")) else "—"
            d_s  = f"{r['D1W']:+.1f}"  if pd.notna(r.get("D1W"))     else "—"
            ret_s = f"{r['E[Ret]']:+.0f}" if pd.notna(r.get("E[Ret]")) else "—"
            rsk_s = f"{r['Risk']:.0f}" if pd.notna(r.get("Risk")) else "—"
            t += "<tr>"
            t += _td(format_trade_plain(r["Trade"], r["Type"]), al="left")
            t += _td(r.get("Type", ""))
            t += _td(z_s,  bg=_z_bg(z_s),     fg=_z_txt(z_s))
            t += _td(ret_s)
            t += _td(rsk_s)
            try:
                sfg = "#ffffff" if abs(float(s_s.replace("+", ""))) > 0.5 else TEXT1
            except Exception:
                sfg = TEXT1
            t += _td(s_s, bg=_sharpe_bg(s_s), fg=sfg)
            t += _td(d_s)
            t += "</tr>"
        t += "</tbody></table>"
        return t

    def curve_table(hdf):
        if hdf is None or hdf.empty:
            return cap("Curve data unavailable.")
        tenors = ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
        t = (f"<table style='width:100%;border-collapse:collapse;margin:8px 0'>"
             f"<thead><tr>")
        t += _th("Tenor") + _th("Level (%)") + _th("ΔW (bps)") + _th("Δ1M (bps)") + _th("Z (252d)")
        t += "</tr></thead><tbody>"
        for tenor in tenors:
            if tenor not in hdf.columns:
                continue
            s = hdf[tenor].dropna()
            if len(s) < 2:
                continue
            lv   = f"{float(s.iloc[-1]):.3f}"
            d1w  = f"{(float(s.iloc[-1]) - float(s.iloc[-6]))*100:+.1f}"  if len(s) > 5  else "—"
            d1m  = f"{(float(s.iloc[-1]) - float(s.iloc[-22]))*100:+.1f}" if len(s) > 21 else "—"
            if len(s) >= 252:
                mu = float(s.rolling(252).mean().iloc[-1])
                sd = float(s.rolling(252).std().iloc[-1])
                zv = (float(s.iloc[-1]) - mu) / sd if sd > 0 else float("nan")
                z_s = f"{zv:+.2f}"
            else:
                zv = float("nan"); z_s = "—"
            t += "<tr>"
            t += _td(tenor, fg=TEXT2)
            t += _td(lv)
            # ΔW colour
            try:
                dv = float(d1w)
                bg = "#14532d" if dv < -5 else ("#7f1d1d" if dv > 5 else PANEL)
                fg = "#ffffff" if abs(dv) > 5 else TEXT1
            except Exception:
                bg, fg = PANEL, TEXT1
            t += _td(d1w, bg=bg, fg=fg)
            try:
                mv = float(d1m)
                bg2 = "#14532d" if mv < -5 else ("#7f1d1d" if mv > 5 else PANEL)
                fg2 = "#ffffff" if abs(mv) > 5 else TEXT1
            except Exception:
                bg2, fg2 = PANEL, TEXT1
            t += _td(d1m, bg=bg2, fg=fg2)
            t += _td(z_s, bg=_z_bg(z_s), fg=_z_txt(z_s))
            t += "</tr>"
        t += "</tbody></table>"
        return t

    # ── Header ────────────────────────────────────────────────────────────
    hdr_color = ACCENT2 if is_fri else ACCENT
    label = "RECAP · What happened this week" if is_fri else "SETUP · What to watch this week"
    parts = [
        f"<html><body style='font-family:Inter,Arial,sans-serif;background:{BG};"
        f"color:{TEXT1};padding:24px;max-width:720px;margin:0 auto'>",

        f"<div style='border-left:4px solid {hdr_color};padding-left:16px;margin-bottom:20px'>",
        f"<h1 style='color:{TEXT1};font-size:22px;margin:0;line-height:1.3'>Rates Weekly — Macro Manv</h1>",
        f"<p style='color:{hdr_color};font-size:13px;margin:4px 0 0'>{label}&nbsp;·&nbsp;Week of {week_str}</p>",
        "</div>",
        f"<hr style='border:none;border-top:1px solid {DIVIDER};margin:0 0 16px'>",
    ]

    if personal_comment.strip():
        parts.append(
            f"<div style='background:#061a0e;border:1px solid {ACCENT2};"
            f"border-radius:6px;padding:14px 16px;margin:0 0 20px'>"
            f"<div style='color:{ACCENT2};font-size:10px;font-weight:700;"
            f"text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px'>"
            f"✏️ Personal note</div>"
            f"<p style='color:{TEXT1};font-size:13px;line-height:1.65;margin:0'>"
            f"{personal_comment.strip()}</p></div>"
        )

    if not is_fri:
        # ── MONDAY content ─────────────────────────────────────────────────
        top  = filt.nlargest(cfg.get("top_n", 10), "Sharpe")
        best = top.iloc[0]
        best_name = format_trade_plain(best["Trade"], best["Type"])
        best_z    = float(best["Z"])
        tags_str  = "  ".join(derive_tags(best, top=True))

        if best_z < -0.5:
            why = "Dislocation has not fully normalised — carry is supportive while valuation remains cheap."
        elif best_z > 0.5:
            why = "Carry and roll are doing the work; signal remains elevated despite rich valuation."
        else:
            why = "Model signal is strongest here with valuation broadly in line with history."

        similar = [format_trade_plain(r["Trade"], r["Type"]) for _, r in top.iloc[1:4].iterrows()]
        theme   = theme_summary(top)
        anchor  = "/".join(theme["common"][:2]) if theme["common"] else "the curve"

        mov     = filt.reindex(filt["D1W"].abs().sort_values(ascending=False).index)
        biggest = mov.iloc[0]
        big_name = format_trade_plain(biggest["Trade"], biggest["Type"])
        big_z    = float(biggest["Z"])
        cheap_rich = "cheap" if big_z < -0.5 else ("rich" if big_z > 0.5 else "near fair value")

        parts += [
            _note_html("curve_snapshot") + section("CURVE SNAPSHOT"),
            curve_table(hist_df),

            _note_html("top_signal") + section("HIGHEST CONVICTION RV SIGNAL"),
            f"<p style='color:{ACCENT};font-size:18px;font-weight:bold;margin:4px 0'>Receive {best_name}</p>",
            f"<p style='color:{TEXT3};font-size:11px;margin:2px 0 10px'>{tags_str}</p>",

            body_p(
                f"Top-ranked structure on the screen with Sharpe <b>{best['Sharpe']:+.2f}</b>, "
                f"expected return <b>{best['E[Ret]']:+.0f} bps/yr</b>, and risk {best['Risk']:.0f}. "
                f"The structure {describe_valuation(best_z)} (z-score {best_z:+.2f})."
            ),
            body_p(f"<b>Why now:</b> {why}"),
            body_p("<b>Regime fit:</b> Best in a lower-vol, shock-fading environment."),
            body_p("<b>Risk:</b> Renewed long-end selling or vol spike would delay reversion."),

            _note_html("theme") + section("THEME BUILDING ACROSS THE CURVE"),
            body_p(
                f"Signals are clustering in <b>{anchor}</b>-led receiver structures"
                + (f", including {', '.join(similar)}. " if similar else ". ")
                + "This suggests the opportunity is thematic rather than isolated."
            ),

            _note_html("movers") + section("MOST STRETCHED — WATCH FOR REVERSAL"),
            body_p(
                f"<b>Receive {big_name}</b> moved {biggest['D1W']:+.1f} bps last week "
                f"and now screens {cheap_rich} at z-score {big_z:+.2f}. "
                "Watch for mean reversion if vol stabilises."
            ),

            _note_html("top_table") + section("TOP SIGNALS BY SHARPE"),
            scanner_table(filt, top_n=15, sort_col="Sharpe"),
        ]

        # ── AbsScore top-3 section (Monday) ──────────────────────────────
        if "AbsScore" in filt.columns:
            top3_abs = filt.reindex(filt["AbsScore"].abs().sort_values(ascending=False).index).head(3)
            abs_html = (f"<table style='width:100%;border-collapse:collapse;margin:8px 0'>"
                        f"<thead><tr>{_th('Trade','left')}{_th('AbsScore')}{_th('Sharpe')}{_th('Z')}{_th('Direction')}</tr></thead><tbody>")
            snap_rows = []
            for _, r in top3_abs.iterrows():
                sc     = int(r["AbsScore"])
                sc_col = ACCENT2 if sc > 0 else RED
                dirn   = "📈 Receive" if sc > 0 else "📉 Pay"
                sh_s   = f"{r['Sharpe']:+.2f}"
                z_s    = f"{float(r['Z']):+.2f}"
                abs_html += (f"<tr>{_td(format_trade_plain(r['Trade'],r['Type']),'left')}"
                             f"{_td(f'{sc:+d}',fg=sc_col,bold=True)}"
                             f"{_td(sh_s)}{_td(z_s,bg=_z_bg(r['Z']),fg=_z_txt(r['Z']))}"
                             f"{_td(dirn,fg=sc_col)}</tr>")
                snap_rows.append({"trade": r["Trade"], "type": r["Type"],
                                  "abs_score": sc, "sharpe": float(r["Sharpe"]),
                                  "z": float(r["Z"])})
            abs_html += "</tbody></table>"
            parts += [section("TOP 3 COMPOSITE SCORES — TRACKING INTO FRIDAY"), abs_html,
                      cap("|AbsScore| ranked. +100 = max receive conviction, −100 = max pay conviction.")]
            # Save Monday snapshot for Friday comparison
            try:
                import json as _json
                _ABS_SNAPSHOT_FILE.write_text(_json.dumps(
                    {"date": str(today), "top3": snap_rows}, indent=2))
            except Exception:
                pass

    else:
        # ── FRIDAY content ─────────────────────────────────────────────────
        top15  = filt.nlargest(15, "Sharpe")
        movers = filt.reindex(filt["D1W"].abs().sort_values(ascending=False).index).head(12)

        # Scorecard: did signals pay this week?
        # Only directional signals count: |Z| > 0.5 (rate clearly cheap/rich vs history).
        # Direction from Z: Z > 0 → rate HIGH/cheap → Receive bias → Worked if rate FELL.
        #   Outrights:    D1W < 0 = rate fell = receive gained.
        #   Spreads/Flies: D1W > 0 = spread/fly widened = receive gained.
        # Threshold: |D1W| > 2 bps to avoid noise.
        hits = misses = flats = 0
        sc_rows = []
        for _, r in top15.iterrows():
            d    = float(r["D1W"]) if pd.notna(r.get("D1W")) else 0.0
            z    = float(r.get("Z", 0))
            ttype = str(r.get("Type", "Outright"))
            # Only count as directional if Z is meaningful
            if abs(z) <= 0.5:
                verdict, v_col = "→ Neutral", TEXT2
            else:
                # Receive bias when Z > 0 (rate high vs history = cheap to receive)
                is_receive_biased = z > 0
                # For outrights: receive works when rate falls (D1W < 0)
                # For spreads/flies: receive works when spread/fly widens (D1W > 0)
                is_outright = ttype == "Outright"
                if abs(d) <= 2:
                    verdict, v_col = "→ Flat", TEXT2
                elif is_receive_biased:
                    worked = (d < -2) if is_outright else (d > 2)
                    verdict, v_col = ("✓ Worked", ACCENT2) if worked else ("✗ Against", RED)
                else:
                    # Z < -0.5: rate LOW vs history — no strong receive signal; carry-only
                    verdict, v_col = "→ Carry", TEXT2
            if verdict.startswith("✓"):   hits   += 1
            elif verdict.startswith("✗"): misses += 1
            sc_rows.append((format_trade_plain(r["Trade"], r["Type"]),
                            f"{r['Sharpe']:+.2f}", f"{z:+.2f}",
                            f"{d:+.1f}", verdict, v_col))

        n_dir = hits + misses
        hit_rate = hits / n_dir if n_dir > 0 else 0.0
        hr_col = ACCENT2 if hit_rate >= 0.65 else ("#f59e0b" if hit_rate >= 0.45 else RED)
        verdict_text = (
            "Strong week — Z-score signals were directionally correct." if hit_rate >= 0.65
            else "Mixed signals — roughly half the directional calls were correct." if hit_rate >= 0.45
            else "Challenging week — model struggled with direction. Worth reviewing macro context."
        )

        # KPI block
        kpi_style = (f"display:inline-block;background:{PANEL};border-radius:8px;"
                     f"padding:12px 20px;margin:4px;text-align:center;min-width:100px")
        kpis = (
            f"<div style='margin:12px 0'>"
            f"<div style='{kpi_style}'><div style='color:{TEXT3};font-size:11px'>Hit Rate</div>"
            f"<div style='color:{hr_col};font-size:22px;font-weight:bold'>{hit_rate:.0%}</div>"
            f"<div style='color:{TEXT3};font-size:10px'>{hits}/{n_dir} directional</div></div>"
            f"<div style='{kpi_style}'><div style='color:{TEXT3};font-size:11px'>Correct</div>"
            f"<div style='color:{ACCENT2};font-size:22px;font-weight:bold'>{hits}</div></div>"
            f"<div style='{kpi_style}'><div style='color:{TEXT3};font-size:11px'>Against</div>"
            f"<div style='color:{RED};font-size:22px;font-weight:bold'>{misses}</div></div>"
            f"</div>"
        )

        # Scorecard table
        sc_html = (f"<table style='width:100%;border-collapse:collapse;margin:8px 0'>"
                   f"<thead><tr>")
        sc_html += _th("Trade", "left") + _th("Sharpe") + _th("Z") + _th("D1W bps") + _th("Verdict")
        sc_html += "</tr></thead><tbody>"
        for trade, sharpe, z_s, d_s, verdict, v_col in sc_rows:
            sc_html += "<tr>"
            sc_html += _td(trade, al="left")
            sc_html += _td(sharpe)
            sc_html += _td(z_s, bg=_z_bg(z_s), fg=_z_txt(z_s))
            try:
                dv = float(d_s)
                d_bg = "#14532d" if dv > 2 else ("#7f1d1d" if dv < -2 else PANEL)
            except Exception:
                d_bg = PANEL
            sc_html += _td(d_s, bg=d_bg)
            sc_html += _td(verdict, fg=v_col, bold=True)
            sc_html += "</tr>"
        sc_html += "</tbody></table>"

        # ── Recommended trades block ──────────────────────────────────────
        rec_html = ""
        _open = open_trades_df if (open_trades_df is not None and not open_trades_df.empty) else pd.DataFrame()
        if not _open.empty:
            rec_html = (f"<table style='width:100%;border-collapse:collapse;margin:8px 0'>"
                        f"<thead><tr>{_th('Trade','left')}{_th('Direction')}{_th('Date On')}"
                        f"{_th('Entry')}{_th('Current')}{_th('P&L (bps)')}</tr></thead><tbody>")
            for _, tr in _open.iterrows():
                unreal = tr.get("unreal_bps", float("nan"))
                unreal_s = f"{float(unreal):+.1f}" if pd.notna(unreal) else "—"
                pnl_col = ACCENT2 if pd.notna(unreal) and float(unreal) >= 0 else RED
                curr = tr.get("current", float("nan"))
                curr_s = f"{float(curr):.4f}" if pd.notna(curr) else "—"
                entry_s = f"{float(tr['entry_level']):.4f}" if pd.notna(tr.get('entry_level')) else "—"
                rec_html += (f"<tr>{_td(str(tr['trade']),'left')}"
                             f"{_td(str(tr.get('direction','—')))}"
                             f"{_td(str(tr.get('date','—')))}"
                             f"{_td(entry_s)}"
                             f"{_td(curr_s)}"
                             f"{_td(unreal_s,fg=pnl_col,bold=True)}</tr>")
            rec_html += "</tbody></table>"

        # ── AbsScore Mon→Fri tracker ──────────────────────────────────────
        abs_tracker_html = ""
        if "AbsScore" in filt.columns and _ABS_SNAPSHOT_FILE.exists():
            try:
                import json as _json
                snap = _json.loads(_ABS_SNAPSHOT_FILE.read_text())
                snap_rows = snap.get("top3", [])
                snap_date = snap.get("date", "Monday")
                if snap_rows:
                    abs_tracker_html = (
                        f"<table style='width:100%;border-collapse:collapse;margin:8px 0'>"
                        f"<thead><tr>{_th('Trade','left')}{_th(f'AbsScore {snap_date}')}"
                        f"{_th('AbsScore Now')}{_th('Δ Score')}{_th('D1W bps')}</tr></thead><tbody>")
                    for sr in snap_rows:
                        tname = sr["trade"]
                        mon_sc = int(sr["abs_score"])
                        match = filt[filt["Trade"] == tname]
                        fri_sc = int(match.iloc[0]["AbsScore"]) if not match.empty else None
                        d1w_val = float(match.iloc[0]["D1W"]) if not match.empty and pd.notna(match.iloc[0].get("D1W")) else None
                        fri_s = f"{fri_sc:+d}" if fri_sc is not None else "—"
                        fri_col = (ACCENT2 if fri_sc and fri_sc > 0 else RED) if fri_sc is not None else TEXT2
                        delta = fri_sc - mon_sc if fri_sc is not None else None
                        delta_s = f"{delta:+d}" if delta is not None else "—"
                        delta_col = ACCENT2 if (delta or 0) > 0 else (RED if (delta or 0) < 0 else TEXT2)
                        d1w_s = f"{d1w_val:+.1f}" if d1w_val is not None else "—"
                        d1w_bg = "#14532d" if d1w_val and d1w_val > 2 else ("#7f1d1d" if d1w_val and d1w_val < -2 else PANEL)
                        abs_tracker_html += (
                            f"<tr>{_td(format_trade_plain(tname, sr.get('type','')),'left')}"
                            f"{_td(f'{mon_sc:+d}')}"
                            f"{_td(fri_s,fg=fri_col,bold=True)}"
                            f"{_td(delta_s,fg=delta_col)}"
                            f"{_td(d1w_s,bg=d1w_bg)}</tr>")
                    abs_tracker_html += "</tbody></table>"
            except Exception:
                pass

        parts += [
            _note_html("curve") + section("THIS WEEK'S CURVE MOVES"),
            curve_table(hist_df),
        ]
        if rec_html:
            parts += [section("RECOMMENDED TRADES — LIVE TRACK RECORD"), rec_html,
                      cap("Entry vs current level. P&L in bps. Source: Trade Tracker.")]
        if abs_tracker_html:
            parts += [section("COMPOSITE SCORE TRACKER — MONDAY → FRIDAY"), abs_tracker_html,
                      cap("AbsScore: +100 = max receive conviction, −100 = max pay conviction.")]
        parts += [
            _note_html("scorecard") + section("SIGNAL SCORECARD — DID THE TOP SIGNALS DELIVER?"),
            kpis,
            f"<p style='color:{hr_col};font-size:14px;font-weight:bold;margin:8px 0'>{verdict_text}</p>",
            sc_html,
            cap("Directional signal = |Z(1Y)| > 0.5 with receive bias (Z > 0). "
                "Outrights: Worked = rate fell. Spreads/Flies: Worked = spread widened. "
                "Neutral/Carry rows excluded from hit rate."),

            _note_html("movers_fri") + section("BIGGEST WEEKLY MOVERS"),
            scanner_table(movers, top_n=12, sort_col="D1W"),

            _note_html("next_week") + section("INTO NEXT WEEK — REFRESHED TOP SIGNALS"),
            scanner_table(filt, top_n=10, sort_col="Sharpe"),
        ]

    # ── Inline chart images ───────────────────────────────────────────────
    _imgs = chart_images or {}
    _chart_titles = {
        "rates_curve":  "Yield Curve Snapshot",
        "rates_sharpe": "Expected Sharpe vs Z-score",
        "rates_return": "Expected Return vs Risk",
        "rates_movers": "Biggest Weekly Movers",
    }
    if _imgs:
        import base64 as _b64
        parts.append(f"<hr style='border:none;border-top:1px solid {DIVIDER};margin:20px 0'>")
        parts.append(f"<p style='color:{ACCENT};font-weight:bold;font-size:13px;margin:16px 0 4px'>CHARTS</p>")
        for cid, title in _chart_titles.items():
            if cid in _imgs:
                if use_data_uris:
                    b64 = _b64.b64encode(_imgs[cid]).decode()
                    src = f"data:image/png;base64,{b64}"
                else:
                    src = f"cid:{cid}"
                parts.append(
                    f"<p style='color:{TEXT2};font-size:12px;margin:14px 0 4px'>{title}</p>"
                    f"<img src='{src}' style='max-width:680px;border-radius:8px;display:block'><br>"
                )

    parts += [
        f"<hr style='border:none;border-top:1px solid {DIVIDER};margin:20px 0'>",
        cap("Macro Manv Rates Dashboard &nbsp;·&nbsp; Model estimates only &nbsp;·&nbsp; Not investment advice"),
        f"<p style='color:{TEXT3};font-size:11px'>Full formatted report attached as PDF.</p>",
        "</body></html>",
    ]
    return "".join(parts)


# ── Compose panel (admin only) — personal note + section annotations ─────────
_pc = ""
_sn: dict = {}
if is_admin():
    with st.expander("📰 Market news (Macro Manv · Bloomberg · FT)", expanded=False):
        from dashboard.components.news import render_news_panel
        render_news_panel(limit_per_source=5, campaign="alerts_panel")

    with st.expander("🏛️ Central banks (Fed · ECB · BoE press releases)", expanded=False):
        from dashboard.components.news import render_central_banks_panel
        render_central_banks_panel(limit_per_source=5)

    with st.expander("✏️ Compose — personal note & section annotations", expanded=False):
        st.markdown(
            "Optionally add a **personal note** at the top of the email/PDF, "
            "and short annotations above any section. Leave blank to omit."
        )
        _pc = st.text_area(
            "Personal intro / comment",
            placeholder="This week I've been watching the front-end closely…",
            height=90,
            key="wk_personal_comment",
        )
        st.markdown("---")

        # ── Load preview data (cached — instant after first call) ─────────
        _prev_sdf  = _build_scanner_df()
        _prev_hist = get_master_df()
        _prev_filt = pd.DataFrame()
        if not _prev_sdf.empty:
            _tt = cfg.get("trade_types", ["Outright", "Curve", "Fly"])
            _prev_filt = _prev_sdf[_prev_sdf["Type"].isin(_tt)].dropna(subset=["Sharpe"])

        def _mini_scanner_df(df, top_n=5, sort_by="Sharpe"):
            if df is None or df.empty:
                return
            rows = df.dropna(subset=[sort_by]).nlargest(top_n, sort_by)[
                ["Trade", "Type", "Sharpe", "Z", "D1W"]
            ].copy()
            rows["Sharpe"] = rows["Sharpe"].map(lambda x: f"{x:+.2f}" if pd.notna(x) else "—")
            rows["Z"]      = rows["Z"].map(lambda x: f"{x:+.2f}"      if pd.notna(x) else "—")
            rows["D1W"]    = rows["D1W"].map(lambda x: f"{x:+.1f}"    if pd.notna(x) else "—")
            rows.rename(columns={"D1W": "ΔWk bps"}, inplace=True)
            st.dataframe(rows, hide_index=True, use_container_width=True)

        def _mini_movers_df(df, top_n=5):
            if df is None or df.empty:
                return
            _m = df.copy()
            _m["_abs"] = _m["D1W"].abs()
            rows = _m.nlargest(top_n, "_abs")[["Trade", "Type", "D1W", "Z", "Sharpe"]].copy()
            rows["Sharpe"] = rows["Sharpe"].map(lambda x: f"{x:+.2f}" if pd.notna(x) else "—")
            rows["Z"]      = rows["Z"].map(lambda x: f"{x:+.2f}"      if pd.notna(x) else "—")
            rows["D1W"]    = rows["D1W"].map(lambda x: f"{x:+.1f}"    if pd.notna(x) else "—")
            rows.rename(columns={"D1W": "ΔWk bps"}, inplace=True)
            st.dataframe(rows, hide_index=True, use_container_width=True)

        def _mini_stretched_df(df, top_n=5):
            if df is None or df.empty:
                return
            _s = df.copy()
            _s["_absz"] = _s["Z"].abs()
            rows = _s.nlargest(top_n, "_absz")[["Trade", "Type", "Z", "D1W", "Sharpe"]].copy()
            rows["Sharpe"] = rows["Sharpe"].map(lambda x: f"{x:+.2f}" if pd.notna(x) else "—")
            rows["Z"]      = rows["Z"].map(lambda x: f"{x:+.2f}"      if pd.notna(x) else "—")
            rows["D1W"]    = rows["D1W"].map(lambda x: f"{x:+.1f}"    if pd.notna(x) else "—")
            rows.rename(columns={"D1W": "ΔWk bps"}, inplace=True)
            st.dataframe(rows, hide_index=True, use_container_width=True)

        def _mini_curve_df(hdf):
            if hdf is None or hdf.empty:
                return
            tenors = [c for c in ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"] if c in hdf.columns]
            rows = []
            for t in tenors:
                s = hdf[t].dropna()
                if len(s) < 2:
                    continue
                d1w = (float(s.iloc[-1]) - float(s.iloc[-6]))*100  if len(s) > 5  else float("nan")
                d1m = (float(s.iloc[-1]) - float(s.iloc[-22]))*100 if len(s) > 21 else float("nan")
                rows.append({
                    "Tenor": t,
                    "Level": f"{float(s.iloc[-1]):.3f}%",
                    "ΔWk bps": f"{d1w:+.1f}" if pd.notna(d1w) else "—",
                    "Δ1M bps": f"{d1m:+.1f}" if pd.notna(d1m) else "—",
                })
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        # ── Section note inputs with inline data previews ─────────────────
        st.caption("**Section notes** — 1–2 lines above each section (both Mon & Fri where applicable)")

        # -- Introduction (no preview needed) --
        _sn["intro"] = st.text_input("📌 Introduction", key="sn_intro", placeholder="Week starts with…")
        st.markdown("---")

        # Monday sections
        st.caption("**Monday — Week Ahead**")
        _c1, _c2 = st.columns([1, 1])
        with _c1:
            _sn["curve_snapshot"] = st.text_input(
                "📌 Curve snapshot",
                key="sn_curve_mon", placeholder="Front end has been…")
        with _c2:
            with st.expander("📊 current curve levels", expanded=False):
                _mini_curve_df(_prev_hist)

        _c1, _c2 = st.columns([1, 1])
        with _c1:
            _sn["top_signal"] = st.text_input(
                "📌 Highest conviction trade",
                key="sn_topsig", placeholder="This trade stands out because…")
        with _c2:
            with st.expander("📊 top 3 signals by Sharpe", expanded=False):
                _mini_scanner_df(_prev_filt, top_n=3, sort_by="Sharpe")

        _c1, _c2 = st.columns([1, 1])
        with _c1:
            _sn["theme"] = st.text_input(
                "📌 Theme / clustering",
                key="sn_theme", placeholder="Pattern this week…")
        with _c2:
            with st.expander("📊 top 5 signals — spot themes", expanded=False):
                _mini_scanner_df(_prev_filt, top_n=5, sort_by="Sharpe")

        _c1, _c2 = st.columns([1, 1])
        with _c1:
            _sn["movers"] = st.text_input(
                "📌 Most stretched / Watch for reversal",
                key="sn_movers", placeholder="Watch for mean reversion…")
        with _c2:
            with st.expander("📊 most stretched by |Z-score|", expanded=False):
                _mini_stretched_df(_prev_filt, top_n=5)

        _c1, _c2 = st.columns([1, 1])
        with _c1:
            _sn["top_table"] = st.text_input(
                "📌 Top signals table context",
                key="sn_toptbl", placeholder="Broad screen context…")
        with _c2:
            with st.expander("📊 top 10 signals (full table preview)", expanded=False):
                _mini_scanner_df(_prev_filt, top_n=10, sort_by="Sharpe")

        st.markdown("---")

        # Friday sections
        st.caption("**Friday — Week in Review**")
        _c1, _c2 = st.columns([1, 1])
        with _c1:
            _sn["curve"] = st.text_input(
                "📌 Curve moves this week",
                key="sn_curve_fri", placeholder="Key move this week was…")
        with _c2:
            with st.expander("📊 curve levels & weekly change", expanded=False):
                _mini_curve_df(_prev_hist)

        _c1, _c2 = st.columns([1, 1])
        with _c1:
            _sn["scorecard"] = st.text_input(
                "📌 Signal scorecard context",
                key="sn_scorecard", placeholder="Model context…")
        with _c2:
            with st.expander("📊 top signals from last week", expanded=False):
                _mini_scanner_df(_prev_filt, top_n=5, sort_by="Sharpe")

        _c1, _c2 = st.columns([1, 1])
        with _c1:
            _sn["movers_fri"] = st.text_input(
                "📌 Biggest weekly movers",
                key="sn_movfri", placeholder="Biggest move driven by…")
        with _c2:
            with st.expander("📊 biggest movers by |ΔWk bps|", expanded=False):
                _mini_movers_df(_prev_filt, top_n=5)

        _c1, _c2 = st.columns([1, 1])
        with _c1:
            _sn["next_week"] = st.text_input(
                "📌 Into next week",
                key="sn_nextwk", placeholder="Watch for…")
        with _c2:
            with st.expander("📊 refreshed top signals", expanded=False):
                _mini_scanner_df(_prev_filt, top_n=5, sort_by="Sharpe")

        _sn = {k: v for k, v in _sn.items() if v.strip()}

# ── Daily text alert ───────────────────────────────────────────────────────────
st.divider()
st.subheader("📩 Daily Morning Alert  ·  6:30 am")
st.caption(
    "Plain-text email sent every morning at 06:30 with the top 5 trades by Sharpe, "
    "biggest overnight movers, and key levels. Fast, mobile-friendly, no attachments."
)

def _build_daily_text(sdf: "pd.DataFrame", cfg: dict) -> str:
    """Build a compact plain-text morning briefing."""
    from datetime import date as _date
    today = _date.today().strftime("%a %d %b %Y")
    SEP = "─" * 47

    lines = [
        f"Macro Manv · Rates Morning Briefing · {today}",
        "=" * 58,
        "",
    ]

    if sdf is None or sdf.empty:
        lines.append("No scanner data available.")
        return "\n".join(lines)

    filt = sdf.dropna(subset=["Sharpe"]).copy()
    if filt.empty:
        lines.append("No scanner data available.")
        return "\n".join(lines)

    # ── COMPOSITE SCORE  (adaptive / non-linear) ─────────────────────────
    # sign(x)*|x|^p amplification before min-max normalisation:
    #   Sharpe p=2 → quadratic: Sh 1.5 >> Sh 0.8 >> Sh 0.3 (outlier dominates)
    #   Z-cheap p=1.5 → super-linear: very cheap Z matters more than modestly cheap
    #   Risk p=1 → linear (less dynamic, acts as tie-breaker)
    # Weights (50/30/20) still apply but extreme signals pull harder within each dimension.
    def _amp(s: pd.Series, power: float) -> pd.Series:
        raw = s.map(lambda x: float(np.sign(x) * abs(x) ** power) if pd.notna(x) else np.nan)
        mn, mx = raw.min(), raw.max()
        if abs(mx - mn) < 1e-9:
            return pd.Series(0.5, index=s.index)
        return (raw - mn) / (mx - mn)

    if len(filt) >= 3:
        _risk = filt["Risk"] if "Risk" in filt.columns else pd.Series(np.nan, index=filt.index)
        _risk_f = _risk.fillna(_risk.max() if _risk.notna().any() else 99.0)
        sh_norm = _amp(filt["Sharpe"], 2.0)   # quadratic: outlier Sharpe strongly dominates
        z_norm  = _amp(-filt["Z"],     1.5)   # 1.5-power: very cheap Z >> mildly cheap
        rk_norm = _amp(-_risk_f,       1.0)   # linear: risk as tie-breaker
        filt["Score"] = (
            0.50 * sh_norm + 0.30 * z_norm + 0.20 * rk_norm
        ).mul(100).round(0).astype(int)
    else:
        filt["Score"] = np.nan

    # ── TOP 5 COMPOSITE SCORE ─────────────────────────────────────────────
    # Adaptive: Sh^2 amplifies outlier Sharpe · Z^1.5 cheap bias · Risk linear
    lines.append("TOP 5 COMPOSITE SCORE  [adaptive · Sh^2 50% · Z^1.5-cheap 30% · Risk 20%]")
    lines.append(SEP)
    for _, r in filt.nlargest(5, "Score").iterrows():
        name   = str(r.get("Trade", ""))
        score  = r.get("Score", float("nan"))
        sharpe = r.get("Sharpe", float("nan"))
        z      = r.get("Z", float("nan"))
        risk   = r.get("Risk", float("nan"))
        sc_s   = f"{int(score):>3}"  if pd.notna(score)  else " — "
        sh_s   = f"{sharpe:+.2f}"    if pd.notna(sharpe) else "  —"
        z_s    = f"{z:+.2f}"         if pd.notna(z)      else "  —"
        rk_s   = f"{risk:.1f}"       if pd.notna(risk)   else " —"
        lines.append(f"  [{sc_s}] {name:<24} Sh {sh_s}  Z(1Y) {z_s}  Vol {rk_s}bps")
    lines.append("")

    # ── TOP 3 BY SHARPE ───────────────────────────────────────────────────
    lines.append("TOP 3 BY SHARPE  (63d ann. vol)")
    lines.append(SEP)
    for _, r in filt.nlargest(3, "Sharpe").iterrows():
        name   = str(r.get("Trade", ""))
        sharpe = r.get("Sharpe", float("nan"))
        z      = r.get("Z", float("nan"))
        ret    = r.get("E[Ret]", float("nan"))
        score  = r.get("Score", float("nan"))
        sh_s   = f"{sharpe:+.2f}" if pd.notna(sharpe) else "  — "
        z_s    = f"{z:+.2f}"      if pd.notna(z)      else "  — "
        ret_s  = f"{ret:+.0f}"    if pd.notna(ret)    else "—"
        sc_s   = f"{int(score):>3}" if pd.notna(score) else " — "
        lines.append(f"  {name:<24} Sh(63d) {sh_s}  Z(1Y) {z_s}  E[Ret] {ret_s}bps  [{sc_s}]")
    lines.append("")

    # ── BOTTOM 3 BY SHARPE ────────────────────────────────────────────────
    lines.append("BOTTOM 3 BY SHARPE  (63d ann. vol)")
    lines.append(SEP)
    for _, r in filt.nsmallest(3, "Sharpe").iterrows():
        name   = str(r.get("Trade", ""))
        sharpe = r.get("Sharpe", float("nan"))
        z      = r.get("Z", float("nan"))
        ret    = r.get("E[Ret]", float("nan"))
        score  = r.get("Score", float("nan"))
        sh_s   = f"{sharpe:+.2f}" if pd.notna(sharpe) else "  — "
        z_s    = f"{z:+.2f}"      if pd.notna(z)      else "  — "
        ret_s  = f"{ret:+.0f}"    if pd.notna(ret)    else "—"
        sc_s   = f"{int(score):>3}" if pd.notna(score) else " — "
        lines.append(f"  {name:<24} Sh(63d) {sh_s}  Z(1Y) {z_s}  E[Ret] {ret_s}bps  [{sc_s}]")
    lines.append("")

    # ── OVERNIGHT MOVES ── top 5 by |Z_D1D| ─────────────────────────────
    if "Z_D1D" in filt.columns and "D1D" in filt.columns:
        ov = filt.dropna(subset=["Z_D1D", "D1D"]).copy()
        ov["_abs_z_d1d"] = ov["Z_D1D"].abs()
        top_ov = ov.nlargest(5, "_abs_z_d1d")
        if not top_ov.empty:
            lines.append("OVERNIGHT MOVES  \u2500\u2500 top 5 by |Z_D1D|")
            lines.append(SEP)
            for _, r in top_ov.iterrows():
                arrow = "\u25b2" if r["D1D"] > 0 else "\u25bc"
                name  = str(r.get("Trade", ""))
                z_d1d = r["Z_D1D"]
                d1d   = r["D1D"]
                lines.append(
                    f"  {arrow} {name:<24} Z {z_d1d:+.2f}  ({d1d:+.1f} bps)"
                )
            lines.append("")

    # ── WEEKLY MOVES ── top 5 by |Z_D1W| ─────────────────────────────────
    if "Z_D1W" in filt.columns and "D1W" in filt.columns:
        wk = filt.dropna(subset=["Z_D1W", "D1W"]).copy()
        wk["_abs_z_d1w"] = wk["Z_D1W"].abs()
        top_wk = wk.nlargest(5, "_abs_z_d1w")
        if not top_wk.empty:
            lines.append("WEEKLY MOVES  \u2500\u2500 top 5 by |Z_D1W|")
            lines.append(SEP)
            for _, r in top_wk.iterrows():
                arrow = "\u25b2" if r["D1W"] > 0 else "\u25bc"
                name  = str(r.get("Trade", ""))
                z_d1w = r["Z_D1W"]
                d1w   = r["D1W"]
                lines.append(
                    f"  {arrow} {name:<24} Z {z_d1w:+.2f}  ({d1w:+.1f} bps)"
                )
            lines.append("")

    # ── EXTREME Z-SCORES  |Z| > 1.5 ──────────────────────────────────────
    extreme_df = filt[filt["Z"].abs() > 1.5].copy()
    if not extreme_df.empty:
        bot5 = extreme_df.nsmallest(5, "Z")
        top5 = extreme_df.nlargest(5, "Z")
        extreme_combined = (
            pd.concat([bot5, top5])
            .drop_duplicates(subset=["Trade"])
            .sort_values("Z")
        )
        lines.append("EXTREME Z-SCORES  |Z(1Y)| > 1.5")
        lines.append(SEP)
        for _, r in extreme_combined.iterrows():
            name = str(r.get("Trade", ""))
            z    = r["Z"]
            tag  = "CHEAP" if z < 0 else "RICH"
            lines.append(f"  {name:<24} Z(1Y)={z:+.2f}  [{tag}]")
        lines.append("")

    # ── E[SHARPE] SIGNAL TABLE ── top 10 by |Sharpe| ─────────────────────
    sig = filt.copy()
    sig["abs_sh"] = sig["Sharpe"].abs()
    top10 = sig.nlargest(10, "abs_sh")
    lines.append("E[SHARPE(63d ann.)] SIGNAL TABLE  \u2500\u2500 top 10 by |Sharpe|")
    lines.append(SEP)
    lines.append(f"  {'Trade':<24} {'Score':>5} {'Sh(63d)':>8} {'Z(1Y)':>7} {'Sh_LW':>8} {'Z_LW':>7}")
    for _, r in top10.iterrows():
        name  = str(r.get("Trade", ""))
        sh    = r.get("Sharpe", float("nan"))
        z     = r.get("Z", float("nan"))
        sh_lw = r.get("Sharpe_LW", float("nan"))
        z_lw  = r.get("Z_LW", float("nan"))
        score = r.get("Score", float("nan"))
        sc_s    = f"{int(score):>5}"  if pd.notna(score) else "   \u2014 "
        sh_s    = f"{sh:>+6.2f}"     if pd.notna(sh)    else "  \u2014  "
        z_s     = f"{z:>+6.2f}"      if pd.notna(z)     else "  \u2014  "
        sh_lw_s = f"{sh_lw:>+8.2f}"  if pd.notna(sh_lw) else "    \u2014   "
        z_lw_s  = f"{z_lw:>+7.2f}"   if pd.notna(z_lw)  else "   \u2014  "
        lines.append(f"  {name:<24} {sc_s} {sh_s} {z_s} {sh_lw_s} {z_lw_s}")
    lines.append("")

    # ── ASCII SCATTER: E[Sharpe] vs Z-score ──────────────────────────────
    # Exclude near-zero Sharpe (rounds to 0 on 0.25 grid — no signal)
    scatter_df = filt.dropna(subset=["Sharpe", "Z"]).copy()
    scatter_df = scatter_df[scatter_df["Sharpe"].abs() >= 0.13]
    if not scatter_df.empty:
        GRID_W = 52

        all_z  = scatter_df["Z"].tolist()
        all_sh = scatter_df["Sharpe"].tolist()
        z_min  = max(-3.5, min(all_z) - 0.3)
        z_max  = min(3.5,  max(all_z) + 0.3)
        sh_min = min(all_sh) - 0.2
        sh_max = max(all_sh) + 0.2

        def _x_col(z_val):
            if z_max == z_min:
                return GRID_W // 2
            return int(round((z_val - z_min) / (z_max - z_min) * (GRID_W - 1)))

        # Build y-levels: unique Sharpe values rounded to 0.25, always include 0.0
        _raw_ylevels = set(round(v / 0.25) * 0.25 for v in all_sh) | {0.0}
        rounded_sh = sorted(_raw_ylevels, reverse=True)
        if len(rounded_sh) > 14:
            # Keep up to 6 positive + 0 + 6 negative levels
            _pos = sorted([v for v in rounded_sh if v > 0], reverse=True)[:6]
            _neg = sorted([v for v in rounded_sh if v < 0], reverse=True)[:6]
            rounded_sh = sorted(_pos + [0.0] + _neg, reverse=True)

        # Column for Z=0 (vertical axis)
        x_zero = max(0, min(GRID_W - 1, _x_col(0.0)))

        # Map each row to its nearest y-level
        def _nearest_ylevel(sh_val):
            return min(rounded_sh, key=lambda y: abs(y - sh_val))

        lines.append("E[SHARPE(63d ann.)] vs Z(1Y)  (x = today  \u00b7 = last week)")
        lines.append("")

        for y_val in rounded_sh:
            is_x_axis = (y_val == 0.0)   # horizontal axis row at Sharpe = 0

            # Collect trades at this y-level, sorted by |Score| so best trades
            # get first pick of label positions.
            # Never plot markers on the axis row itself (y=0 is the axis, not data).
            _all_at_level = [] if is_x_axis else [
                r for _, r in scatter_df.iterrows()
                if _nearest_ylevel(float(r["Sharpe"])) == y_val
            ]
            _all_at_level.sort(key=lambda r: abs(r.get("Score", 0) or 0), reverse=True)

            # Fill background: dashes on horizontal axis, spaces elsewhere
            marker_row = (["─"] * GRID_W) if is_x_axis else ([" "] * GRID_W)
            label_row  = [" "] * GRID_W

            # Vertical axis at Z=0 — │ normally, + at the crossing point
            marker_row[x_zero] = "+" if is_x_axis else "│"

            used_x_cols = set()   # deduplicate: one point per column

            for r in _all_at_level:
                xc = _x_col(float(r["Z"]))
                xc = max(0, min(GRID_W - 1, xc))

                # Skip if this column is already taken by a higher-priority trade
                if xc in used_x_cols:
                    continue

                # Try to place label first — only show x if label fits
                label_placed = False
                if not is_x_axis:
                    raw_label = str(r.get("Trade", "")).replace("Rcv ", "")[:10]
                    for offset in range(3):
                        p = xc + offset
                        if p + len(raw_label) > GRID_W:
                            break
                        if all(label_row[p + i] == " " for i in range(len(raw_label))):
                            for i, ch in enumerate(raw_label):
                                label_row[p + i] = ch
                            label_placed = True
                            break
                else:
                    label_placed = True  # axis row: no label needed, just mark

                if not label_placed:
                    continue  # can't label it → don't mark it

                marker_row[xc] = "x"
                used_x_cols.add(xc)

                # Last-week marker (only if position is free)
                if pd.notna(r.get("Z_LW")):
                    xlw = _x_col(float(r["Z_LW"]))
                    xlw = max(0, min(GRID_W - 1, xlw))
                    if marker_row[xlw] in (" ", "─", "│", "+"):
                        marker_row[xlw] = "\u00b7"

            y_label = f"{y_val:+.2f}" if y_val != 0.0 else "  0.00"
            # No outer box pipes — the │ at x_zero IS the y-axis
            lines.append(f"{y_label:>6} {''.join(marker_row)}")
            if not is_x_axis:
                lines.append(f"{'':>7}{''.join(label_row)}")

        # X-axis tick marks at key z-scores only (−2, −1, 1, 2 — skip 0, it's on the axis)
        lines.append("")
        tick_row   = [" "] * GRID_W
        label_row2 = [" "] * GRID_W
        for tick_z in [-2, -1, 1, 2]:
            if z_min <= tick_z <= z_max:
                xc = _x_col(float(tick_z))
                if 0 <= xc < GRID_W:
                    tick_row[xc] = "|"
                    lbl = str(tick_z)
                    start = xc - len(lbl) // 2
                    for i, ch in enumerate(lbl):
                        if 0 <= start + i < GRID_W:
                            label_row2[start + i] = ch
        # Put 0 label at x_zero
        _zero_lbl_pos = x_zero - 0
        if 0 <= _zero_lbl_pos < GRID_W:
            label_row2[_zero_lbl_pos] = "0"
        lines.append(f"{'':>6} {''.join(tick_row)}")
        lines.append(f"{'':>6} {''.join(label_row2)}")
        lines.append(f"{'':>22} Z-SCORE(1Y) \u2192")
        lines.append("")

    lines += [
        "─" * 57,
        "Macro Manv · macroManv.substack.com",
        "Unsubscribe: reply STOP",
    ]
    return "\n".join(lines)


def _build_daily_html(plain_text: str) -> str:
    """Wrap plain text in a minimal dark HTML email for daily send."""
    BG     = "#0a1628"
    PANEL  = "#122340"
    TEXT1  = "#e8eef9"
    TEXT2  = "#94a8c9"
    ACCENT = "#4fc3f7"
    lines  = plain_text.split("\n")
    rows   = "".join(
        f"<tr><td style='padding:2px 0;font-family:\"Courier New\",monospace;"
        f"font-size:12px;color:{TEXT1 if not ln.startswith('TOP') and not ln.startswith('BIG') and not ln.startswith('EXTREME') and not ln.startswith('Macro') and not ln.startswith('=') else ACCENT};'>"
        f"{ln.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;') or '&nbsp;'}"
        f"</td></tr>"
        for ln in lines
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
        f"The author accepts no liability for any losses arising from use of or reliance "
        f"on this content. Always consult a qualified and regulated financial adviser before "
        f"making any investment or trading decision.</p>"
        f"<p style='color:{TEXT2};font-size:10px;margin-top:8px'>"
        f"Macro Manv · macroManv.substack.com · Unsubscribe: reply STOP</p>"
        f"</body></html>"
    )


def _send_daily_text_gmail(recipients, plain_body: str, html_body: str) -> tuple:
    """Send the daily morning plain-text briefing via Gmail SMTP."""
    import smtplib
    from datetime import date as _date
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from dashboard.state import _secret

    gmail_user = _secret("GMAIL_USER", "")
    gmail_pass = _secret("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass:
        return 0, "Gmail credentials not configured."

    today = _date.today().strftime("%-d %b %Y")
    subject = f"📈 Rates Morning · Macro Manv · {today}"

    sent = 0
    for addr in recipients:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = gmail_user
            msg["To"]      = addr
            msg.attach(MIMEText(plain_body, "plain"))
            msg.attach(MIMEText(html_body,  "html"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
                s.login(gmail_user, gmail_pass)
                s.send_message(msg)
            sent += 1
        except Exception:
            pass
    return sent, None


# Daily alert UI
_da_col1, _da_col2 = st.columns([2, 1])
with _da_col1:
    _showing = bool(st.session_state.get("_daily_preview_text"))
    _btn_label = "✕ Hide Preview" if _showing else "👁 Preview Morning Alert"
    _daily_preview_clicked = st.button(_btn_label, use_container_width=True, key="btn_daily_prev")
    if _daily_preview_clicked:
        if _showing:
            del st.session_state["_daily_preview_text"]
            st.rerun()
        else:
            _sdf_d = _build_scanner_df()
            _plain_d = _build_daily_text(_sdf_d, cfg)
            st.session_state["_daily_preview_text"] = _plain_d
            st.rerun()

with _da_col2:
    _daily_send_clicked = st.button(
        "🚀 Send Now", type="primary", use_container_width=True, key="btn_daily_send"
    )
    if _daily_send_clicked:
        with st.spinner("Sending morning alert…"):
            _sdf_d   = _build_scanner_df()
            _plain_d = _build_daily_text(_sdf_d, cfg)
            _html_d  = _build_daily_html(_plain_d)
            _recip_d = set()
            if cfg.get("email"):
                _recip_d.add(cfg["email"])
            for _sub in _load_subscribers():
                _recip_d.add(_sub["email"])
            if not _recip_d:
                st.error("No recipients configured.")
            else:
                _sent_d, _err_d = _send_daily_text_gmail(list(_recip_d), _plain_d, _html_d)
                if _err_d:
                    st.warning(_err_d)
                elif _sent_d:
                    st.success(f"✅ Morning alert sent to {_sent_d} recipient(s).")
                else:
                    st.error("Failed to send.")

# Show preview inline
if st.session_state.get("_daily_preview_text"):
    st.code(st.session_state["_daily_preview_text"], language=None)

st.caption(
    "⏰ **Scheduled send at 06:30 every weekday** — set up once via cron: "
    "`0 6 30 * * 1-5  cd /path/to/rates-dashboard && python3 -m dashboard.scripts.daily_alert`  "
    "or use the Scheduler tab in your hosting environment."
)

st.divider()

# ── Action buttons ─────────────────────────────────────────────────────────────
st.subheader("📋 Weekly PDF Alert")
col_dl, col_prev, col_pdf, col_send = st.columns(4)

# ── Download PDF (no preview) ──────────────────────────────────────────────
with col_dl:
    if st.button("⬇️ Download PDF", use_container_width=True, key="btn_dl_only"):
        with st.spinner("Generating PDF…"):
            from analysis.weekly_pdf import build_weekly_pdf
            sdf     = _build_scanner_df()
            hist_df = get_master_df()
            try:
                pdf_path  = build_weekly_pdf(sdf, hist_df, cfg,
                                             personal_comment=_pc,
                                             section_notes=_sn)
                st.session_state["_wk_pdf_bytes"] = pdf_path.read_bytes()
                st.session_state["_wk_pdf_name"]  = pdf_path.name
                st.success(f"✅ {pdf_path.name}")
            except Exception as e:
                st.error(f"PDF build failed: {e}")

    if st.session_state.get("_wk_pdf_bytes"):
        st.download_button(
            "💾 Save PDF",
            data=st.session_state["_wk_pdf_bytes"],
            file_name=st.session_state.get("_wk_pdf_name", "rates_weekly.pdf"),
            mime="application/pdf",
            use_container_width=True,
            key="save_wk_pdf",
        )

# ── Preview Email ──────────────────────────────────────────────────────────
with col_prev:
    if st.button("📧 Preview Email", use_container_width=True, key="btn_prev_email"):
        with st.spinner("Building preview…"):
            sdf          = _build_scanner_df()
            hist_df      = get_master_df()
            chart_images = _build_rates_chart_images(sdf, hist_df)
            html         = _build_weekly_html(sdf, hist_df, cfg,
                                              personal_comment=_pc,
                                              section_notes=_sn,
                                              chart_images=chart_images,
                                              use_data_uris=True,
                                              open_trades_df=_load_open_trades_with_levels())
            st.session_state["_wk_preview_html"] = html
    if st.session_state.get("_wk_preview_html"):
        if st.button("✕ Clear", key="clear_email_preview", use_container_width=True):
            del st.session_state["_wk_preview_html"]
            st.rerun()

# ── Preview PDF (with inline viewer) ──────────────────────────────────────
with col_pdf:
    if st.button("📊 Preview PDF", use_container_width=True, key="btn_prev_pdf"):
        with st.spinner("Building PDF…"):
            from analysis.weekly_pdf import build_weekly_pdf
            sdf     = _build_scanner_df()
            hist_df = get_master_df()
            try:
                pdf_path  = build_weekly_pdf(sdf, hist_df, cfg,
                                             personal_comment=_pc,
                                             section_notes=_sn)
                st.session_state["_wk_preview_pdf_bytes"] = pdf_path.read_bytes()
                st.session_state["_wk_preview_pdf_name"]  = pdf_path.name
                st.success(f"✅ {pdf_path.name}")
            except Exception as e:
                st.error(f"PDF build failed: {e}")
    if st.session_state.get("_wk_preview_pdf_bytes"):
        if st.button("✕ Clear", key="clear_pdf_preview", use_container_width=True):
            del st.session_state["_wk_preview_pdf_bytes"]
            st.rerun()

st.divider()

# ── Persistent previews (survive re-renders) ──────────────────────────────
import streamlit.components.v1 as _stcv1
import base64 as _b64mod

if st.session_state.get("_wk_preview_html"):
    st.subheader("📧 Email Preview")
    _stcv1.html(st.session_state["_wk_preview_html"], height=900, scrolling=True)
    if st.button("✕ Close email preview", key="close_email_preview_bot"):
        del st.session_state["_wk_preview_html"]
        st.rerun()
    st.divider()

if st.session_state.get("_wk_preview_pdf_bytes"):
    st.subheader("📊 PDF Preview")
    _pdf_b64 = _b64mod.b64encode(st.session_state["_wk_preview_pdf_bytes"]).decode()
    _stcv1.html(
        f'<iframe src="data:application/pdf;base64,{_pdf_b64}" '
        f'width="100%" height="960" style="border:none;border-radius:8px"></iframe>',
        height=980, scrolling=False,
    )
    _pdl_col, _pclr_col = st.columns(2)
    _pdl_col.download_button(
        "⬇️ Download PDF",
        data=st.session_state["_wk_preview_pdf_bytes"],
        file_name=st.session_state.get("_wk_preview_pdf_name", "rates_weekly.pdf"),
        mime="application/pdf",
        use_container_width=True,
        key="dl_from_preview",
    )
    if _pclr_col.button("✕ Close PDF preview", key="close_pdf_preview_bot", use_container_width=True):
        del st.session_state["_wk_preview_pdf_bytes"]
        st.rerun()
    st.divider()

def _send_alert_gmail(recipients, html_body, plain_body="", pdf_path=None,
                      chart_images: dict | None = None):
    """
    Send rates alert with rich HTML body, inline chart images, and PDF attachment.

    chart_images: {cid: bytes} — keyed by the Content-ID used in the HTML
    (e.g. "rates_sharpe", "rates_curve", etc.)
    """
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.image import MIMEImage
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from datetime import date, timedelta
    from dashboard.state import _secret

    gmail_user = _secret("GMAIL_USER", "")
    gmail_pass = _secret("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass:
        return 0, "Gmail credentials not configured in secrets."

    today  = date.today()
    monday = today - timedelta(days=today.weekday())
    is_fri = today.weekday() == 4
    day_label = "Recap" if is_fri else "Setup"
    default_subject = f"📊 Rates Weekly — Macro Manv · {monday.strftime('%-d %b %Y')} · {day_label}"

    # ── A/B subject test (optional) ───────────────────────────────────────
    # If there's an active subject test for this week, each recipient gets
    # a deterministic 50/50 variant. Otherwise everyone gets the default.
    active_test = None
    try:
        from analysis.ab_test import (
            list_tests, assign_variant, log_send,
        )
        for t in list_tests():
            if (t.get("kind") == "subject"
                    and t.get("started_on") <= str(today)
                    and not t.get("winner")):
                active_test = t
                break
    except Exception:
        active_test = None

    sent = 0
    for addr in recipients:
        try:
            if active_test:
                v = assign_variant(active_test, addr)
                subject = active_test["variant_a"] if v == "A" else active_test["variant_b"]
            else:
                subject = default_subject

            msg = MIMEMultipart("mixed")
            msg["Subject"] = subject
            msg["From"]    = gmail_user
            msg["To"]      = addr

            # Inline images need a related wrapper so CID references resolve
            if chart_images:
                related = MIMEMultipart("related")
                alt = MIMEMultipart("alternative")
                fallback = (plain_body[:800] + "\n\n[Full report attached as PDF]"
                            if plain_body else "Rates Weekly alert. See PDF attachment.")
                alt.attach(MIMEText(fallback, "plain"))
                alt.attach(MIMEText(html_body, "html"))
                related.attach(alt)
                for cid, img_bytes in chart_images.items():
                    img = MIMEImage(img_bytes, "png")
                    img.add_header("Content-ID", f"<{cid}>")
                    img.add_header("Content-Disposition", "inline",
                                   filename=f"{cid}.png")
                    related.attach(img)
                msg.attach(related)
            else:
                alt = MIMEMultipart("alternative")
                fallback = (plain_body[:800] + "\n\n[Full report attached as PDF]"
                            if plain_body else "Rates Weekly alert. See PDF attachment.")
                alt.attach(MIMEText(fallback, "plain"))
                alt.attach(MIMEText(html_body, "html"))
                msg.attach(alt)

            if pdf_path and pdf_path.exists():
                with open(pdf_path, "rb") as f:
                    part = MIMEApplication(f.read(), _subtype="pdf")
                    part["Content-Disposition"] = f'attachment; filename="{pdf_path.name}"'
                    msg.attach(part)

            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
                s.login(gmail_user, gmail_pass)
                s.send_message(msg)
            sent += 1
            # Log the A/B send so the console accumulates accurate counts.
            if active_test:
                try:
                    log_send(active_test, addr, v)
                except Exception:
                    pass
        except Exception:
            pass
    return sent, None


with col_send:
    if st.button("🚀 Send PDF Alert", type="primary", use_container_width=True):
        with st.spinner("Building PDF and sending…"):
            from analysis.weekly_pdf import build_weekly_pdf
            sdf          = _build_scanner_df()
            plain        = _build_alert_body(sdf, cfg)
            hist_df      = get_master_df()
            chart_images = _build_rates_chart_images(sdf, hist_df)
            html         = _build_weekly_html(sdf, hist_df, cfg,
                                              personal_comment=_pc,
                                              section_notes=_sn,
                                              chart_images=chart_images,
                                              open_trades_df=_load_open_trades_with_levels())

            pdf_path = None
            try:
                pdf_path = build_weekly_pdf(sdf, hist_df, cfg,
                                            personal_comment=_pc,
                                            section_notes=_sn)
            except Exception as e:
                st.warning(f"PDF build failed, sending text only: {e}")

            recipients = set()
            if cfg.get("email"):
                recipients.add(cfg["email"])
            for sub in _load_subscribers():
                recipients.add(sub["email"])

            if not recipients:
                st.error("No recipients — add a primary email or wait for subscribers.")
            else:
                sent, err = _send_alert_gmail(
                    list(recipients), html,
                    plain_body=plain,
                    pdf_path=pdf_path,
                    chart_images=chart_images,
                )
                if err:
                    st.warning(err)
                elif sent:
                    label = pdf_path.name if pdf_path else "text email"
                    st.success(f"Sent {label} to {sent} recipient(s).")
                else:
                    st.error("Failed to send to any recipient.")

                ALERTS_LOG.parent.mkdir(parents=True, exist_ok=True)
                with open(ALERTS_LOG, "a", newline="") as f:
                    csv.writer(f).writerow([datetime.now().isoformat(), len(recipients), sent])
