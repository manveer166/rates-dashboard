"""
07_Data_Sources.py — Data Sources & Metadata reference page.

Lists every data series used in the dashboard with descriptions,
FRED codes, source URLs, and live availability status.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from config import (
    TREASURY_TENORS, SOFR_SERIES, CORP_SPREAD_SERIES,
    INTL_SERIES, MACRO_SERIES, PLOTLY_THEME,
)
from dashboard.state import get_master_df, init_session_state
from dashboard.components.controls import render_sidebar_controls

st.set_page_config(page_title="Data Sources", page_icon="📡", layout="wide")
init_session_state()
render_sidebar_controls()

st.title("📡 Data Sources")
st.caption("All data series used across the dashboard, with FRED codes, source URLs, and current availability.")

df = get_master_df()

def _status(col):
    if col in df.columns:
        s = df[col].dropna()
        if len(s) > 0:
            return f"✅ {len(s)} obs → {s.index[-1].strftime('%Y-%m-%d')}"
    return "❌ Not loaded"

# ═══════════════════════════════════════════════════════════════════════════
# 1. US TREASURY YIELDS
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("🇺🇸 US Treasury Yields")
st.markdown("""
**Primary source:** [US Treasury Dept XML API](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml)
with FRED fallback.

Treasury constant-maturity yields are published daily by the US Department
of the Treasury. They represent the interpolated yield curve for on-the-run
Treasury securities.
""")

tsy_rows = []
for label, fred_code in TREASURY_TENORS.items():
    tsy_rows.append({
        "Tenor": label,
        "FRED Code": fred_code,
        "FRED URL": f"https://fred.stlouisfed.org/series/{fred_code}",
        "Description": f"Treasury Constant Maturity {label}",
        "Status": _status(label),
    })
tsy_df = pd.DataFrame(tsy_rows)
st.dataframe(tsy_df, use_container_width=True, hide_index=True,
             column_config={
                 "FRED URL": st.column_config.LinkColumn("FRED Link", display_text="Open"),
             })

# ═══════════════════════════════════════════════════════════════════════════
# 2. SOFR & SWAP RATES
# ═══════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("💱 SOFR & Swap Rates")
st.markdown("""
**Source:** [ICE Benchmark Administration](https://www.theice.com/iba/sofr) via FRED.

SOFR (Secured Overnight Financing Rate) is the replacement for USD LIBOR.
The ICE SOFR swap rates represent fixed rates on SOFR-linked interest rate swaps
at various tenors.
""")

sofr_rows = []
for label, fred_code in SOFR_SERIES.items():
    desc_map = {
        "SOFR": "Secured Overnight Financing Rate (daily)",
        "SOFR_1Y": "ICE SOFR Swap Rate 1Y",
        "SOFR_2Y": "ICE SOFR Swap Rate 2Y",
        "SOFR_3Y": "ICE SOFR Swap Rate 3Y",
        "SOFR_5Y": "ICE SOFR Swap Rate 5Y",
        "SOFR_7Y": "ICE SOFR Swap Rate 7Y",
        "SOFR_10Y": "ICE SOFR Swap Rate 10Y",
        "SOFR_15Y": "ICE SOFR Swap Rate 15Y",
        "SOFR_20Y": "ICE SOFR Swap Rate 20Y",
        "SOFR_30Y": "ICE SOFR Swap Rate 30Y",
    }
    sofr_rows.append({
        "Label": label,
        "FRED Code": fred_code,
        "FRED URL": f"https://fred.stlouisfed.org/series/{fred_code}",
        "Description": desc_map.get(label, f"SOFR / Swap {label}"),
        "Status": _status(label),
    })
sofr_df = pd.DataFrame(sofr_rows)
st.dataframe(sofr_df, use_container_width=True, hide_index=True,
             column_config={
                 "FRED URL": st.column_config.LinkColumn("FRED Link", display_text="Open"),
             })

# ═══════════════════════════════════════════════════════════════════════════
# 3. CORPORATE CREDIT SPREADS
# ═══════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("🏢 Corporate Credit Spreads (ICE BofA OAS)")
st.markdown("""
**Source:** [ICE BofA via FRED](https://fred.stlouisfed.org/categories/32413)

Option-Adjusted Spreads (OAS) for US corporate bonds, broken down by
investment grade (IG) and high yield (HY) rating buckets.
OAS measures the spread above the risk-free curve after accounting for
embedded optionality.
""")

credit_rows = []
desc_credit = {
    "IG_OAS": "US Corporate Master OAS (all IG)",
    "AAA_OAS": "AAA-rated Corporate OAS",
    "AA_OAS": "AA-rated Corporate OAS",
    "A_OAS": "A-rated Corporate OAS",
    "BBB_OAS": "BBB-rated Corporate OAS",
    "HY_OAS": "US High Yield Master II OAS",
    "BB_OAS": "BB-rated High Yield OAS",
    "B_OAS": "B-rated High Yield OAS",
    "CCC_OAS": "CCC & below High Yield OAS",
    "EM_OAS": "Emerging Markets Corporate OAS",
}
for label, fred_code in CORP_SPREAD_SERIES.items():
    credit_rows.append({
        "Label": label,
        "FRED Code": fred_code,
        "FRED URL": f"https://fred.stlouisfed.org/series/{fred_code}",
        "Description": desc_credit.get(label, label),
        "Status": _status(label),
    })
credit_df = pd.DataFrame(credit_rows)
st.dataframe(credit_df, use_container_width=True, hide_index=True,
             column_config={
                 "FRED URL": st.column_config.LinkColumn("FRED Link", display_text="Open"),
             })

# ═══════════════════════════════════════════════════════════════════════════
# 4. INTERNATIONAL YIELDS
# ═══════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("🌍 International Government Bond Yields")
st.markdown("""
**Source:** OECD via FRED (monthly, forward-filled to daily).

Long-term and short-term interest rates for major economies.
These are based on OECD Main Economic Indicators — typically 10-year
benchmark government bond yields.
""")

intl_rows = []
desc_intl = {
    "DE_2Y": "Germany 2Y government bond yield (EUR)",
    "DE_10Y": "Germany 10Y Bund yield (EUR)",
    "GB_2Y": "UK 2Y Gilt yield (GBP)",
    "GB_10Y": "UK 10Y Gilt yield (GBP)",
    "CH_10Y": "Switzerland 10Y government bond yield (CHF)",
    "JP_10Y": "Japan 10Y JGB yield (JPY)",
    "ECB_RATE": "ECB Deposit Facility Rate",
}
for label, fred_code in INTL_SERIES.items():
    intl_rows.append({
        "Label": label,
        "FRED Code": fred_code,
        "FRED URL": f"https://fred.stlouisfed.org/series/{fred_code}",
        "Description": desc_intl.get(label, label),
        "Status": _status(label),
    })
intl_df = pd.DataFrame(intl_rows)
st.dataframe(intl_df, use_container_width=True, hide_index=True,
             column_config={
                 "FRED URL": st.column_config.LinkColumn("FRED Link", display_text="Open"),
             })

# ═══════════════════════════════════════════════════════════════════════════
# 5. MACRO & INFLATION
# ═══════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("📊 Macro & Inflation Indicators")
st.markdown("""
**Source:** FRED (Federal Reserve Economic Data).

Key monetary policy and inflation expectation series used for
macro context in the dashboard.
""")

macro_rows = []
desc_macro = {
    "FEDFUNDS": "Effective Federal Funds Rate (monthly avg)",
    "EFFR": "Effective Federal Funds Rate (daily)",
    "TIPS_10Y": "10-Year TIPS Real Yield (DFII10)",
    "BREAKEVEN_5Y": "5-Year Breakeven Inflation Rate (T5YIE)",
    "BREAKEVEN_10Y": "10-Year Breakeven Inflation Rate (T10YIE)",
    "VIX": "CBOE Volatility Index (VIX)",
}
for label, fred_code in MACRO_SERIES.items():
    macro_rows.append({
        "Label": label,
        "FRED Code": fred_code,
        "FRED URL": f"https://fred.stlouisfed.org/series/{fred_code}",
        "Description": desc_macro.get(label, label),
        "Status": _status(label),
    })
macro_df = pd.DataFrame(macro_rows)
st.dataframe(macro_df, use_container_width=True, hide_index=True,
             column_config={
                 "FRED URL": st.column_config.LinkColumn("FRED Link", display_text="Open"),
             })

# ═══════════════════════════════════════════════════════════════════════════
# 6. SOURCE LINKS & API DOCUMENTATION
# ═══════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("🔗 Source Links & API Documentation")

sources = [
    {"Source": "FRED (Federal Reserve Economic Data)",
     "URL": "https://fred.stlouisfed.org/",
     "Notes": "Primary data backend for all non-Treasury series. API key in .env (FRED_API_KEY)"},
    {"Source": "US Treasury Dept — Daily Yield Curve",
     "URL": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml",
     "Notes": "XML API with monthly pagination. Used for Treasury CMT yields with FRED fallback"},
    {"Source": "ICE Benchmark Administration — SOFR",
     "URL": "https://www.theice.com/iba/sofr",
     "Notes": "SOFR overnight rate and term SOFR swap rates (via FRED ICERATES1100USD series)"},
    {"Source": "ICE BofA — Credit Indices",
     "URL": "https://fred.stlouisfed.org/categories/32413",
     "Notes": "Option-adjusted spreads for IG/HY corporate bonds. Updated daily via FRED"},
    {"Source": "OECD Main Economic Indicators",
     "URL": "https://data.oecd.org/interest/long-term-interest-rates.htm",
     "Notes": "International government bond yields. Monthly frequency, forward-filled"},
    {"Source": "fredapi Python library",
     "URL": "https://github.com/mortada/fredapi",
     "Notes": "Python wrapper for the FRED API. pip install fredapi"},
    {"Source": "pandas-datareader (fallback)",
     "URL": "https://pandas-datareader.readthedocs.io/",
     "Notes": "Fallback data reader when fredapi is unavailable. No API key needed but rate-limited"},
]
src_df = pd.DataFrame(sources)
st.dataframe(src_df, use_container_width=True, hide_index=True,
             column_config={
                 "URL": st.column_config.LinkColumn("Link", display_text="Open"),
             })

# ═══════════════════════════════════════════════════════════════════════════
# 7. DATA SUMMARY
# ═══════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("📈 Data Summary")

if not df.empty:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Columns", len(df.columns))
    c2.metric("Date Range", f"{df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}")
    c3.metric("Trading Days", len(df))
    loaded = sum(1 for c in df.columns if df[c].dropna().shape[0] > 0)
    c4.metric("Active Series", f"{loaded} / {len(df.columns)}")

    st.markdown("**Column Coverage:**")
    cov_rows = []
    for c in df.columns:
        s = df[c].dropna()
        cov_rows.append({
            "Column": c,
            "Obs": len(s),
            "First": s.index[0].strftime('%Y-%m-%d') if len(s) > 0 else "—",
            "Last": s.index[-1].strftime('%Y-%m-%d') if len(s) > 0 else "—",
            "Last Value": round(float(s.iloc[-1]), 4) if len(s) > 0 else None,
            "NaN %": round((1 - len(s)/len(df)) * 100, 1),
        })
    cov_df = pd.DataFrame(cov_rows)
    st.dataframe(cov_df, use_container_width=True, hide_index=True)
else:
    st.warning("No data loaded. Hit Refresh Data in the sidebar.")
