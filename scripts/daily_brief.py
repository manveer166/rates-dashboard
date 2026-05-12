#!/usr/bin/env python3
"""
Generate a Substack-ready morning brief from the dashboard's cached data.

Writes to briefs/YYYY-MM-DD/:
  brief.md   — Markdown skeleton ready to paste into Substack
  curve.png  — Yield-curve snapshot (today vs 1w / 1m ago)

All dashboard links are UTM-tagged so Substack -> dashboard conversions
show up in GA / your analytics layer.

Usage:
    python3 scripts/daily_brief.py

Config (optional, in .streamlit/secrets.toml):
    DASHBOARD_URL = "https://your-dashboard-url.com"

PNG rendering needs `pip install kaleido`. Without it, the script falls
back to an HTML chart and still produces a usable brief.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── DASHBOARD_URL from secrets.toml (optional) ─────────────────────────────
DASHBOARD_URL = "https://your-dashboard-url.com"
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
if SECRETS_PATH.exists() and tomllib:
    try:
        with open(SECRETS_PATH, "rb") as f:
            SECRETS = tomllib.load(f)
        DASHBOARD_URL = SECRETS.get("DASHBOARD_URL", DASHBOARD_URL).rstrip("/")
    except Exception as e:
        logger.warning("Could not read secrets.toml (%s) — using default DASHBOARD_URL.", e)


# ── UTM helper ─────────────────────────────────────────────────────────────
def utm(path: str, campaign: str, date_str: str) -> str:
    path = path.lstrip("/")
    qs = f"utm_source=substack&utm_medium=brief&utm_campaign={campaign}&utm_content={date_str}"
    sep = "/" if path else ""
    return f"{DASHBOARD_URL}{sep}{path}?{qs}"


# ── Scanner (mirrors scripts/send_alert.py::build_scanner) ─────────────────
def build_scanner():
    import numpy as np
    import pandas as pd
    import fixed_income as fi
    from data.fetchers.base import CACHE_DIR

    master = CACHE_DIR / "master.parquet"
    if not master.exists():
        logger.error("No cached data at %s — run the dashboard first.", master)
        return pd.DataFrame(), pd.DataFrame(), {}, []

    df = pd.read_parquet(master)
    df.index = pd.to_datetime(df.index)
    ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
    TY = fi.TENOR_YEARS
    avail = [t for t in ALL_TENORS if t in df.columns]
    rdf = df[avail].ffill(limit=3).dropna(how="all")
    if len(rdf) < 252:
        return pd.DataFrame(), rdf, {}, avail

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
        cr = fi.forward_carry_rolldown(curve, on_rate, "outright", t)
        z = fi.zscore_current(s, 252)
        chg = s.diff().dropna() * 100
        rvol = float(chg.tail(63).std() * np.sqrt(252)) if len(chg) >= 63 else float("nan")
        ann_cr = cr["total"] * 12
        sharpe = ann_cr / rvol if rvol and rvol > 0 else float("nan")
        d1w = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0
        rows.append({"Trade": f"Rcv {t}", "Type": "Outright", "Sharpe": round(sharpe, 2),
                     "Z": round(z, 2), "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1), "D1W": d1w})

    pairs = [(avail[i], avail[j]) for i in range(len(avail)) for j in range(i + 1, len(avail))]
    for t1, t2 in pairs:
        d1, d2 = dv01(t1), dv01(t2)
        ratio = d2 / d1 if d1 > 0 else 1.0
        s = (rdf[t2] - ratio * rdf[t1]).dropna()
        if len(s) < 252:
            continue
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
             for i in range(len(avail)) for j in range(i + 1, len(avail)) for k in range(j + 1, len(avail))]
    for w1, b, w2 in flies:
        dw1, db, dw2 = dv01(w1), dv01(b), dv01(w2)
        wb = 2.0 * (dw1 / db) if db > 0 else 2.0
        ww2 = dw1 / dw2 if dw2 > 0 else 1.0
        s = (wb * rdf[b] - rdf[w1] - ww2 * rdf[w2]).dropna()
        if len(s) < 252:
            continue
        cr = fi.forward_carry_rolldown(curve, on_rate, "fly", w1, b, w2)
        z = fi.zscore_current(s, 252)
        chg = s.diff().dropna() * 100
        rvol = float(chg.tail(63).std() * np.sqrt(252)) if len(chg) >= 63 else float("nan")
        ann_cr = cr["total"] * 12
        sharpe = ann_cr / rvol if rvol and rvol > 0 else float("nan")
        d1w = round((float(s.iloc[-1]) - float(s.iloc[-6])) * 100, 1) if len(s) > 5 else 0
        rows.append({"Trade": f"Rcv {w1}/{b}/{w2}", "Type": "Fly", "Sharpe": round(sharpe, 2),
                     "Z": round(z, 2), "E[Ret]": round(ann_cr, 1), "Risk": round(rvol, 1), "D1W": d1w})

    return (pd.DataFrame(rows) if rows else pd.DataFrame()), rdf, curve, avail


# ── Curve chart ────────────────────────────────────────────────────────────
def render_curve_chart(rdf, avail, out_path: Path) -> bool:
    import plotly.graph_objects as go
    from config import PLOTLY_THEME

    if rdf.empty or not avail:
        return False

    today = rdf.iloc[-1]
    wk = rdf.iloc[max(0, len(rdf) - 6)]
    mo = rdf.iloc[max(0, len(rdf) - 22)]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=avail, y=[mo[t] for t in avail], name="1m ago",
                             line=dict(color="#888", dash="dot")))
    fig.add_trace(go.Scatter(x=avail, y=[wk[t] for t in avail], name="1w ago",
                             line=dict(color="#4da6ff", dash="dash")))
    fig.add_trace(go.Scatter(x=avail, y=[today[t] for t in avail], name="Today",
                             line=dict(color="#ff4d6d", width=3), mode="lines+markers"))
    fig.update_layout(template=PLOTLY_THEME, title="US Treasury Yield Curve",
                      xaxis_title="Tenor", yaxis_title="Yield (%)",
                      width=900, height=500, legend=dict(x=0.02, y=0.98))

    try:
        fig.write_image(str(out_path), format="png", scale=2)
        return True
    except Exception as e:
        logger.warning("PNG export failed (%s) — writing HTML. `pip install kaleido` to enable PNG.", e)
        fig.write_html(str(out_path.with_suffix(".html")), include_plotlyjs="cdn")
        return False


# ── Brief markdown ─────────────────────────────────────────────────────────
def build_brief_md(sdf, rdf, date_str: str, chart_file: str) -> str:
    def fmt(r):
        return f"| {r['Trade']} | {r['Sharpe']:+.2f} | {r['Z']:+.2f} | {r['E[Ret]']:+.0f} | {r['Risk']:.0f} | {r['D1W']:+.1f} |"

    L = [f"# Morning Rates Scan — {datetime.now().strftime('%d %b %Y')}", ""]

    if len(rdf) >= 6 and "2Y" in rdf.columns and "10Y" in rdf.columns:
        now = (rdf["10Y"].iloc[-1] - rdf["2Y"].iloc[-1]) * 100
        wk = (rdf["10Y"].iloc[-6] - rdf["2Y"].iloc[-6]) * 100
        d = now - wk
        direction = "steepened" if d > 0 else "flattened"
        L += [f"_2s10s {direction} {abs(d):.1f} bps this week to **{now:+.0f} bps**._", ""]

    L += [f"![Yield curve]({chart_file})", ""]
    L += [f"[See the live curve →]({utm('Yield_Curve', 'morning_scan', date_str)})", ""]

    if sdf.empty:
        L += ["_No scanner data available — run the dashboard to refresh the cache._"]
        return "\n".join(L)

    top = sdf.dropna(subset=["Sharpe"]).nlargest(5, "Sharpe")
    L += ["## Top 5 trades by Sharpe", ""]
    L += ["| Trade | Sharpe | Z | E[Ret] (bps) | Risk | D1W |",
          "|---|---:|---:|---:|---:|---:|"]
    L += [fmt(r) for _, r in top.iterrows()]
    L += ["", f"[Full scanner on the dashboard →]({utm('Analysis', 'morning_scan', date_str)})", ""]

    cheap = sdf[sdf["Z"] < -2.0].sort_values("Z").head(5)
    rich = sdf[sdf["Z"] > 2.0].sort_values("Z", ascending=False).head(5)
    if not cheap.empty or not rich.empty:
        L += ["## Z-score extremes (1Y lookback)", ""]
        if not cheap.empty:
            L += ["**Cheap (Z < -2):**", ""]
            L += [f"- {r['Trade']} — Z={r['Z']:+.2f}, Sharpe={r['Sharpe']:+.2f}"
                  for _, r in cheap.iterrows()]
            L += [""]
        if not rich.empty:
            L += ["**Rich (Z > +2):**", ""]
            L += [f"- {r['Trade']} — Z={r['Z']:+.2f}, Sharpe={r['Sharpe']:+.2f}"
                  for _, r in rich.iterrows()]
            L += [""]

    movers_idx = sdf["D1W"].abs().sort_values(ascending=False).index
    movers = sdf.loc[movers_idx]
    movers = movers[movers["D1W"].abs() > 10].head(5)
    if not movers.empty:
        L += ["## Biggest weekly movers", ""]
        L += [f"- {r['Trade']} — D1W={r['D1W']:+.1f} bps, Z={r['Z']:+.2f}"
              for _, r in movers.iterrows()]
        L += [""]

    L += ["---",
          f"_Data via the [Macro Manv rates dashboard]({utm('', 'morning_scan', date_str)}) — updated daily._"]
    return "\n".join(L)


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_dir = ROOT / "briefs" / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Building scanner...")
    sdf, rdf, curve, avail = build_scanner()

    logger.info("Rendering curve chart...")
    chart_path = out_dir / "curve.png"
    png_ok = render_curve_chart(rdf, avail, chart_path)
    chart_file = "curve.png" if png_ok else "curve.html"

    logger.info("Writing brief.md...")
    brief = build_brief_md(sdf, rdf, date_str, chart_file)
    (out_dir / "brief.md").write_text(brief)

    logger.info("Done — %s", out_dir / "brief.md")
    print(f"\nBrief ready: {out_dir}/brief.md")
    print(f"Deep links point to: {DASHBOARD_URL}")
    if not png_ok:
        print("Note: PNG export needs `pip install kaleido`; wrote HTML chart instead.")


if __name__ == "__main__":
    main()
