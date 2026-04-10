"""
06_Analysis.py — Fixed Income Trading Analytics page.

Uses the fixed_income library to provide interactive analysis:
  0. Trade Scanner (main page)
  1. Z-Score Analysis
  2. Carry & Rolldown
  3. Trade Book (Outrights/Spreads/Flies)
  4. Bond Analytics
  5. Spread Options
  6. Wedge Analysis
  7. Swaptions
  8. Portfolio (Beta/Frontier/Sharpe)
  9. Weekly Tables
 10. Custom Trade Builder
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import TREASURY_TENORS, PLOTLY_THEME
from dashboard.state import get_master_df, init_session_state
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header

st.set_page_config(page_title="Analysis", page_icon="🔬", layout="wide")

init_session_state()
render_sidebar_controls()
render_page_header(current="Analysis")

# ── Lazy import: only load fixed_income when this page is visited ──────────
@st.cache_resource
def _load_fi():
    import fixed_income as fi
    return fi

fi = _load_fi()

# ── Helpers ────────────────────────────────────────────────────────────────
ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]

@st.cache_data(ttl=3600, show_spinner=False)
def _get_df():
    return get_master_df()

def _col(df, tenor):
    """Resolve the actual column name for a tenor (handles both '2Y' and 'DGS2')."""
    if tenor in df.columns:
        return tenor
    DGS_MAP = {"2Y":"DGS2","3Y":"DGS3","5Y":"DGS5","7Y":"DGS7","10Y":"DGS10","20Y":"DGS20","30Y":"DGS30"}
    alt = DGS_MAP.get(tenor)
    if alt and alt in df.columns:
        return alt
    return None

def rate_series(df, tenor):
    c = _col(df, tenor)
    return df[c].dropna() if c else pd.Series(dtype=float)

def curve_snapshot(df):
    avail = [t for t in ALL_TENORS if _col(df, t)]
    sub = df[[_col(df, t) for t in avail]].dropna(how="all")
    if sub.empty:
        return {}
    row = sub.iloc[-1]
    return {t: float(row[_col(df, t)]) for t in avail if not pd.isna(row[_col(df, t)])}

def overnight_rate(df):
    for col in ["SOFR", "DFF", "EFFR", "FEDFUNDS"]:
        if col in df.columns:
            s = df[col].dropna()
            if len(s) > 0:
                return float(s.iloc[-1])
    return 5.3

def _safe_style(df_in, fmt="{:.2f}", na_rep="—", **style_kwargs):
    """Coerce to numeric before styling to avoid 'Unknown format code' on str cols."""
    numeric = df_in.apply(pd.to_numeric, errors="coerce")
    styler = numeric.style.format(fmt, na_rep=na_rep)
    if "background_gradient" in style_kwargs:
        styler = styler.background_gradient(**style_kwargs["background_gradient"])
    return styler

def rate_df_multi(df, tenors):
    cols = {t: _col(df, t) for t in tenors if _col(df, t)}
    out = df[list(cols.values())].rename(columns={v: k for k, v in cols.items()})
    return out.ffill(limit=3).dropna(how="all")


# ── Page header ────────────────────────────────────────────────────────────
st.title("🔬 Fixed Income Analysis")
st.caption("Select an analysis section below. Data loads from cache; charts render on demand.")

df = _get_df()
if df.empty:
    st.error("No data available. Hit **Refresh Data** in the sidebar.")
    st.stop()

curve = curve_snapshot(df)
on_rate = overnight_rate(df)

# ── Section selector ──────────────────────────────────────────────────────
section = st.selectbox("Analysis Section", [
    "0. Trade Scanner",
    "1. Z-Score Analysis",
    "2. Carry & Rolldown",
    "3. Trade Book",
    "4. Bond Analytics",
    "5. Spread Options",
    "6. Wedge Analysis",
    "7. Swaptions",
    "8. Portfolio Analytics",
    "9. Weekly Update Tables",
    "10. Custom Trade Builder",
], index=0)

st.divider()

# ═══════════════════════════════════════════════════════════════════════════
# 0. TRADE SCANNER — main analysis page
# ═══════════════════════════════════════════════════════════════════════════
if section.startswith("0"):
    st.subheader("Trade Scanner")
    st.caption(
        "All outright, DV01 curve (1:1), DV01 fly (1:2:1), "
        "beta-weighted curve\\* & fly\\* (zero 10Y exposure) in one table."
    )

    avail = [t for t in ALL_TENORS if _col(df, t)]
    rdf = rate_df_multi(df, avail)
    on_s = pd.Series(on_rate, index=rdf.index)

    # ── tenor → years mapping (must match fi.TENOR_YEARS) ─────────────
    TY = fi.TENOR_YEARS  # e.g. {"2Y": 2.0, "10Y": 10.0, ...}

    # ── controls ──
    ctrl_cols = st.columns([1.2, 1, 1, 1])
    with ctrl_cols[0]:
        scan_dir = st.selectbox("Direction", ["Receive", "Pay"], key="scan_dir")
    with ctrl_cols[1]:
        z_window = st.selectbox("Z-score Window", [63, 126, 252], index=2, key="scan_zwin",
                                format_func=lambda x: {63:"3M",126:"6M",252:"1Y"}[x])
    with ctrl_cols[2]:
        vol_window = st.selectbox("Vol Window", [21, 42, 63, 126], index=2, key="scan_vol",
                                  format_func=lambda x: f"{x}d")
    with ctrl_cols[3]:
        hold_months = st.selectbox("Holding Period", [1, 3], index=0, key="scan_hold",
                                   format_func=lambda x: f"{x}M")

    direction_sign = 1.0 if scan_dir == "Receive" else -1.0
    dir_label = "Rcv" if scan_dir == "Receive" else "Pay"

    # ── helpers ──
    def _pct_changes(series):
        s = series.dropna()
        n = len(s)
        out = {}
        for label, offset in [("1D", 1), ("1W", 5), ("1M", 21), ("3M", 63)]:
            out[f"\u0394{label}"] = round((float(s.iloc[-1]) - float(s.iloc[-1-offset])) * 100, 1) if n > offset else np.nan
        return out

    def _dv01(tenor_label):
        yrs = TY.get(tenor_label, 10.0)
        rate = curve.get(tenor_label, 4.0)
        return fi.approx_dv01(yrs, rate)

    def _dv01_bps(tenor_label):
        """DV01 in bps (per 100 notional) = approx_dv01($) / 100."""
        return round(_dv01(tenor_label) / 100.0, 4)

    def _raw_convexity(tenor_label):
        """Raw bond convexity (second derivative of price w.r.t. yield)."""
        yrs = TY.get(tenor_label, 10.0)
        rate = curve.get(tenor_label, 4.0)
        cfs = fi.bond_cashflows(rate, yrs, notional=100.0, freq=2)
        return fi.convexity(cfs, rate, freq=2)

    def _convexity_pickup_bps(tenor_label, rvol_bps):
        """Annualised expected convexity P&L in bps.
        = 0.5 * Convexity * σ²_annual   (σ in decimal yield)
        Result in bps (× 10000).
        """
        if rvol_bps is None or np.isnan(rvol_bps) or rvol_bps <= 0:
            return 0.0
        conv = _raw_convexity(tenor_label)
        vol_dec = rvol_bps / 10000.0  # bps → decimal yield
        return 0.5 * conv * (vol_dec ** 2) * 10000  # bps

    _beta_ref = "10Y"
    def _compute_betas():
        ref = rdf[_beta_ref].diff().dropna() * 100 if _beta_ref in rdf.columns else None
        out = {}
        if ref is None:
            return out
        for t in avail:
            s = rdf[t].diff().dropna() * 100
            aligned = pd.concat([s, ref], axis=1).dropna()
            if len(aligned) < 60:
                continue
            aligned.columns = ["y", "x"]
            cov = aligned["y"].cov(aligned["x"])
            var = aligned["x"].var()
            out[t] = cov / var if var > 0 else 1.0
        return out
    betas = _compute_betas()

    # ── per-tenor realised vol (for convexity across all trade types) ──
    _tenor_vols = {}
    for t in avail:
        dchg = rdf[t].diff().dropna() * 100  # daily bps
        _tenor_vols[t] = float(dchg.tail(vol_window).std() * np.sqrt(252)) if len(dchg) >= vol_window else np.nan

    def _per_leg_conv_bps(tenor_label):
        """Annualised convexity pickup for a single tenor (bps/yr)."""
        v = _tenor_vols.get(tenor_label)
        if v is None or np.isnan(v) or v <= 0:
            return 0.0
        c = _raw_convexity(tenor_label)
        vol_dec = v / 10000.0
        return 0.5 * c * (vol_dec ** 2) * 10000

    def _net_conv_bps(trade_type, t1, t2=None, t3=None):
        """Net portfolio convexity pickup in bps/yr (before direction sign).

        Curve (receive t2, pay t1 DV01-weighted):
          +per_leg(t2) − (DV01_t2/DV01_t1) × per_leg(t1)

        Fly (receive belly, pay wings DV01-weighted):
          The fly = w_b×belly − w1 − w_w2×w2  (in rate space).
          Long fly ⇒ long belly rate / short wing rates
          ⇒ short belly bond (+ve), long wing bonds (-ve for conv sign).
          Net conv = +per_leg(w1) + w_w2×per_leg(w2) − w_b×per_leg(belly)
        """
        if trade_type == "Outright":
            return _per_leg_conv_bps(t1)
        elif trade_type in ("Curve", "Curve*"):
            d1, d2 = _dv01(t1), _dv01(t2)
            ratio = d2 / d1 if d1 > 0 else 1.0
            return _per_leg_conv_bps(t2) - ratio * _per_leg_conv_bps(t1)
        elif trade_type in ("Fly", "Fly*"):
            d_w1, d_b, d_w2 = _dv01(t1), _dv01(t2), _dv01(t3)
            w_b = 2.0 * (d_w1 / d_b) if d_b > 0 else 2.0
            w_w2 = d_w1 / d_w2 if d_w2 > 0 else 1.0
            return _per_leg_conv_bps(t1) + w_w2 * _per_leg_conv_bps(t3) - w_b * _per_leg_conv_bps(t2)
        return 0.0

    # ── series builders ──
    def _dv01_spread(t1, t2):
        d1, d2 = _dv01(t1), _dv01(t2)
        ratio = d2 / d1 if d1 > 0 else 1.0
        return (rdf[t2] - ratio * rdf[t1]).dropna()

    def _beta_spread(t1, t2):
        b1, b2 = betas.get(t1, 1.0), betas.get(t2, 1.0)
        ratio = b2 / b1 if b1 != 0 else 1.0
        return (rdf[t2] - ratio * rdf[t1]).dropna()

    def _dv01_fly(w1, belly, w2):
        d_w1, d_b, d_w2 = _dv01(w1), _dv01(belly), _dv01(w2)
        w_b = 2.0 * (d_w1 / d_b) if d_b > 0 else 2.0
        w_w2 = d_w1 / d_w2 if d_w2 > 0 else 1.0
        return (w_b * rdf[belly] - rdf[w1] - w_w2 * rdf[w2]).dropna()

    def _beta_fly(w1, belly, w2):
        b_w1, b_b, b_w2 = betas.get(w1, 1.0), betas.get(belly, 1.0), betas.get(w2, 1.0)
        if b_w1 == 0: b_w1 = 0.01
        c = (2.0 * b_b - b_w1) / b_w2 if b_w2 != 0 else 1.0
        return (2.0 * rdf[belly] - rdf[w1] - c * rdf[w2]).dropna()

    # ── row builder (unified: level always in bps for curves/flies, % for outrights) ──
    def _row(trade_label, trade_type, series_raw, cr_dict,
             tenor_label=None, tenors=None):
        """tenors = (t1,) | (t1,t2) | (w1,belly,w2) for conv/DV01 calc."""
        s = series_raw.dropna()
        if len(s) < z_window:
            return None
        curr = float(s.iloc[-1])
        curr_display = curr if trade_type == "Outright" else curr * 100  # bps
        carry_bps = cr_dict["carry"] * direction_sign
        roll_bps = cr_dict["rolldown"] * direction_sign
        total_cr = cr_dict["total"] * direction_sign
        ann_cr = total_cr * (12.0 / hold_months)
        daily_chg = s.diff().dropna() * 100
        rvol = float(daily_chg.tail(vol_window).std() * np.sqrt(252)) if len(daily_chg) >= vol_window else np.nan

        # Net convexity pickup (bps/yr) — all trade types
        conv_ann_bps = 0.0
        dv01_bps_val = np.nan
        if tenors:
            t1 = tenors[0]
            t2 = tenors[1] if len(tenors) > 1 else None
            t3 = tenors[2] if len(tenors) > 2 else None
            conv_ann_bps = _net_conv_bps(trade_type, t1, t2, t3) * direction_sign
            if trade_type == "Outright":
                dv01_bps_val = _dv01_bps(t1)

        ann_ret = ann_cr + conv_ann_bps
        z = fi.zscore_current(s, z_window)
        sharpe = ann_ret / rvol if (rvol and rvol > 0) else np.nan
        chg = _pct_changes(s)
        row = {
            "Trade": trade_label, "Type": trade_type,
            "Level": round(curr_display, 3 if trade_type == "Outright" else 1),
            "DV01": round(dv01_bps_val, 2) if not np.isnan(dv01_bps_val) else np.nan,
            "Carry": round(carry_bps, 1),
            "Roll": round(roll_bps, 1),
            "Conv": round(conv_ann_bps, 1),
            "E[Ret]": round(ann_ret, 1),
            "Risk": round(rvol, 1) if not np.isnan(rvol) else np.nan,
            "Sharpe": round(sharpe, 2) if not np.isnan(sharpe) else np.nan,
            "Z": round(z, 2),
            **chg,
        }
        return row

    # ═══════════════════════════════════════════════════════════════════════
    # BUILD COMBINED TABLE: outrights + DV01 curves + beta curves* + DV01 flies + beta flies*
    # ═══════════════════════════════════════════════════════════════════════
    all_rows = []
    _zero_cr = {"carry": 0, "rolldown": 0, "total": 0}

    # 1) Outrights
    for t in avail:
        cr = fi.forward_carry_rolldown(curve, on_rate, "outright", t,
            holding_months=hold_months) if t in curve else _zero_cr
        r = _row(f"{dir_label} {t}", "Outright", rdf[t], cr, tenors=(t,))
        if r: all_rows.append(r)

    # 2) DV01 curves (1:1)
    all_pairs = [(avail[i], avail[j]) for i in range(len(avail)) for j in range(i+1, len(avail))]
    for t1, t2 in all_pairs:
        spread = _dv01_spread(t1, t2)
        cr = fi.forward_carry_rolldown(curve, on_rate, "spread", t2, t1,
            holding_months=hold_months) if (t1 in curve and t2 in curve) else _zero_cr
        r = _row(f"{dir_label} {t1}/{t2}", "Curve", spread, cr, tenors=(t1, t2))
        if r: all_rows.append(r)

    # 3) Beta curves* (zero 10Y exposure)
    if _beta_ref in rdf.columns:
        for t1, t2 in all_pairs:
            spread = _beta_spread(t1, t2)
            cr = fi.forward_carry_rolldown(curve, on_rate, "spread", t2, t1,
                holding_months=hold_months) if (t1 in curve and t2 in curve) else _zero_cr
            r = _row(f"{dir_label} {t1}/{t2}*", "Curve*", spread, cr, tenors=(t1, t2))
            if r: all_rows.append(r)

    # 4) DV01 flies (1:2:1)
    all_flies = [(avail[i], avail[j], avail[k])
                 for i in range(len(avail)) for j in range(i+1, len(avail)) for k in range(j+1, len(avail))]
    for w1, belly, w2 in all_flies:
        fly = _dv01_fly(w1, belly, w2)
        cr = fi.forward_carry_rolldown(curve, on_rate, "fly", w1, belly, w2,
            holding_months=hold_months) if all(x in curve for x in [w1, belly, w2]) else _zero_cr
        r = _row(f"{dir_label} {w1}/{belly}/{w2}", "Fly", fly, cr, tenors=(w1, belly, w2))
        if r: all_rows.append(r)

    # 5) Beta flies* (zero 10Y exposure)
    if _beta_ref in rdf.columns:
        for w1, belly, w2 in all_flies:
            fly = _beta_fly(w1, belly, w2)
            cr = fi.forward_carry_rolldown(curve, on_rate, "fly", w1, belly, w2,
                holding_months=hold_months) if all(x in curve for x in [w1, belly, w2]) else _zero_cr
            r = _row(f"{dir_label} {w1}/{belly}/{w2}*", "Fly*", fly, cr, tenors=(w1, belly, w2))
            if r: all_rows.append(r)

    # ── display ──
    st.divider()
    if all_rows:
        result = pd.DataFrame(all_rows)
        # Coerce numeric columns to float so NaN renders as "—" not "None"
        for c in result.columns:
            if c not in ("Trade", "Type"):
                result[c] = pd.to_numeric(result[c], errors="coerce")
        # Drop DV01/Conv columns if ALL values are NaN (no outrights selected)
        # Otherwise Streamlit shows "None" for NaN in mixed columns
        # Filter by type
        type_filter = st.multiselect("Show trade types", ["Outright","Curve","Curve*","Fly","Fly*"],
                                     default=["Outright","Curve","Fly"], key="type_filt")
        result = result[result["Type"].isin(type_filter)].reset_index(drop=True)

        if not result.empty:
            result = result.sort_values("Sharpe", ascending=False, na_position="last").reset_index(drop=True)
            sc1, sc2 = st.columns([3, 1])
            with sc1:
                sort_col = st.selectbox("Sort by", [c for c in result.columns if c != "Type"],
                                        index=[c for c in result.columns if c != "Type"].index("Sharpe"), key="sort_all")
            with sc2:
                asc = st.checkbox("Ascending", value=False, key="asc_all")
            result = result.sort_values(sort_col, ascending=asc, na_position="last").reset_index(drop=True)

            fmt = {c: "{:.1f}" for c in result.columns if c not in ("Trade","Type")}
            fmt["Level"] = "{:.3f}"
            fmt["Sharpe"] = "{:.2f}"
            fmt["Z"] = "{:.2f}"
            fmt["DV01"] = "{:.2f}"
            fmt["Conv"] = "{:.1f}"

            # Apply colour gradient on every numeric column
            numeric_cols = [c for c in result.columns if c not in ("Trade","Type")]
            styler = result.style.format(fmt, na_rep="\u2014", subset=numeric_cols)

            # Sharpe: green=high, red=low
            if "Sharpe" in result.columns:
                styler = styler.background_gradient(subset=["Sharpe"], cmap="RdYlGn", vmin=-1.5, vmax=1.5)
            # Z-score: reverse — low z = cheap = green
            if "Z" in result.columns:
                styler = styler.background_gradient(subset=["Z"], cmap="RdYlGn_r", vmin=-2, vmax=2)
            # E[Ret]: green=high positive, red=negative
            if "E[Ret]" in result.columns:
                styler = styler.background_gradient(subset=["E[Ret]"], cmap="RdYlGn", vmin=-50, vmax=150)
            # Carry: green=positive, red=negative
            if "Carry" in result.columns:
                styler = styler.background_gradient(subset=["Carry"], cmap="RdYlGn", vmin=-10, vmax=15)
            # Roll: green=positive, red=negative
            if "Roll" in result.columns:
                styler = styler.background_gradient(subset=["Roll"], cmap="RdYlGn", vmin=-5, vmax=5)
            # Conv: green=high (more convexity benefit)
            if "Conv" in result.columns:
                styler = styler.background_gradient(subset=["Conv"], cmap="RdYlGn", vmin=0, vmax=10)
            # DV01: neutral gradient
            if "DV01" in result.columns:
                styler = styler.background_gradient(subset=["DV01"], cmap="Blues", vmin=0, vmax=20)
            # Risk: lower = green, higher = red (inverted)
            if "Risk" in result.columns:
                styler = styler.background_gradient(subset=["Risk"], cmap="RdYlGn_r", vmin=20, vmax=120)
            # Delta columns: green=positive moves (for receiver), red=negative
            for dc in ["\u03941D", "\u03941W", "\u03941M", "\u03943M"]:
                if dc in result.columns:
                    styler = styler.background_gradient(subset=[dc], cmap="RdYlGn_r", vmin=-30, vmax=30)

            st.dataframe(styler, use_container_width=True, height=min(800, 40 + 35 * len(result)))

            # ── Export buttons ──
            export_cols = st.columns([1, 1, 5])
            with export_cols[0]:
                csv_data = result.to_csv(index=False).encode("utf-8")
                st.download_button("Download CSV", csv_data, "scanner_export.csv",
                                   "text/csv", use_container_width=True)
            with export_cols[1]:
                # HTML report with inline styles for print-to-PDF
                html_table = result.to_html(index=False, na_rep="—", border=0,
                                            float_format=lambda x: f"{x:.2f}")
                html_report = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Rates Scanner — {pd.Timestamp.now().strftime('%d %b %Y')}</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; margin: 40px; color: #222; }}
  h1 {{ font-size: 22px; }} h2 {{ font-size: 16px; color: #666; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
  th {{ background: #1a1a2e; color: white; padding: 6px 10px; text-align: left; }}
  td {{ padding: 5px 10px; border-bottom: 1px solid #e0e0e0; }}
  tr:nth-child(even) {{ background: #f8f9fa; }}
  .footer {{ margin-top: 30px; font-size: 11px; color: #999; }}
</style></head><body>
<h1>Rates Dashboard — Trade Scanner</h1>
<h2>{pd.Timestamp.now().strftime('%d %B %Y')} | Direction: {scan_dir} | Hold: {hold_months}M | Z-window: {z_window}d</h2>
{html_table}
<p class="footer">Generated by Macro Manv Rates Dashboard &mdash; manveersahota.substack.com</p>
</body></html>"""
                st.download_button("Download Report", html_report.encode("utf-8"),
                                   "scanner_report.html", "text/html", use_container_width=True)

            # Beta reference table
            with st.expander("Beta to 10Y, DV01 & Convexity reference"):
                # Use avg vol from the last row of rdf for convexity pickup estimate
                _ref_vol = {}
                for t in avail:
                    dchg = rdf[t].diff().dropna() * 100
                    _ref_vol[t] = float(dchg.tail(vol_window).std() * np.sqrt(252)) if len(dchg) >= vol_window else 60.0
                beta_df = pd.DataFrame([
                    {"Tenor": t,
                     "\u03B2 vs 10Y": round(betas.get(t, np.nan), 4),
                     "DV01 (bps)": round(_dv01_bps(t), 4),
                     "Raw Conv": round(_raw_convexity(t), 1),
                     "Conv P&L (bps/yr)": round(_convexity_pickup_bps(t, _ref_vol[t]), 1)}
                    for t in avail
                ])
                st.dataframe(beta_df, use_container_width=True, hide_index=True)

            # ───────────────────────────────────────────────────────────
            # LLM TRADE COMMENTARY (optional — requires ANTHROPIC_API_KEY)
            # ───────────────────────────────────────────────────────────
            import os as _os_llm
            if _os_llm.getenv("ANTHROPIC_API_KEY"):
                with st.expander("AI Trade Commentary"):
                    if st.button("Generate Commentary", key="llm_btn"):
                        with st.spinner("Analysing trades with Claude..."):
                            try:
                                import anthropic
                                client = anthropic.Anthropic()
                                top5 = result.head(5)[["Trade","Type","Sharpe","Z","E[Ret]","Risk","Carry","Roll","Conv"]].to_string(index=False)
                                z_extremes = result.nsmallest(3, "Z")[["Trade","Z","Sharpe"]].to_string(index=False)
                                prompt = (
                                    f"You are a rates trading analyst at a macro hedge fund. "
                                    f"Today's scanner shows these top trades by Sharpe:\n\n{top5}\n\n"
                                    f"Z-score extremes (cheapest):\n{z_extremes}\n\n"
                                    f"Direction: {scan_dir}. Curve snapshot: {curve}\n"
                                    f"SOFR overnight: {on_rate}%\n\n"
                                    f"Write a concise 3-4 paragraph market commentary covering:\n"
                                    f"1. Top trade ideas and why they look attractive\n"
                                    f"2. Key curve/fly themes from the scanner\n"
                                    f"3. Risks to watch\n"
                                    f"Keep it professional, specific, and under 250 words."
                                )
                                msg = client.messages.create(
                                    model="claude-sonnet-4-20250514",
                                    max_tokens=500,
                                    messages=[{"role": "user", "content": prompt}],
                                )
                                st.markdown(msg.content[0].text)
                            except ImportError:
                                st.warning("Install `anthropic` package: `pip install anthropic`")
                            except Exception as e:
                                st.error(f"LLM error: {e}")

            # ───────────────────────────────────────────────────────────
            # BUBBLE CHARTS — Sharpe vs Z-score  &  E[Ret] vs Risk
            # ───────────────────────────────────────────────────────────
            st.divider()
            st.subheader("Trade Landscape")

            # Type toggle for bubble charts (independent of table filter)
            bubble_types = st.multiselect(
                "Show trade types on charts",
                ["Outright", "Curve", "Curve*", "Fly", "Fly*"],
                default=[t for t in type_filter],  # inherit table filter
                key="bubble_type_filt",
            )
            bdf = result[result["Type"].isin(bubble_types)].copy()

            if not bdf.empty and "\u03941W" in bdf.columns:
                # Bubble size = abs(1W change), with a floor so tiny dots are visible
                bdf["_size"] = bdf["\u03941W"].abs().clip(lower=0.5)

                TYPE_COLORS = {
                    "Outright": "#4fc3f7",
                    "Curve": "#ff8a65",
                    "Curve*": "#ffb74d",
                    "Fly": "#81c784",
                    "Fly*": "#aed581",
                }

                # ── Chart 1: Expected Sharpe vs Z-score ──
                fig1 = go.Figure()
                for ttype in bubble_types:
                    sub = bdf[bdf["Type"] == ttype]
                    if sub.empty:
                        continue
                    fig1.add_trace(go.Scatter(
                        x=sub["Z"], y=sub["Sharpe"],
                        mode="markers",
                        marker=dict(
                            size=sub["_size"],
                            sizemode="area",
                            sizeref=2.0 * bdf["_size"].max() / (40.0 ** 2),
                            sizemin=4,
                            color=TYPE_COLORS.get(ttype, "#888"),
                            opacity=0.75,
                            line=dict(width=0.5, color="white"),
                        ),
                        text=sub["Trade"],
                        hovertemplate=(
                            "<b>%{text}</b><br>"
                            "Z-score: %{x:.2f}<br>"
                            "Sharpe: %{y:.2f}<br>"
                            "\u03941W: %{customdata:.1f} bps"
                            "<extra></extra>"
                        ),
                        customdata=sub["\u03941W"],
                        name=ttype,
                    ))
                fig1.add_hline(y=0, line_dash="dot", line_color="grey", opacity=0.4)
                fig1.add_vline(x=0, line_dash="dot", line_color="grey", opacity=0.4)
                fig1.update_layout(
                    template=PLOTLY_THEME,
                    title="Expected Sharpe vs Z-score",
                    xaxis_title="Z-score (low = cheap)",
                    yaxis_title="Expected Sharpe",
                    height=500,
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    margin=dict(l=50, r=20, t=60, b=50),
                )
                st.plotly_chart(fig1, use_container_width=True)

                # ── Chart 2: Expected Return vs Risk ──
                fig2 = go.Figure()
                for ttype in bubble_types:
                    sub = bdf[bdf["Type"] == ttype]
                    if sub.empty:
                        continue
                    fig2.add_trace(go.Scatter(
                        x=sub["Risk"], y=sub["E[Ret]"],
                        mode="markers",
                        marker=dict(
                            size=sub["_size"],
                            sizemode="area",
                            sizeref=2.0 * bdf["_size"].max() / (40.0 ** 2),
                            sizemin=4,
                            color=TYPE_COLORS.get(ttype, "#888"),
                            opacity=0.75,
                            line=dict(width=0.5, color="white"),
                        ),
                        text=sub["Trade"],
                        hovertemplate=(
                            "<b>%{text}</b><br>"
                            "Risk: %{x:.1f} bps/yr<br>"
                            "E[Ret]: %{y:.1f} bps/yr<br>"
                            "\u03941W: %{customdata:.1f} bps"
                            "<extra></extra>"
                        ),
                        customdata=sub["\u03941W"],
                        name=ttype,
                    ))
                fig2.add_hline(y=0, line_dash="dot", line_color="grey", opacity=0.4)
                fig2.update_layout(
                    template=PLOTLY_THEME,
                    title="Expected Return vs Risk",
                    xaxis_title="Risk (60d realised vol, bps/yr)",
                    yaxis_title="E[Return] (bps/yr)",
                    height=500,
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    margin=dict(l=50, r=20, t=60, b=50),
                )
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Not enough data for bubble charts.")

        else:
            st.info("No trades match the selected filters.")
    else:
        st.warning("Not enough data to build trade table.")

    # ═══════════════════════════════════════════════════════════════════════
    # TRADE DETAIL — level, z-score, rolling E[Ret], rolling Sharpe
    # ═══════════════════════════════════════════════════════════════════════
    st.divider()
    st.subheader("Trade Detail")
    st.caption("Time series, z-score, rolling expected return, and rolling Sharpe evolution.")

    det_type = st.radio("Detail Type", ["Outright","Curve","Curve*","Fly","Fly*"], horizontal=True, key="det_type")
    det_cols = st.columns([1.2, 1.2, 1.2])

    if det_type == "Outright":
        with det_cols[0]:
            det_tenor = st.selectbox("Tenor", avail, index=avail.index("10Y") if "10Y" in avail else 0, key="det_t")
        det_series = rdf[det_tenor].dropna()
        det_label = f"{dir_label} {det_tenor}"
        det_is_pct = True
    elif det_type in ("Curve", "Curve*"):
        with det_cols[0]:
            det_t1 = st.selectbox("Short Leg", avail, index=0, key="det_cl1")
        with det_cols[1]:
            det_t2 = st.selectbox("Long Leg", avail,
                                  index=min(len(avail)-1, avail.index("10Y") if "10Y" in avail else 3), key="det_cl2")
        det_series = (_beta_spread(det_t1, det_t2) if det_type == "Curve*" else _dv01_spread(det_t1, det_t2)).dropna()
        det_label = f"{dir_label} {det_t1}/{det_t2}" + ("*" if det_type == "Curve*" else "")
        det_is_pct = False
    else:
        with det_cols[0]:
            det_w1 = st.selectbox("Wing 1", avail, index=0, key="det_fw1")
        with det_cols[1]:
            det_belly = st.selectbox("Belly", avail, index=min(len(avail)-1, 2), key="det_fb")
        with det_cols[2]:
            det_w2 = st.selectbox("Wing 2", avail, index=min(len(avail)-1, 4), key="det_fw2")
        det_series = (_beta_fly(det_w1, det_belly, det_w2) if det_type == "Fly*"
                      else _dv01_fly(det_w1, det_belly, det_w2)).dropna()
        det_label = f"{dir_label} {det_w1}/{det_belly}/{det_w2}" + ("*" if det_type == "Fly*" else "")
        det_is_pct = False

    det_series = det_series.dropna()
    if det_is_pct:
        det_display = det_series          # % for outrights
        det_unit = "Rate (%)"
    else:
        det_display = det_series * 100    # bps for curves/flies
        det_unit = "bps"

    if len(det_series) > z_window:
        det_z = fi.zscore(det_series, z_window)

        # Rolling expected return: carry+rolldown annualised (static, repeated as line)
        # Use rolling realised vol to get rolling Sharpe
        daily_chg = det_series.diff().dropna() * 100  # bps
        roll_vol = daily_chg.rolling(vol_window, min_periods=int(vol_window*0.7)).std() * np.sqrt(252)

        # Carry+roll via forward swap rates
        if det_is_pct and det_tenor in curve:
            cr_snap = fi.forward_carry_rolldown(curve, on_rate, "outright", det_tenor,
                holding_months=hold_months)
            det_tenors = (det_tenor,)
        elif not det_is_pct and det_type in ("Curve", "Curve*"):
            cr_snap = fi.forward_carry_rolldown(curve, on_rate, "spread", det_t2, det_t1,
                holding_months=hold_months) if (det_t1 in curve and det_t2 in curve) else _zero_cr
            det_tenors = (det_t1, det_t2)
        elif not det_is_pct and det_type in ("Fly", "Fly*"):
            legs = (det_w1, det_belly, det_w2)
            cr_snap = fi.forward_carry_rolldown(curve, on_rate, "fly", *legs,
                holding_months=hold_months) if all(x in curve for x in legs) else _zero_cr
            det_tenors = legs
        else:
            cr_snap = _zero_cr
            det_tenors = ()

        ann_cr_static = cr_snap["total"] * direction_sign * (12.0 / hold_months)
        # Net convexity pickup (all trade types)
        conv_ann_detail = 0.0
        if det_tenors:
            t1d = det_tenors[0]
            t2d = det_tenors[1] if len(det_tenors) > 1 else None
            t3d = det_tenors[2] if len(det_tenors) > 2 else None
            conv_ann_detail = _net_conv_bps(det_type, t1d, t2d, t3d) * direction_sign
        ann_ret_static = ann_cr_static + conv_ann_detail
        roll_sharpe = ann_ret_static / roll_vol
        roll_sharpe = roll_sharpe.replace([np.inf, -np.inf], np.nan)

        # 4-panel chart: Level | Z-score | E[Return] | Sharpe
        fig = make_subplots(rows=4, cols=1, shared_xaxes=True,
                            subplot_titles=[f"{det_label} \u2014 {det_unit}", f"Z-score ({z_window}d)",
                                            f"E[Return] (bps/yr)", f"Rolling Sharpe ({vol_window}d vol)"],
                            row_heights=[0.3, 0.25, 0.2, 0.25], vertical_spacing=0.05)
        # Row 1: Level
        fig.add_trace(go.Scatter(x=det_display.index, y=det_display.values,
                                 line=dict(color="#4fc3f7", width=1.3), showlegend=False), row=1, col=1)
        # Row 2: Z-score
        fig.add_trace(go.Scatter(x=det_z.index, y=det_z.values,
                                 line=dict(color="#ff8a65", width=1.3), showlegend=False), row=2, col=1)
        for lvl, clr in [(2,"red"),(1.5,"orangered"),(0,"grey"),(-1.5,"limegreen"),(-2,"green")]:
            fig.add_hline(y=lvl, line_dash="dot", line_color=clr, opacity=0.4, row=2, col=1)
        # Row 3: Expected return (horizontal line = current ann E[Ret])
        eret_series = pd.Series(ann_ret_static, index=det_display.index)
        fig.add_trace(go.Scatter(x=eret_series.index, y=eret_series.values,
                                 line=dict(color="#66bb6a", width=1.5), showlegend=False), row=3, col=1)
        fig.add_hline(y=0, line_dash="dot", line_color="grey", opacity=0.5, row=3, col=1)
        # Row 4: Rolling Sharpe
        fig.add_trace(go.Scatter(x=roll_sharpe.index, y=roll_sharpe.values,
                                 line=dict(color="#ab47bc", width=1.3), showlegend=False), row=4, col=1)
        fig.add_hline(y=0, line_dash="dot", line_color="grey", opacity=0.5, row=4, col=1)
        for lvl, clr in [(1,"limegreen"),(-1,"red")]:
            fig.add_hline(y=lvl, line_dash="dot", line_color=clr, opacity=0.4, row=4, col=1)

        fig.update_layout(template=PLOTLY_THEME, height=700, showlegend=False,
                          margin=dict(l=50, r=20, t=30, b=30))
        st.plotly_chart(fig, use_container_width=True)

        # Summary metrics — colour-coded via styled DataFrame row
        curr_val = float(det_display.iloc[-1])
        curr_z = float(det_z.iloc[-1]) if not det_z.empty else np.nan
        curr_rvol = float(roll_vol.iloc[-1]) if not roll_vol.empty and not np.isnan(roll_vol.iloc[-1]) else np.nan
        curr_sharpe = ann_ret_static / curr_rvol if (curr_rvol and curr_rvol > 0) else np.nan
        chg_1d = float(det_display.iloc[-1] - det_display.iloc[-2]) if len(det_display) > 1 else 0
        chg_1w = float(det_display.iloc[-1] - det_display.iloc[-6]) if len(det_display) > 5 else 0
        chg_1m = float(det_display.iloc[-1] - det_display.iloc[-22]) if len(det_display) > 21 else 0

        # Build a single-row DataFrame and colour every cell
        metric_row = pd.DataFrame([{
            "Level": curr_val,
            "Z-score": round(curr_z, 2),
            "E[Ret] bps/yr": round(ann_ret_static, 1),
            "Sharpe": round(curr_sharpe, 2) if not np.isnan(curr_sharpe) else np.nan,
            "\u0394 1D": round(chg_1d, 1),
            "\u0394 1W": round(chg_1w, 1),
            "\u0394 1M": round(chg_1m, 1),
        }])

        def _cell_color(val, good_high=True, lo=-2.0, hi=2.0):
            if pd.isna(val):
                return ""
            frac = max(0.0, min(1.0, (float(val) - lo) / (hi - lo))) if hi != lo else 0.5
            if not good_high:
                frac = 1.0 - frac
            r = int(200 * (1 - frac) + 30 * frac)
            g = int(50 * (1 - frac) + 180 * frac)
            b = int(50 * (1 - frac) + 70 * frac)
            return f"background-color: #{r:02x}{g:02x}{b:02x}; color: white; font-weight: 700"

        is_rcv = direction_sign > 0
        def _style_metric_row(row):
            return [
                "",  # Level: no colour
                _cell_color(row["Z-score"], good_high=False, lo=-2, hi=2),
                _cell_color(row["E[Ret] bps/yr"], good_high=True, lo=-30, hi=150),
                _cell_color(row["Sharpe"], good_high=True, lo=-1, hi=2),
                _cell_color(row["\u0394 1D"], good_high=not is_rcv, lo=-10, hi=10),
                _cell_color(row["\u0394 1W"], good_high=not is_rcv, lo=-20, hi=20),
                _cell_color(row["\u0394 1M"], good_high=not is_rcv, lo=-30, hi=30),
            ]

        m_styler = metric_row.style.apply(_style_metric_row, axis=1).format({
            "Level": "{:.2f}", "Z-score": "{:.2f}",
            "E[Ret] bps/yr": "{:.1f}", "Sharpe": "{:.2f}",
            "\u0394 1D": "{:+.1f}", "\u0394 1W": "{:+.1f}", "\u0394 1M": "{:+.1f}",
        }, na_rep="\u2014").hide(axis="index")
        st.dataframe(m_styler, use_container_width=True, hide_index=True)
    else:
        st.info("Not enough data for the selected trade.")


# ═══════════════════════════════════════════════════════════════════════════
# 1. Z-SCORE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════
elif section.startswith("1"):
    avail_tenors = [t for t in ALL_TENORS if _col(df, t)]
    rdf = rate_df_multi(df, avail_tenors)

    st.subheader("Z-Score Summary")
    z_table = fi.zscore_table(rdf, window=252)
    st.dataframe(_safe_style(z_table), use_container_width=True)

    st.divider()
    st.subheader("Rolling Z-Score")
    c1, c2 = st.columns([1, 1])
    with c1:
        tenor_pick = st.selectbox("Tenor", avail_tenors, index=avail_tenors.index("10Y") if "10Y" in avail_tenors else 0)
    with c2:
        z_window = st.select_slider("Window (days)", [63, 126, 189, 252, 504], value=252)

    s = rate_series(df, tenor_pick)
    z = fi.zscore(s, z_window)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        subplot_titles=[f"{tenor_pick} Rate (%)", f"Z-score ({z_window}d)"],
                        row_heights=[0.5, 0.5])
    fig.add_trace(go.Scatter(x=s.index, y=s.values, name="Rate", line=dict(color="#4fc3f7")), row=1, col=1)
    fig.add_trace(go.Scatter(x=z.index, y=z.values, name="Z-score", line=dict(color="#ff8a65")), row=2, col=1)
    fig.add_hline(y=1.5, line_dash="dash", line_color="green", row=2, col=1)
    fig.add_hline(y=-1.5, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=0, line_dash="dot", line_color="grey", row=2, col=1)
    fig.update_layout(template=PLOTLY_THEME, height=500, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Spread Z-Scores")
    spread_rows = []
    for t1, t2 in [("2Y","10Y"),("2Y","30Y"),("5Y","10Y"),("5Y","30Y"),("10Y","30Y")]:
        s1, s2 = rate_series(df, t1), rate_series(df, t2)
        spread = (s2 - s1).dropna() * 100
        if len(spread) < 50:
            continue
        spread_rows.append({
            "Spread": f"{t1}/{t2}",
            "Current (bps)": round(float(spread.iloc[-1]), 1),
            "Z-score (1Y)": round(fi.zscore_current(spread, 252), 2),
            "Pctile (1Y)": round(float(fi.percentile_rank(spread, 252).iloc[-1]), 1),
        })
    if spread_rows:
        st.dataframe(pd.DataFrame(spread_rows).set_index("Spread"), use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# 2. CARRY & ROLLDOWN
# ═══════════════════════════════════════════════════════════════════════════
elif section.startswith("2"):
    st.subheader("Outright Carry & Rolldown")
    hold = st.select_slider("Holding period (months)", [1, 3, 6], value=1)

    rows = []
    for tenor in ["2Y","3Y","5Y","7Y","10Y","20Y","30Y"]:
        if tenor not in curve:
            continue
        cr = fi.snapshot_carry_rolldown(curve, on_rate, "outright", tenor, holding_months=hold)
        rows.append({
            "Tenor": tenor, "Rate (%)": round(curve[tenor], 3),
            "Carry (bps)": cr["carry"], "Rolldown (bps)": cr["rolldown"],
            "Total (bps)": cr["total"], "Annualised (bps)": round(cr["total"] * 12 / hold, 1),
        })
    cr_df = pd.DataFrame(rows).set_index("Tenor")

    def _cr_color(v):
        if pd.isna(v) or not isinstance(v, (int, float)):
            return ""
        if v > 5: return "background-color: #2d6a2d; color: white"
        if v > 0: return "background-color: #3a6b3a; color: white"
        if v > -5: return "background-color: #8b3030; color: white"
        return "background-color: #8b0000; color: white"

    st.dataframe(cr_df.style.applymap(_cr_color, subset=["Total (bps)","Annualised (bps)"]).format("{:.2f}", na_rep="—"),
                 use_container_width=True)

    # Bar chart
    fig = go.Figure()
    fig.add_trace(go.Bar(x=cr_df.index, y=cr_df["Carry (bps)"], name="Carry", marker_color="#42a5f5"))
    fig.add_trace(go.Bar(x=cr_df.index, y=cr_df["Rolldown (bps)"], name="Rolldown", marker_color="#66bb6a"))
    fig.update_layout(template=PLOTLY_THEME, barmode="stack",
                      title=f"Carry + Rolldown ({hold}M holding)", yaxis_title="bps")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Spread Carry & Rolldown")
    rows2 = []
    for t1, t2 in [("2Y","10Y"),("2Y","30Y"),("5Y","10Y"),("5Y","30Y"),("10Y","30Y")]:
        if t1 not in curve or t2 not in curve:
            continue
        cr = fi.snapshot_carry_rolldown(curve, on_rate, "spread", t2, t1, holding_months=hold)
        rows2.append({
            "Spread": f"{t1}/{t2}", "Level (bps)": round((curve[t2]-curve[t1])*100, 1),
            "Carry": cr["carry"], "Rolldown": cr["rolldown"],
            "Total": cr["total"], "Annualised": round(cr["total"]*12/hold, 1),
        })
    if rows2:
        st.dataframe(pd.DataFrame(rows2).set_index("Spread"), use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# 3. TRADE BOOK
# ═══════════════════════════════════════════════════════════════════════════
elif section.startswith("3"):
    st.subheader("Trade Book")
    avail = [t for t in ["2Y","3Y","5Y","7Y","10Y","20Y","30Y"] if _col(df, t)]
    rdf = rate_df_multi(df, avail)
    on_s = pd.Series(on_rate, index=rdf.index)

    book = fi.build_trade_book(
        rate_df=rdf, overnight_series=on_s,
        outright_tenors=avail,
        spread_pairs=[("2Y","10Y"),("5Y","30Y"),("2Y","30Y"),("10Y","30Y")],
        fly_triplets=[("2Y","5Y","10Y"),("5Y","10Y","30Y")],
        curve_snapshot=curve, zscore_window=252, holding_months=1,
    )

    for name, tdf in book.items():
        st.markdown(f"**{name.upper()}**")
        st.dataframe(_safe_style(tdf), use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# 4. BOND ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════
elif section.startswith("4"):
    st.subheader("Bond Calculator")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        coupon = st.number_input("Coupon (%)", 0.0, 15.0, 4.5, 0.125)
    with c2:
        mat_yr = st.number_input("Maturity (yrs)", 0.5, 50.0, 10.0, 0.5)
    with c3:
        ytm = st.number_input("YTM (%)", 0.0, 20.0, curve.get("10Y", 4.5), 0.01)
    with c4:
        notional = st.number_input("Notional ($M)", 1, 500, 10) * 1_000_000

    analytics = fi.quick_analytics(coupon, mat_yr, ytm, notional)
    cols = st.columns(len(analytics))
    for col, (k, v) in zip(cols, analytics.items()):
        col.metric(k, f"{v:,.2f}" if isinstance(v, float) else v)

    st.divider()
    st.subheader("DV01 Across the Curve")
    dv01_rows = []
    for tenor, rate in curve.items():
        tyr = fi.TENOR_YEARS.get(tenor)
        if tyr is None:
            continue
        cfs = fi.bond_cashflows(rate, tyr)
        dv01_rows.append({
            "Tenor": tenor, "Rate (%)": round(rate, 3),
            "DV01 ($10M)": round(fi.dv01_bond(cfs, rate, 10_000_000), 0),
            "Mod Duration": round(fi.modified_duration(cfs, rate), 2),
            "Convexity": round(fi.convexity(cfs, rate), 2),
        })
    st.dataframe(pd.DataFrame(dv01_rows).set_index("Tenor"), use_container_width=True)

    # Price sensitivity chart
    yield_shocks = np.linspace(-100, 100, 41)  # bps
    cfs = fi.bond_cashflows(coupon, mat_yr)
    prices = [fi.bond_price(cfs, ytm + s/100) for s in yield_shocks]
    fig = go.Figure(go.Scatter(x=yield_shocks, y=prices, line=dict(color="#ab47bc")))
    fig.add_vline(x=0, line_dash="dash", line_color="grey")
    fig.update_layout(template=PLOTLY_THEME, title="Price Sensitivity to Yield Shock",
                      xaxis_title="Yield Shock (bps)", yaxis_title="Price (%)")
    st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# 5. SPREAD OPTIONS
# ═══════════════════════════════════════════════════════════════════════════
elif section.startswith("5"):
    st.subheader("Spread Option Pricing")
    avail = [t for t in ALL_TENORS if _col(df, t)]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        so_t1 = st.selectbox("Short Leg", avail, index=avail.index("2Y") if "2Y" in avail else 0)
    with c2:
        so_t2 = st.selectbox("Long Leg", avail, index=avail.index("10Y") if "10Y" in avail else min(2, len(avail)-1))
    with c3:
        so_expiry = st.selectbox("Expiry (months)", [1,3,6,9,12], index=1)
    with c4:
        so_vol_win = st.selectbox("Vol Window (days)", [21,42,63,126], index=2)

    spread_s = (rate_series(df, so_t2) - rate_series(df, so_t1)).dropna() * 100
    if len(spread_s) < 50:
        st.warning("Not enough spread data.")
    else:
        setup = fi.spread_option_setup(spread_s, so_expiry, "ATM", 0.0, so_vol_win)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Spread (bps)", f"{setup['Spread (bps)']:.1f}")
        c2.metric("Z-score", f"{setup['Z-score (1Y)']:.2f}")
        c3.metric("Call (bps)", f"{setup['Call Price (bps)']:.2f}")
        c4.metric("Put (bps)", f"{setup['Put Price (bps)']:.2f}")

        greeks = fi.bachelier_greeks(setup["Spread (bps)"], setup["Strike (bps)"],
                                     setup["Hist Vol (bps/yr)"], setup["Expiry (yrs)"], "call")
        gc1, gc2, gc3, gc4 = st.columns(4)
        gc1.metric("Delta", f"{greeks['delta']:.3f}")
        gc2.metric("Gamma", f"{greeks['gamma']:.5f}")
        gc3.metric("Vega", f"{greeks['vega']:.3f}")
        gc4.metric("Theta/day", f"{greeks['theta']:.3f}")

        # Payoff diagram
        strikes = np.linspace(setup["Spread (bps)"]-80, setup["Spread (bps)"]+80, 80)
        call_pnl = [max(s - setup["Strike (bps)"], 0) - setup["Call Price (bps)"] for s in strikes]
        put_pnl = [max(setup["Strike (bps)"] - s, 0) - setup["Put Price (bps)"] for s in strikes]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=strikes, y=call_pnl, name="Bought Call", line=dict(color="#42a5f5")))
        fig.add_trace(go.Scatter(x=strikes, y=put_pnl, name="Bought Put", line=dict(color="#ef5350")))
        fig.add_hline(y=0, line_dash="dot", line_color="grey")
        fig.add_vline(x=setup["Spread (bps)"], line_dash="dash", line_color="white", annotation_text="Current")
        fig.update_layout(template=PLOTLY_THEME, title=f"{so_t1}/{so_t2} Spread Option P&L at Expiry",
                          xaxis_title="Spread at Expiry (bps)", yaxis_title="P&L (bps)")
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Spread Options Screen")
    sdict = {}
    for t1, t2 in fi.SPREAD_PAIRS:
        s1, s2 = rate_series(df, t1), rate_series(df, t2)
        if len(s1) > 100 and len(s2) > 100:
            sdict[f"{t1}/{t2}"] = (s2 - s1).dropna() * 100
    if sdict:
        screen = fi.spread_option_screen(sdict, so_expiry)
        st.dataframe(_safe_style(screen), use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# 6. WEDGE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════
elif section.startswith("6"):
    st.subheader("Wedge Grid (bps)")
    st.caption("Wedge = forward swap rate − spot swap rate. Positive = curve pricing in a rate rise.")

    t_list = sorted([(fi.TENOR_YEARS[t], curve[t]) for t in curve if t in fi.TENOR_YEARS])
    c_tenors = [x[0] for x in t_list]
    c_rates = [x[1] for x in t_list]

    w_grid = fi.wedge_grid(c_tenors, c_rates)
    st.dataframe(_safe_style(w_grid, fmt="{:.1f}", background_gradient=dict(cmap="RdYlGn_r", axis=None)),
                 use_container_width=True)

    st.divider()
    st.subheader("Top Wedge Trades (Risk-Adjusted)")
    vol_win = st.select_slider("Vol window", [21, 42, 63, 126], value=63, key="wedge_vol")
    tcm = {t: t for t in curve}
    col_map = {_col(df, t): t for t in ALL_TENORS if _col(df, t)}
    rdf_renamed = df.rename(columns=col_map)
    top = fi.run_wedge_analysis(c_tenors, c_rates, rdf_renamed, tcm, vol_win, top_n=10)
    st.dataframe(top, use_container_width=True)

    st.divider()
    st.subheader("Specific Wedge")
    wc1, wc2 = st.columns(2)
    with wc1:
        fs = st.selectbox("Forward Start", [1,2,3,5,7,10], index=1)
    with wc2:
        tt = st.selectbox("Tail Tenor", [1,2,3,5,10], index=3)
    w = fi.wedge(c_tenors, c_rates, float(fs), float(tt))
    fwd = fi.forward_swap_rate(c_tenors, c_rates, float(fs), float(tt))
    spot = fi.interpolate_rate(c_tenors, c_rates, float(tt))
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric(f"{fs}Y{tt}Y Forward", f"{fwd:.3f}%")
    mc2.metric(f"{tt}Y Spot", f"{spot:.3f}%")
    mc3.metric("Wedge", f"{w:.1f} bps")


# ═══════════════════════════════════════════════════════════════════════════
# 7. SWAPTIONS
# ═══════════════════════════════════════════════════════════════════════════
elif section.startswith("7"):
    st.subheader("Swaption Pricer")
    t_list = sorted([(fi.TENOR_YEARS[t], curve[t]) for t in curve if t in fi.TENOR_YEARS])
    c_tenors = [x[0] for x in t_list]
    c_rates = [x[1] for x in t_list]

    sc1, sc2, sc3, sc4 = st.columns(4)
    with sc1:
        sw_expiry = st.selectbox("Expiry", ["1M","3M","6M","1Y","2Y","5Y"], index=3)
    with sc2:
        sw_tail = st.selectbox("Tail", ["1Y","2Y","5Y","10Y","20Y","30Y"], index=3)
    with sc3:
        sw_vol = st.number_input("Impl Vol (bps/yr)", 10.0, 500.0, 80.0, 5.0)
    with sc4:
        sw_type = st.selectbox("Type", ["payer", "receiver"])

    exp_yrs = fi.swaptions.EXPIRY_YEARS.get(sw_expiry, 1.0)
    tail_yrs = fi.swaptions.TAIL_YEARS.get(sw_tail, 10.0)
    fwd = fi.forward_swap_rate(c_tenors, c_rates, exp_yrs, tail_yrs)
    strike = fwd  # ATM

    price = fi.bachelier_swaption(fwd, strike, sw_vol, exp_yrs, tail_yrs, sw_type)
    greeks = fi.swaption_greeks(fwd, strike, sw_vol, exp_yrs, tail_yrs, sw_type)

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Forward Rate", f"{fwd:.3f}%")
    mc2.metric("Premium (bps)", f"{price:.2f}")
    mc3.metric("Delta", f"{greeks['delta']:.3f}")
    mc4.metric("Theta/day", f"{greeks['theta']:.3f}")

    st.divider()
    st.subheader("Expected Return (Realised vs Implied Vol)")
    real_vol = st.slider("Realised Vol (bps/yr)", 10.0, 300.0, sw_vol * 1.1, 5.0)
    exp_ret = fi.swaption_expected_return(fwd, strike, sw_vol, exp_yrs, tail_yrs, real_vol, 0.0, sw_type)
    er1, er2, er3, er4 = st.columns(4)
    er1.metric("E[P&L] (bps)", f"{exp_ret['E[P&L] (bps)']:.1f}")
    er2.metric("Sharpe", f"{exp_ret['Sharpe']:.2f}" if not np.isnan(exp_ret.get("Sharpe", np.nan)) else "—")
    er3.metric("Prob Profit", f"{exp_ret['Prob Profit']:.1%}")
    er4.metric("Vol Ratio", f"{exp_ret['Vol Ratio (real/impl)']:.3f}")

    # Premium across strikes
    strikes = np.linspace(fwd - 1.5, fwd + 1.5, 50)
    payer_p = [fi.bachelier_swaption(fwd, K, sw_vol, exp_yrs, tail_yrs, "payer") for K in strikes]
    rcvr_p = [fi.bachelier_swaption(fwd, K, sw_vol, exp_yrs, tail_yrs, "receiver") for K in strikes]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=strikes, y=payer_p, name="Payer", line=dict(color="#ef5350")))
    fig.add_trace(go.Scatter(x=strikes, y=rcvr_p, name="Receiver", line=dict(color="#42a5f5")))
    fig.add_vline(x=fwd, line_dash="dash", line_color="white", annotation_text="ATM")
    fig.update_layout(template=PLOTLY_THEME, title=f"{sw_expiry}{sw_tail} Swaption Premium",
                      xaxis_title="Strike (%)", yaxis_title="Premium (bps)")
    st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# 8. PORTFOLIO ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════
elif section.startswith("8"):
    avail = [t for t in ["2Y","5Y","10Y","30Y"] if _col(df, t)]
    rdf = rate_df_multi(df, avail)

    st.subheader("Rolling Beta")
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        beta_y = st.selectbox("Dependent", avail, index=avail.index("10Y") if "10Y" in avail else 0)
    with bc2:
        beta_x = st.selectbox("Independent", avail, index=avail.index("2Y") if "2Y" in avail else 0)
    with bc3:
        beta_win = st.select_slider("Window", [63,126,252,504], value=252, key="beta_win")

    if beta_y != beta_x:
        beta_s = fi.rolling_beta(rdf[beta_y], rdf[beta_x], beta_win)
        reg = fi.regression_summary(rdf[beta_y], rdf[beta_x], beta_win)
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("Beta", f"{reg.get('Beta', 0):.3f}")
        rc2.metric("R²", f"{reg.get('R²', 0):.3f}")
        rc3.metric("Alpha (ann bps)", f"{reg.get('Alpha (ann bps)', 0):.1f}")
        rc4.metric("Track Error (bps/yr)", f"{reg.get('Tracking Error (bps/yr)', 0):.1f}")

        fig = go.Figure(go.Scatter(x=beta_s.index, y=beta_s.values, line=dict(color="#ab47bc")))
        fig.add_hline(y=1.0, line_dash="dash", line_color="grey")
        fig.update_layout(template=PLOTLY_THEME, title=f"Rolling {beta_win}d Beta: {beta_y} vs {beta_x}",
                          yaxis_title="Beta")
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Sharpe Ratios")
    returns_df = rdf.diff().dropna() * -100  # receiver P&L in bps
    returns_df.columns = [f"Receive {t}" for t in avail]
    sharpe_df = fi.sharpe_table(returns_df)
    st.dataframe(_safe_style(sharpe_df), use_container_width=True)

    st.divider()
    st.subheader("Efficient Frontier")
    frontier = fi.efficient_frontier(returns_df.tail(504), n_portfolios=80)
    max_sr = fi.max_sharpe_portfolio(returns_df.tail(504))

    if not frontier.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=frontier["Vol (ann)"], y=frontier["Return (ann)"],
                                 mode="lines", name="Frontier", line=dict(color="#4fc3f7")))
        if max_sr:
            fig.add_trace(go.Scatter(
                x=[max_sr["Volatility (ann)"]], y=[max_sr["Expected Return (ann)"]],
                mode="markers", marker=dict(size=14, color="#ffca28", symbol="star"),
                name=f"Max Sharpe ({max_sr.get('Sharpe',0):.2f})"
            ))
        fig.update_layout(template=PLOTLY_THEME, title="Efficient Frontier (Receive Fixed)",
                          xaxis_title="Annualised Vol", yaxis_title="Annualised Return")
        st.plotly_chart(fig, use_container_width=True)

        if max_sr:
            st.markdown("**Max Sharpe Portfolio Weights**")
            w_cols = {k: v for k, v in max_sr.items() if k.startswith("w_")}
            if w_cols:
                fig2 = go.Figure(go.Bar(x=list(w_cols.keys()), y=list(w_cols.values()),
                                        marker_color="#66bb6a"))
                fig2.update_layout(template=PLOTLY_THEME, yaxis_title="Weight", height=300)
                st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("Annual Move Indicator")
    annual = fi.annual_move_indicator(rdf)
    st.dataframe(_safe_style(annual), use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# 9. WEEKLY UPDATE TABLES
# ═══════════════════════════════════════════════════════════════════════════
elif section.startswith("9"):
    st.subheader("Weekly Update — OneNote Style")

    rate_series_dict = {t: rate_series(df, t) for t in curve.keys()}

    # Expected return
    exp_tbl = fi.expected_return_table(curve, on_rate, holding_months=1, annualise=True)
    if not exp_tbl.empty:
        st.markdown("**Expected Return (ann bps)**")
        st.dataframe(_safe_style(exp_tbl, fmt="{:.1f}"), use_container_width=True)

    # Sharpe
    sharpe_tbl = fi.sharpe_table_from_rates(curve, on_rate, rate_series_dict, holding_months=1)
    if not sharpe_tbl.empty:
        st.markdown("**Sharpe Ratios**")
        st.dataframe(_safe_style(sharpe_tbl), use_container_width=True)

    # Z-scores
    avail_t = [t for t in curve if t in rate_series_dict and len(rate_series_dict[t]) > 50]
    if avail_t:
        hist_df = pd.concat({t: rate_series_dict[t] for t in avail_t}, axis=1).dropna(how="all")
        z_tbl = fi.zscore_table(hist_df, 252, avail_t)
        st.markdown("**Z-Scores**")
        st.dataframe(_safe_style(z_tbl), use_container_width=True)

    # Wedge grid
    t_list = sorted([(fi.TENOR_YEARS[t], curve[t]) for t in curve if t in fi.TENOR_YEARS])
    if len(t_list) >= 3:
        w_grid = fi.wedge_grid([x[0] for x in t_list], [x[1] for x in t_list])
        st.markdown("**Wedge Grid (bps)**")
        st.dataframe(_safe_style(w_grid, fmt="{:.1f}"), use_container_width=True)

    # ── Efficient Frontier ────────────────────────────────────────────────
    st.divider()
    st.subheader("Efficient Frontier")
    st.caption("Markowitz mean-variance frontier across rate trades, colour-coded by Sharpe ratio.")

    # Build daily returns for available trades: outrights + spreads + flies
    ef_avail = [t for t in curve if t in rate_series_dict and len(rate_series_dict[t]) > 60]
    ef_rets_dict = {}
    # Outrights (daily change in bps)
    for t in ef_avail:
        s = rate_series_dict[t].dropna()
        ef_rets_dict[f"Rcv {t}"] = s.diff().dropna() * 100  # bps
    # Spreads
    ef_spread_pairs = [("2Y","10Y"),("2Y","30Y"),("5Y","10Y"),("5Y","30Y"),("10Y","30Y")]
    for t1, t2 in ef_spread_pairs:
        if t1 in rate_series_dict and t2 in rate_series_dict:
            s1 = rate_series_dict[t1].dropna()
            s2 = rate_series_dict[t2].dropna()
            spread = (s2 - s1).dropna()
            if len(spread) > 60:
                ef_rets_dict[f"{t1}/{t2}"] = spread.diff().dropna() * 100
    # Flies
    ef_fly_trips = [("2Y","5Y","10Y"),("2Y","10Y","30Y"),("5Y","10Y","30Y")]
    for w1, b, w2 in ef_fly_trips:
        if all(x in rate_series_dict for x in [w1, b, w2]):
            sw1 = rate_series_dict[w1].dropna()
            sb = rate_series_dict[b].dropna()
            sw2 = rate_series_dict[w2].dropna()
            fly = (sb - 0.5*sw1 - 0.5*sw2).dropna()
            if len(fly) > 60:
                ef_rets_dict[f"{w1}/{b}/{w2}"] = fly.diff().dropna() * 100

    if len(ef_rets_dict) >= 2:
        ef_rets_df = pd.DataFrame(ef_rets_dict).dropna()

        ef_c1, ef_c2 = st.columns([1, 1])
        with ef_c1:
            ef_n = st.select_slider("Frontier points", [50, 100, 200, 300], value=100, key="ef_n")
        with ef_c2:
            ef_trades = st.multiselect(
                "Trades to include",
                list(ef_rets_dict.keys()),
                default=list(ef_rets_dict.keys()),
                key="ef_trades",
            )

        if len(ef_trades) >= 2:
            ef_sub = ef_rets_df[ef_trades].dropna()
            frontier = fi.efficient_frontier(ef_sub, n_portfolios=ef_n, risk_free_rate=0.0)

            if not frontier.empty:
                # Max Sharpe and Min Variance
                ms = fi.max_sharpe_portfolio(ef_sub, risk_free_rate=0.0)
                mv = fi.min_variance_portfolio(ef_sub)

                # ── Plotly chart: frontier coloured by Sharpe ──
                fig_ef = go.Figure()

                # Frontier curve — scatter coloured by Sharpe (green=high, red=low)
                fig_ef.add_trace(go.Scatter(
                    x=frontier["Vol (ann)"],
                    y=frontier["Return (ann)"],
                    mode="markers",
                    marker=dict(
                        size=6,
                        color=frontier["Sharpe"],
                        colorscale=[
                            [0.0, "#d32f2f"],    # deep red
                            [0.2, "#ff5722"],    # orange-red
                            [0.4, "#ff9800"],    # orange
                            [0.5, "#ffc107"],    # amber
                            [0.6, "#cddc39"],    # lime-yellow
                            [0.8, "#4caf50"],    # green
                            [1.0, "#1b5e20"],    # deep green
                        ],
                        colorbar=dict(title="Sharpe", thickness=15, len=0.6),
                        showscale=True,
                    ),
                    text=[f"Sharpe: {s:.2f}" for s in frontier["Sharpe"]],
                    hovertemplate="Vol: %{x:.1f}<br>Return: %{y:.1f}<br>%{text}<extra></extra>",
                    name="Frontier",
                ))

                # Max Sharpe point
                if ms:
                    fig_ef.add_trace(go.Scatter(
                        x=[ms["Volatility (ann)"]],
                        y=[ms["Expected Return (ann)"]],
                        mode="markers+text",
                        marker=dict(size=16, color="#00e676", symbol="star", line=dict(width=2, color="white")),
                        text=[f"Max Sharpe ({ms['Sharpe']:.2f})"],
                        textposition="top center",
                        textfont=dict(color="#00e676", size=11),
                        name="Max Sharpe",
                        hovertemplate=f"Vol: {ms['Volatility (ann)']:.1f}<br>Ret: {ms['Expected Return (ann)']:.1f}<br>Sharpe: {ms['Sharpe']:.2f}<extra></extra>",
                    ))

                # Min Variance point
                if mv:
                    fig_ef.add_trace(go.Scatter(
                        x=[mv["Volatility (ann)"]],
                        y=[mv["Expected Return (ann)"]],
                        mode="markers+text",
                        marker=dict(size=14, color="#29b6f6", symbol="diamond", line=dict(width=2, color="white")),
                        text=[f"Min Vol ({mv.get('Sharpe', 0):.2f})"],
                        textposition="bottom center",
                        textfont=dict(color="#29b6f6", size=11),
                        name="Min Variance",
                        hovertemplate=f"Vol: {mv['Volatility (ann)']:.1f}<br>Ret: {mv['Expected Return (ann)']:.1f}<br>Sharpe: {mv.get('Sharpe',0):.2f}<extra></extra>",
                    ))

                # Individual assets
                mus_ann = ef_sub.mean() * 252
                vols_ann = ef_sub.std() * np.sqrt(252)
                fig_ef.add_trace(go.Scatter(
                    x=vols_ann.values,
                    y=mus_ann.values,
                    mode="markers+text",
                    marker=dict(size=9, color="#b0bec5", symbol="circle", line=dict(width=1, color="white")),
                    text=list(ef_trades),
                    textposition="top right",
                    textfont=dict(size=9, color="#b0bec5"),
                    name="Individual",
                    hovertemplate="%{text}<br>Vol: %{x:.1f}<br>Ret: %{y:.1f}<extra></extra>",
                ))

                fig_ef.update_layout(
                    template=PLOTLY_THEME,
                    height=550,
                    xaxis_title="Annualised Volatility (bps)",
                    yaxis_title="Annualised Expected Return (bps)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    margin=dict(l=60, r=30, t=50, b=50),
                )
                st.plotly_chart(fig_ef, use_container_width=True)

                # ── Portfolio weights tables ──
                st.divider()
                wt_c1, wt_c2 = st.columns(2)

                with wt_c1:
                    st.markdown("**Max Sharpe Portfolio**")
                    if ms:
                        ms_metrics = {k: v for k, v in ms.items() if not k.startswith("w_")}
                        ms_weights = {k.replace("w_", ""): f"{v*100:.1f}%" for k, v in ms.items() if k.startswith("w_") and abs(v) > 0.001}
                        st.json(ms_metrics)
                        if ms_weights:
                            st.markdown("Weights:")
                            wdf = pd.DataFrame(list(ms_weights.items()), columns=["Trade", "Weight"])
                            st.dataframe(wdf, use_container_width=True, hide_index=True)

                with wt_c2:
                    st.markdown("**Min Variance Portfolio**")
                    if mv:
                        mv_metrics = {k: v for k, v in mv.items() if not k.startswith("w_")}
                        mv_weights = {k.replace("w_", ""): f"{v*100:.1f}%" for k, v in mv.items() if k.startswith("w_") and abs(v) > 0.001}
                        st.json(mv_metrics)
                        if mv_weights:
                            st.markdown("Weights:")
                            wdf2 = pd.DataFrame(list(mv_weights.items()), columns=["Trade", "Weight"])
                            st.dataframe(wdf2, use_container_width=True, hide_index=True)
            else:
                st.warning("Frontier optimisation returned no feasible points.")
        else:
            st.info("Select at least 2 trades to compute the frontier.")
    else:
        st.info("Need at least 2 trade series to build the efficient frontier.")


# ═══════════════════════════════════════════════════════════════════════════
# 10. CUSTOM TRADE BUILDER
# ═══════════════════════════════════════════════════════════════════════════
elif section.startswith("10"):
    st.subheader("Custom Trade Builder")
    avail = [t for t in ALL_TENORS if _col(df, t)]
    trade_type = st.radio("Trade Type", ["Outright", "Spread", "Butterfly"], horizontal=True)

    if trade_type == "Outright":
        t1 = st.selectbox("Tenor", avail, index=avail.index("10Y") if "10Y" in avail else 0)
        s = rate_series(df, t1)
        cr = fi.snapshot_carry_rolldown(curve, on_rate, "outright", t1, holding_months=1)
        z = fi.zscore(s, 252)

        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric(f"{t1} Rate", f"{curve.get(t1, 0):.3f}%")
        mc2.metric("Z-score", f"{fi.zscore_current(s, 252):.2f}")
        mc3.metric("Carry+Rolldown", f"{cr['total']:.2f} bps/m")
        mc4.metric("Ann Total", f"{cr['total']*12:.1f} bps/yr")

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            subplot_titles=[f"{t1} (%)", "Z-score"])
        fig.add_trace(go.Scatter(x=s.index, y=s.values, line=dict(color="#4fc3f7")), row=1, col=1)
        fig.add_trace(go.Scatter(x=z.index, y=z.values, line=dict(color="#ff8a65")), row=2, col=1)
        fig.add_hline(y=1.5, line_dash="dash", line_color="green", row=2, col=1)
        fig.add_hline(y=-1.5, line_dash="dash", line_color="red", row=2, col=1)
        fig.update_layout(template=PLOTLY_THEME, height=500, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    elif trade_type == "Spread":
        sc1, sc2 = st.columns(2)
        with sc1:
            sp_t1 = st.selectbox("Short Leg", avail, index=avail.index("2Y") if "2Y" in avail else 0)
        with sc2:
            sp_t2 = st.selectbox("Long Leg", avail, index=avail.index("10Y") if "10Y" in avail else min(2, len(avail)-1))

        s1, s2 = rate_series(df, sp_t1), rate_series(df, sp_t2)
        spread = (s2 - s1).dropna() * 100
        cr = fi.snapshot_carry_rolldown(curve, on_rate, "spread", sp_t2, sp_t1, holding_months=1)
        z = fi.zscore(spread, 252)

        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Spread (bps)", f"{float(spread.iloc[-1]):.1f}")
        mc2.metric("Z-score", f"{fi.zscore_current(spread, 252):.2f}")
        mc3.metric("Carry+Rolldown", f"{cr['total']:.2f} bps/m")
        mc4.metric("Ann Total", f"{cr['total']*12:.1f} bps/yr")

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            subplot_titles=[f"{sp_t1}/{sp_t2} Spread (bps)", "Z-score"])
        fig.add_trace(go.Scatter(x=spread.index, y=spread.values, line=dict(color="#66bb6a")), row=1, col=1)
        fig.add_trace(go.Scatter(x=z.index, y=z.values, line=dict(color="#ff8a65")), row=2, col=1)
        fig.add_hline(y=1.5, line_dash="dash", line_color="green", row=2, col=1)
        fig.add_hline(y=-1.5, line_dash="dash", line_color="red", row=2, col=1)
        fig.update_layout(template=PLOTLY_THEME, height=500, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    elif trade_type == "Butterfly":
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            f_w1 = st.selectbox("Wing 1", avail, index=avail.index("2Y") if "2Y" in avail else 0)
        with fc2:
            f_b = st.selectbox("Belly", avail, index=avail.index("5Y") if "5Y" in avail else 1)
        with fc3:
            f_w2 = st.selectbox("Wing 2", avail, index=avail.index("10Y") if "10Y" in avail else min(2, len(avail)-1))

        sw1, sb, sw2 = rate_series(df, f_w1), rate_series(df, f_b), rate_series(df, f_w2)
        fly = (sb - 0.5*sw1 - 0.5*sw2).dropna() * 100
        cr = fi.snapshot_carry_rolldown(curve, on_rate, "fly", f_w1, f_b, f_w2, holding_months=1)
        z = fi.zscore(fly, 252)

        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Fly (bps)", f"{float(fly.iloc[-1]):.1f}")
        mc2.metric("Z-score", f"{fi.zscore_current(fly, 252):.2f}")
        mc3.metric("Carry+Rolldown", f"{cr['total']:.2f} bps/m")
        mc4.metric("Ann Total", f"{cr['total']*12:.1f} bps/yr")

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            subplot_titles=[f"{f_w1}/{f_b}/{f_w2} Fly (bps)", "Z-score"])
        fig.add_trace(go.Scatter(x=fly.index, y=fly.values, line=dict(color="#ffa726")), row=1, col=1)
        fig.add_trace(go.Scatter(x=z.index, y=z.values, line=dict(color="#ff8a65")), row=2, col=1)
        fig.add_hline(y=1.5, line_dash="dash", line_color="green", row=2, col=1)
        fig.add_hline(y=-1.5, line_dash="dash", line_color="red", row=2, col=1)
        fig.update_layout(template=PLOTLY_THEME, height=500, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.caption(f"Data: {len(df)} rows  |  {df.index[0].date()} → {df.index[-1].date()}  |  O/N rate: {on_rate:.3f}%")

# ── Tutorial overlay (must be LAST) ────────────────────────────────────
from dashboard.tutorial import render_tutorial
render_tutorial(page="analysis")
