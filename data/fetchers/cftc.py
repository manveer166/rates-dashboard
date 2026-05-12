"""
Fetch CFTC Commitment of Traders data for Treasury and SOFR futures positioning.
Uses the CFTC Traders in Financial Futures (TFF) Socrata dataset.
No API key required.

Correct endpoint: gpe5-46if  (TFF — has Leveraged Funds + Asset Manager breakdown)
The legacy endpoint jun7-fc8e is the standard COT and does NOT have those categories.
"""

import logging
from typing import Dict, List

import pandas as pd

from data.fetchers.base import BaseFetcher, load_cache, save_cache

logger = logging.getLogger(__name__)

# CFTC contract market codes for rates futures in the TFF report
CONTRACT_CODES: Dict[str, str] = {
    "2Y":   "042601",   # UST 2Y Note
    "5Y":   "044601",   # UST 5Y Note
    "10Y":  "043602",   # UST 10Y Note
    "30Y":  "020601",   # UST Bond
    "SOFR": "710601",   # 3M SOFR / Eurodollar
}

# TFF (Traders in Financial Futures) Socrata endpoint
CFTC_TFF_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"

# Fields to pull — NOTE: column names differ from the legacy COT endpoint
SELECT_FIELDS = [
    "report_date_as_yyyy_mm_dd",
    "cftc_contract_market_code",
    "lev_money_positions_long",
    "lev_money_positions_short",
    "asset_mgr_positions_long",
    "asset_mgr_positions_short",
]


class CFTCFetcher(BaseFetcher):
    """Fetch weekly CFTC TFF Leveraged Funds + Asset Manager positioning data."""

    def __init__(self, start_date: str, end_date: str, use_cache: bool = True):
        super().__init__(start_date, end_date, use_cache)

    def fetch(self) -> pd.DataFrame:
        cache_key = (
            f"cftc_{self.start.strftime('%Y%m%d')}_{self.end.strftime('%Y%m%d')}"
        )
        if self.use_cache:
            cached = load_cache(cache_key)
            if cached is not None:
                if cached.index.max() >= self.end - pd.Timedelta(days=14):
                    return cached

        df = self._fetch_cot_data()
        if df.empty:
            return df

        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df.index = pd.to_datetime(df.index)

        # COT data is weekly (Tuesday reports). Resample to daily and
        # forward-fill so it aligns with the master DataFrame's daily index.
        # Limit to 7 days — if more than a week gap, leave as NaN.
        df = df.resample("D").asfreq().ffill(limit=7)

        save_cache(cache_key, df)
        return df

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_query_params(self) -> Dict[str, str]:
        """Build Socrata SoQL query parameters for the TFF endpoint."""
        code_list = ", ".join(
            f"'{code}'" for code in CONTRACT_CODES.values()
        )
        start_str = self.start.strftime("%Y-%m-%dT00:00:00.000")

        where_clause = (
            f"report_date_as_yyyy_mm_dd >= '{start_str}' "
            f"AND cftc_contract_market_code in({code_list})"
        )

        params = {
            "$where":  where_clause,
            "$select": ", ".join(SELECT_FIELDS),
            "$limit":  "50000",
            "$order":  "report_date_as_yyyy_mm_dd ASC",
        }
        return params

    def _fetch_cot_data(self) -> pd.DataFrame:
        """Hit the TFF Socrata API and reshape into wide-format columns."""
        params = self._build_query_params()

        try:
            logger.info("CFTC: fetching TFF data from Socrata API")
            resp = self.session.get(CFTC_TFF_URL, params=params, timeout=30)
            resp.raise_for_status()
            records = resp.json()
        except Exception as e:
            logger.warning(f"CFTC TFF API request failed: {e}")
            return pd.DataFrame()

        self._sleep(0.5)

        if not records:
            logger.warning("CFTC TFF: API returned no records")
            return pd.DataFrame()

        raw = pd.DataFrame(records)
        return self._reshape(raw)

    def _reshape(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Convert raw TFF rows into wide-format net positioning columns."""
        # Parse the date column (TFF uses yyyy_mm_dd format)
        raw["date"] = pd.to_datetime(
            raw["report_date_as_yyyy_mm_dd"], errors="coerce"
        )
        raw = raw.dropna(subset=["date"])

        # Filter to our date range
        raw = raw[(raw["date"] >= self.start) & (raw["date"] <= self.end)]
        if raw.empty:
            return pd.DataFrame()

        # Cast position fields to numeric (TFF column names lack the _all suffix)
        pos_cols = [
            "lev_money_positions_long",
            "lev_money_positions_short",
            "asset_mgr_positions_long",
            "asset_mgr_positions_short",
        ]
        for col in pos_cols:
            if col in raw.columns:
                raw[col] = pd.to_numeric(raw[col], errors="coerce").fillna(0)

        # Build a code-to-label lookup (reverse of CONTRACT_CODES)
        code_to_label = {code: label for label, code in CONTRACT_CODES.items()}

        # Compute net positions per contract per date
        frames: List[pd.DataFrame] = []
        for code, label in code_to_label.items():
            subset = raw[raw["cftc_contract_market_code"] == code].copy()
            if subset.empty:
                continue

            subset = subset.set_index("date")
            piece = pd.DataFrame(index=subset.index)

            # Leveraged money net = long - short
            piece[f"COT_{label}_NET_LEV"] = (
                subset["lev_money_positions_long"]
                - subset["lev_money_positions_short"]
            )
            # Asset manager net = long - short
            piece[f"COT_{label}_NET_AM"] = (
                subset["asset_mgr_positions_long"]
                - subset["asset_mgr_positions_short"]
            )

            frames.append(piece)

        if not frames:
            return pd.DataFrame()

        result = pd.concat(frames, axis=1)
        result.index.name = None
        return result
