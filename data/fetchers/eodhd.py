"""
Fetch rates, bond yields, and macro data from the EODHD Financial API.

EODHD (https://eodhd.com) provides end-of-day data for government bond yields,
indices, and economic indicators. This fetcher maps EODHD symbols to the same
column names used by the Treasury and FRED fetchers so the output plugs straight
into the existing master DataFrame.

API docs: https://eodhd.com/financial-apis/
Requires: EODHD_API_TOKEN in st.secrets (or .streamlit/secrets.toml).
"""

import logging
from typing import Dict, Optional

import pandas as pd
import streamlit as st

from data.fetchers.base import BaseFetcher, get_session, load_cache, save_cache

logger = logging.getLogger(__name__)

# ── EODHD API base ──────────────────────────────────────────────────────────
BASE_URL = "https://eodhd.com/api"

# ── Symbol mappings ─────────────────────────────────────────────────────────
# Maps our dashboard column name → EODHD ticker.
# EODHD uses the "INDX" exchange for government-bond yield indices.

EODHD_BOND_SYMBOLS: Dict[str, str] = {
    # US Treasury yields
    "1Y":   "US1Y.INDX",
    "2Y":   "US2Y.INDX",
    "3Y":   "US3Y.INDX",
    "5Y":   "US5Y.INDX",
    "7Y":   "US7Y.INDX",
    "10Y":  "US10Y.INDX",
    "20Y":  "US20Y.INDX",
    "30Y":  "US30Y.INDX",
    # Germany
    "DE_2Y":  "DE2Y.INDX",
    "DE_10Y": "DE10Y.INDX",
    # UK
    "GB_2Y":  "GB2Y.INDX",
    "GB_10Y": "GB10Y.INDX",
    # Japan
    "JP_10Y": "JP10Y.INDX",
    # Switzerland
    "CH_10Y": "CH10Y.INDX",
}

EODHD_MACRO_SYMBOLS: Dict[str, str] = {
    "VIX":  "VIX.INDX",
}

# Symbols EODHD no longer serves on our plan — every request returns an empty
# payload. Each dead symbol still costs an HTTP round-trip plus the 0.25s
# rate-limit sleep below, so we skip them rather than paying for nothing.
#
# 3Y and 20Y are sourced from US Treasury / FRED anyway, so dropping the
# EODHD fallback loses nothing. The international tickers have no working
# source at all right now — the Home page labels them as unavailable rather
# than showing their last known value.
#
# Last verified dead: 2026-07-30. Remove an entry here to re-enable it.
EODHD_UNAVAILABLE = {
    "3Y", "20Y",
    "DE_2Y", "DE_10Y", "GB_2Y", "GB_10Y", "JP_10Y", "CH_10Y",
}


def _get_api_token() -> Optional[str]:
    """Read the EODHD API token from st.secrets (never hardcoded)."""
    try:
        return st.secrets["EODHD_API_TOKEN"]
    except (FileNotFoundError, KeyError):
        return None


class EODHDFetcher(BaseFetcher):
    """Fetch government bond yields and macro data from EODHD."""

    def __init__(self, start_date: str, end_date: str, use_cache: bool = True):
        super().__init__(start_date, end_date, use_cache)
        self.api_token = _get_api_token()

    # ── Public ───────────────────────────────────────────────────────────

    def fetch(self) -> pd.DataFrame:
        """Fetch all mapped symbols and return a single DataFrame."""
        if not self.api_token:
            logger.warning("EODHD: no API token configured — skipping.")
            return pd.DataFrame()

        cache_key = f"eodhd_{self.start.strftime('%Y%m%d')}_{self.end.strftime('%Y%m%d')}"
        if self.use_cache:
            cached = load_cache(cache_key)
            if cached is not None:
                if cached.index.max() >= self.end - pd.Timedelta(days=7):
                    logger.info(f"EODHD: cache hit ({len(cached)} rows)")
                    return cached

        all_symbols = {k: v for k, v in
                       {**EODHD_BOND_SYMBOLS, **EODHD_MACRO_SYMBOLS}.items()
                       if k not in EODHD_UNAVAILABLE}
        frames = {}

        for col_name, symbol in all_symbols.items():
            try:
                s = self._fetch_eod(symbol)
                if s is not None and not s.empty:
                    frames[col_name] = s
                    logger.info(f"EODHD: {col_name} ({symbol}) -> {len(s)} rows")
                else:
                    logger.warning(f"EODHD: {col_name} ({symbol}) -> empty/no data")
            except Exception as e:
                logger.warning(f"EODHD: {col_name} ({symbol}) failed: {e}")
            self._sleep(0.25)  # rate-limit courtesy

        if not frames:
            logger.error("EODHD: no data fetched from any symbol.")
            return pd.DataFrame()

        df = pd.DataFrame(frames)
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        save_cache(cache_key, df)
        logger.info(f"EODHD: merged {len(df)} rows, {df.shape[1]} columns")
        return df

    # ── Private helpers ──────────────────────────────────────────────────

    def _fetch_eod(self, symbol: str) -> Optional[pd.Series]:
        """Fetch EOD close prices for a single symbol from EODHD.

        Returns a Series indexed by date with the 'close' values,
        or None on failure.
        """
        url = f"{BASE_URL}/eod/{symbol}"
        params = {
            "api_token": self.api_token,
            "fmt":       "json",
            "period":    "d",
            "from":      self.start.strftime("%Y-%m-%d"),
            "to":        self.end.strftime("%Y-%m-%d"),
        }

        resp = self.session.get(url, params=params, timeout=30)

        if resp.status_code == 404:
            logger.debug(f"EODHD 404 for {symbol} — symbol may not exist")
            return None
        resp.raise_for_status()

        data = resp.json()
        if not data or not isinstance(data, list):
            return None

        records = pd.DataFrame(data)
        if "date" not in records.columns or "close" not in records.columns:
            return None

        records["date"] = pd.to_datetime(records["date"])
        records = records.set_index("date").sort_index()
        return records["close"]
