"""Central configuration for the Rates Dashboard."""

from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Default date range
# ---------------------------------------------------------------------------
DEFAULT_END_DATE   = datetime.today().strftime("%Y-%m-%d")
DEFAULT_START_DATE = (datetime.today() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")

# ---------------------------------------------------------------------------
# Treasury yield-curve tenors
# ---------------------------------------------------------------------------
TREASURY_TENORS = {
    "1M":  "DGS1MO",
    "3M":  "DGS3MO",
    "6M":  "DGS6MO",
    "1Y":  "DGS1",
    "2Y":  "DGS2",
    "3Y":  "DGS3",
    "5Y":  "DGS5",
    "7Y":  "DGS7",
    "10Y": "DGS10",
    "20Y": "DGS20",
    "30Y": "DGS30",
}

# Tenor labels in order (for curve plots)
TENOR_LABELS = list(TREASURY_TENORS.keys())

# Tenor in years (for Nelson-Siegel fitting)
TENOR_YEARS = [1/12, 3/12, 6/12, 1, 2, 3, 5, 7, 10, 20, 30]

# Treasury.gov XML field names → our tenor labels
TREASURY_XML_FIELDS = {
    "BC_1MONTH": "1M",
    "BC_3MONTH": "3M",
    "BC_6MONTH": "6M",
    "BC_1YEAR":  "1Y",
    "BC_2YEAR":  "2Y",
    "BC_3YEAR":  "3Y",
    "BC_5YEAR":  "5Y",
    "BC_7YEAR":  "7Y",
    "BC_10YEAR": "10Y",
    "BC_20YEAR": "20Y",
    "BC_30YEAR": "30Y",
}

# ---------------------------------------------------------------------------
# SOFR / swap rates (FRED series)
# ---------------------------------------------------------------------------
SOFR_SERIES = {
    "SOFR":         "SOFR",               # Overnight SOFR
    "SOFR_1Y":      "ICERATES1100USD1Y",  # ICE SOFR swap 1Y
    "SOFR_2Y":      "ICERATES1100USD2Y",
    "SOFR_5Y":      "ICERATES1100USD5Y",
    "SOFR_10Y":     "ICERATES1100USD10Y",
    "SOFR_30Y":     "ICERATES1100USD30Y",
}

SOFR_TENOR_LABELS  = ["1Y", "2Y", "5Y", "10Y", "30Y"]
SOFR_TENOR_COLUMNS = ["SOFR_1Y", "SOFR_2Y", "SOFR_5Y", "SOFR_10Y", "SOFR_30Y"]

# ---------------------------------------------------------------------------
# Corporate / credit spread series (ICE BofA OAS via FRED)
# ---------------------------------------------------------------------------
CORP_SPREAD_SERIES = {
    "IG_OAS":   "BAMLC0A0CM",    # US Corp Master (all IG)
    "AAA_OAS":  "BAMLC0A1CAAA",
    "AA_OAS":   "BAMLC0A2CAA",
    "A_OAS":    "BAMLC0A3CA",
    "BBB_OAS":  "BAMLC0A4CBBB",
    "HY_OAS":   "BAMLH0A0HYM2",  # US HY Master II
    "BB_OAS":   "BAMLH0A1HYBB",
    "B_OAS":    "BAMLH0A2HYB",
    "CCC_OAS":  "BAMLH0A3HYC",
    "EM_OAS":   "BAMLEMCBPIOAS", # EM Corp
}

# ---------------------------------------------------------------------------
# International government bond yields (FRED - monthly, ffilled to daily)
# ---------------------------------------------------------------------------
INTL_SERIES = {
    # Germany (EUR proxy) - OECD/FRED monthly
    "DE_2Y":   "IRLTST01DEM156N",   # Germany short-term 2Y
    "DE_10Y":  "IRLTLT01DEM156N",   # Germany 10Y Bund
    # UK Gilts
    "GB_2Y":   "IRLTST01GBM156N",   # UK short-term 2Y
    "GB_10Y":  "IRLTLT01GBM156N",   # UK 10Y Gilt
    # Switzerland
    "CH_10Y":  "IRLTLT01CHM156N",   # Switzerland 10Y
    # Japan
    "JP_10Y":  "IRLTLT01JPM156N",   # Japan 10Y JGB
    # ECB policy rate
    "ECB_RATE": "ECBDFR",           # ECB Deposit Facility Rate (daily)
}

# ---------------------------------------------------------------------------
# Macro / inflation series
# ---------------------------------------------------------------------------
MACRO_SERIES = {
    "FEDFUNDS":     "FEDFUNDS",   # Effective Fed Funds (monthly avg)
    "EFFR":         "EFFR",       # Daily EFFR
    "DFF":          "DFF",        # Daily Fed Funds (same as EFFR, wider history)
    "TIPS_10Y":     "DFII10",     # 10Y TIPS real yield
    "BREAKEVEN_5Y": "T5YIE",      # 5Y breakeven
    "BREAKEVEN_10Y":"T10YIE",     # 10Y breakeven
    "VIX":          "VIXCLS",     # CBOE VIX
    "MOVE":         "MRACIOTM",   # ICE BofA MOVE Index (rates implied vol)
    "ON_RRP":       "RRPONTSYD",  # ON Reverse Repo (overnight, $bn)
}

# ---------------------------------------------------------------------------
# Spread definitions   (col_a - col_b)
# ---------------------------------------------------------------------------
SPREAD_DEFINITIONS = {
    "2s10s":           ("10Y", "2Y"),
    "5s30s":           ("30Y", "5Y"),
    "3m10y":           ("10Y", "3M"),
    "2s5s":            ("5Y",  "2Y"),
    "1s10s":           ("10Y", "1Y"),
    "Swap Spread 10Y": ("SOFR_10Y", "10Y"),
    "Swap Spread 2Y":  ("SOFR_2Y",  "2Y"),
}

# ---------------------------------------------------------------------------
# Plotly theme
# ---------------------------------------------------------------------------
PLOTLY_THEME = "plotly_dark"
PRIMARY_COLOR   = "#00D4FF"
SECONDARY_COLOR = "#FF6B6B"
ACCENT_COLOR    = "#FFD93D"
POSITIVE_COLOR  = "#6BCB77"
NEGATIVE_COLOR  = "#FF6B6B"
