"""
Fetch SOFR swap rates, corporate bond spreads, and macro series from FRED.
Uses fredapi with optional API key, falls back to pandas_datareader.
"""

import logging
import os
import time

import pandas as pd
from dotenv import load_dotenv

from config import CORP_SPREAD_SERIES, INTL_SERIES, MACRO_SERIES, SOFR_SERIES
from data.fetchers.base import BaseFetcher, load_cache, save_cache

load_dotenv()
logger = logging.getLogger(__name__)

ALL_FRED_SERIES = {**SOFR_SERIES, **CORP_SPREAD_SERIES, **MACRO_SERIES, **INTL_SERIES}


class FREDFetcher(BaseFetcher):
    """Fetch SOFR swaps, credit spreads, and macro data from FRED."""

    def __init__(self, start_date: str, end_date: str, use_cache: bool = True):
        super().__init__(start_date, end_date, use_cache)
        self.api_key = os.getenv("FRED_API_KEY")

    def fetch(self) -> pd.DataFrame:
        cache_key = f"fred_{self.start.strftime('%Y%m%d')}_{self.end.strftime('%Y%m%d')}"
        if self.use_cache:
            cached = load_cache(cache_key)
            if cached is not None:
                if cached.index.max() >= self.end - pd.Timedelta(days=7):
                    return cached

        if self.api_key:
            df = self._fetch_with_fredapi()
        else:
            df = self._fetch_with_datareader()

        if df.empty:
            return df

        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df.index = pd.to_datetime(df.index)

        save_cache(cache_key, df)
        return df

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_with_fredapi(self) -> pd.DataFrame:
        """Use fredapi (higher rate limit with API key)."""
        try:
            from fredapi import Fred
            fred = Fred(api_key=self.api_key)
            frames = []
            for col_name, series_id in ALL_FRED_SERIES.items():
                try:
                    s = fred.get_series(
                        series_id,
                        observation_start=self.start.strftime("%Y-%m-%d"),
                        observation_end=self.end.strftime("%Y-%m-%d"),
                    )
                    s.name = col_name
                    frames.append(s)
                    logger.info(f"FRED (fredapi): fetched {series_id} -> {col_name}")
                    time.sleep(0.1)
                except Exception as e:
                    logger.warning(f"fredapi failed for {series_id}: {e}")
            return pd.concat(frames, axis=1) if frames else pd.DataFrame()
        except ImportError:
            logger.warning("fredapi not installed, falling back to pandas_datareader")
            return self._fetch_with_datareader()

    def _fetch_with_datareader(self) -> pd.DataFrame:
        """Use pandas_datareader (no key required, rate-limited)."""
        import pandas_datareader.data as web
        frames = []
        for col_name, series_id in ALL_FRED_SERIES.items():
            try:
                s = web.DataReader(series_id, "fred", self.start, self.end).squeeze()
                s.name = col_name
                frames.append(s)
                logger.info(f"FRED (datareader): fetched {series_id} -> {col_name}")
                time.sleep(0.25)   # be polite without an API key
            except Exception as e:
                logger.warning(f"pandas_datareader failed for {series_id}: {e}")
        return pd.concat(frames, axis=1) if frames else pd.DataFrame()
