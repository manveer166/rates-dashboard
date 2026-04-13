"""
Master data pipeline: orchestrates all fetchers and produces
a single clean DataFrame consumed by all analysis modules.

Sources (in merge priority order — later sources fill gaps, not overwrite):
  1. Treasury.gov  — US Treasury par yields (primary, daily)
  2. FRED           — SOFR swaps, credit OAS, intl yields, macro  (daily/monthly)
  3. EODHD          — Government bond yields, VIX, supplementary  (daily, paid API)
"""

import logging

import pandas as pd

from data.fetchers.fred import FREDFetcher
from data.fetchers.treasury import TreasuryFetcher
from data.fetchers.eodhd import EODHDFetcher

logger = logging.getLogger(__name__)


class DataPipeline:
    """
    Orchestrates Treasury + FRED + EODHD fetchers, merges into one master
    DataFrame, applies alignment and forward-fill.
    """

    def __init__(
        self,
        start_date: str,
        end_date: str,
        use_cache: bool = True,
    ):
        self.start_date = start_date
        self.end_date   = end_date
        self.use_cache  = use_cache

    def load(self) -> pd.DataFrame:
        logger.info("DataPipeline: starting load")

        # 1. Fetch from each source
        treasury = TreasuryFetcher(
            self.start_date, self.end_date, use_cache=self.use_cache
        ).fetch()
        logger.info(f"Treasury rows: {len(treasury)}, cols: {list(treasury.columns)}")

        fred = FREDFetcher(
            self.start_date, self.end_date, use_cache=self.use_cache
        ).fetch()
        logger.info(f"FRED rows: {len(fred)}, cols: {list(fred.columns)}")

        eodhd = EODHDFetcher(
            self.start_date, self.end_date, use_cache=self.use_cache
        ).fetch()
        logger.info(f"EODHD rows: {len(eodhd)}, cols: {list(eodhd.columns)}")

        # 2. Merge on date index (outer join keeps all trading days).
        #    Treasury.gov is the primary source; FRED adds SOFR/credit/macro;
        #    EODHD fills gaps or adds series that the free sources miss.
        sources = [df for df in (treasury, fred, eodhd) if not df.empty]

        if not sources:
            logger.error("No data fetched from any source.")
            return pd.DataFrame()

        master = sources[0]
        for other in sources[1:]:
            # combine_first keeps existing values and only fills NaN gaps
            master = master.combine_first(other)

        # 3. Ensure datetime index and sort
        master.index = pd.to_datetime(master.index)
        master = master.sort_index()

        # 4. Remove duplicate index entries (can occur at month boundaries)
        master = master[~master.index.duplicated(keep="last")]

        # 5. Forward-fill up to 3 days (covers weekends / single-day holidays)
        #    Do NOT use unlimited fill — genuine missing data exists.
        master = master.ffill(limit=3)

        # 6. Drop rows where ALL core treasury tenors are NaN (non-trading days)
        core_cols = [c for c in ["2Y", "5Y", "10Y", "30Y"] if c in master.columns]
        if core_cols:
            master = master.dropna(subset=core_cols, how="all")

        # 7. Filter to requested date range (fetchers may return slightly wider range)
        master = master.loc[self.start_date:self.end_date]

        logger.info(f"Master DataFrame: {len(master)} rows, {master.shape[1]} columns")
        return master
