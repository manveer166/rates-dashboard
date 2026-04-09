"""
Fetch US Treasury yield-curve data from treasury.gov XML API.
Falls back to FRED DGS* series if treasury.gov is unavailable.
"""

import logging
import time
from datetime import datetime
from io import BytesIO

import pandas as pd
from lxml import etree

from config import TREASURY_XML_FIELDS, TREASURY_TENORS
from data.fetchers.base import BaseFetcher, get_session, load_cache, save_cache

logger = logging.getLogger(__name__)

BASE_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/pages/xml?data=daily_treasury_yield_curve"
    "&field_tdr_date_value_month={yyyymm}"
)

ATOM_NS  = "http://www.w3.org/2005/Atom"
PROPS_NS = "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"


class TreasuryFetcher(BaseFetcher):
    """Fetch daily Treasury yield curve rates from treasury.gov."""

    def fetch(self) -> pd.DataFrame:
        cache_key = f"treasury_{self.start.strftime('%Y%m')}_{self.end.strftime('%Y%m')}"
        if self.use_cache:
            cached = load_cache(cache_key)
            if cached is not None:
                # Check if cache covers the requested range
                if cached.index.max() >= self.end - pd.Timedelta(days=7):
                    return cached

        months = self._month_range(self.start, self.end)
        frames = []
        for i, (year, month) in enumerate(months):
            try:
                df = self._fetch_month(year, month)
                if not df.empty:
                    frames.append(df)
                logger.info(f"Treasury: fetched {year}-{month:02d}")
            except Exception as e:
                logger.warning(f"Treasury fetch failed for {year}-{month:02d}: {e}. Trying FRED fallback.")
                df = self._fred_fallback(year, month)
                if not df.empty:
                    frames.append(df)

            # Polite delay between requests
            if i < len(months) - 1:
                time.sleep(0.4)

        if not frames:
            logger.error("No Treasury data retrieved from any source.")
            return pd.DataFrame()

        result = pd.concat(frames).sort_index()
        result = result[~result.index.duplicated(keep="last")]
        result = result.loc[self.start:self.end]

        save_cache(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_month(self, year: int, month: int) -> pd.DataFrame:
        url = BASE_URL.format(yyyymm=f"{year}{month:02d}")
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return self._parse_xml(resp.content)

    def _parse_xml(self, content: bytes) -> pd.DataFrame:
        try:
            root = etree.fromstring(content)
        except etree.XMLSyntaxError as e:
            logger.warning(f"XML parse error: {e}")
            return pd.DataFrame()

        records = []
        for entry in root.iter(f"{{{ATOM_NS}}}entry"):
            props = entry.find(f".//{{{PROPS_NS}}}properties")
            if props is None:
                continue
            row = {}
            for child in props:
                tag = child.tag.split("}")[-1]
                row[tag] = child.text
            if row:
                records.append(row)

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        if "NEW_DATE" not in df.columns:
            return pd.DataFrame()

        df["date"] = pd.to_datetime(df["NEW_DATE"], errors="coerce")
        df = df.dropna(subset=["date"]).set_index("date")

        # Keep only known fields
        keep = {k: v for k, v in TREASURY_XML_FIELDS.items() if k in df.columns}
        df = df[list(keep.keys())].rename(columns=keep)
        df = df.apply(pd.to_numeric, errors="coerce")
        df.index = pd.to_datetime(df.index)
        return df.sort_index()

    def _fred_fallback(self, year: int, month: int) -> pd.DataFrame:
        """Pull Treasury tenors from FRED as a fallback for a given month."""
        try:
            import pandas_datareader.data as web
            start = datetime(year, month, 1)
            if month == 12:
                end = datetime(year + 1, 1, 1)
            else:
                end = datetime(year, month + 1, 1)

            frames = []
            for label, series_id in TREASURY_TENORS.items():
                try:
                    s = web.DataReader(series_id, "fred", start, end).squeeze()
                    s.name = label
                    frames.append(s)
                    time.sleep(0.2)
                except Exception as e:
                    logger.warning(f"FRED fallback failed for {series_id}: {e}")

            if not frames:
                return pd.DataFrame()
            return pd.concat(frames, axis=1)
        except Exception as e:
            logger.error(f"FRED fallback completely failed: {e}")
            return pd.DataFrame()

    @staticmethod
    def _month_range(start: pd.Timestamp, end: pd.Timestamp):
        """Generate list of (year, month) tuples between start and end inclusive."""
        months = []
        current = start.replace(day=1)
        while current <= end:
            months.append((current.year, current.month))
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        return months
