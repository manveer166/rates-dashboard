"""
Fetch secured overnight rates (SOFR, TGCR, BGCR) and SOMA holdings
from the NY Fed Markets API.

API docs: https://markets.newyorkfed.org/static/docs/markets-api.html
No API key required.
"""

import logging
from typing import Dict, List, Optional

import pandas as pd

from data.fetchers.base import BaseFetcher, load_cache, save_cache

logger = logging.getLogger(__name__)

BASE_URL = "https://markets.newyorkfed.org/api"

# Secured rate endpoints: key -> (endpoint suffix, column name(s))
RATE_ENDPOINTS: Dict[str, Dict[str, str]] = {
    "sofr": {
        "path": "rates/secured/sofr/search.json",
        "rate_col": "NYFED_SOFR",
        "volume_col": "SOFR_VOLUME",
    },
    "tgcr": {
        "path": "rates/secured/tgcr/search.json",
        "rate_col": "TGCR",
    },
    "bgcr": {
        "path": "rates/secured/bgcr/search.json",
        "rate_col": "BGCR",
    },
}


class NYFedFetcher(BaseFetcher):
    """Fetch SOFR, TGCR, BGCR rates and SOMA Treasury holdings from NY Fed."""

    def __init__(self, start_date: str, end_date: str, use_cache: bool = True):
        super().__init__(start_date, end_date, use_cache)
        # Override Accept header -- the NY Fed API returns JSON
        self.session.headers.update({"Accept": "application/json"})

    def fetch(self) -> pd.DataFrame:
        start_str = self.start.strftime("%Y%m%d")
        end_str = self.end.strftime("%Y%m%d")
        cache_key = f"nyfed_{start_str}_{end_str}"

        if self.use_cache:
            cached = load_cache(cache_key)
            if cached is not None:
                if cached.index.max() >= self.end - pd.Timedelta(days=7):
                    return cached

        frames: List[pd.DataFrame] = []

        # --- Secured overnight rates (SOFR, TGCR, BGCR) ---
        for name, cfg in RATE_ENDPOINTS.items():
            df = self._fetch_rate(name, cfg)
            if df is not None and not df.empty:
                frames.append(df)
            self._sleep(0.25)

        # --- SOMA Treasury holdings (latest snapshot only) ---
        soma_df = self._fetch_soma_latest()
        if soma_df is not None and not soma_df.empty:
            frames.append(soma_df)

        if not frames:
            logger.warning("NYFedFetcher: no data retrieved from any endpoint")
            return pd.DataFrame()

        result = pd.concat(frames, axis=1)
        result = result.sort_index()
        result = result[~result.index.duplicated(keep="last")]
        result.index = pd.to_datetime(result.index)
        result.index.name = "date"

        save_cache(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_rate(self, name: str, cfg: Dict[str, str]) -> Optional[pd.DataFrame]:
        """Fetch a single secured-rate series (SOFR, TGCR, or BGCR)."""
        url = f"{BASE_URL}/{cfg['path']}"
        params = {
            "startDate": self.start.strftime("%Y-%m-%d"),
            "endDate": self.end.strftime("%Y-%m-%d"),
        }
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"NYFed: failed to fetch {name}: {e}")
            return None

        records = data.get("refRates", [])
        if not records:
            logger.warning(f"NYFed: no refRates in {name} response")
            return None

        rows = []
        for rec in records:
            date = rec.get("effectiveDate")
            rate = rec.get("percentRate")
            if date is None or rate is None:
                continue
            row = {
                "date": pd.Timestamp(date),
                cfg["rate_col"]: float(rate),
            }
            # SOFR also carries volume data
            volume_col = cfg.get("volume_col")
            if volume_col and "volumeInBillions" in rec:
                row[volume_col] = float(rec["volumeInBillions"])
            rows.append(row)

        if not rows:
            return None

        df = pd.DataFrame(rows).set_index("date")
        logger.info(f"NYFed: fetched {len(df)} rows for {name}")
        return df

    def _fetch_soma_latest(self) -> Optional[pd.DataFrame]:
        """Fetch the most recent SOMA Treasury holdings summary.

        Returns a single-row DataFrame with SOMA_TSY (par value in billions).
        """
        # Step 1: get the latest available as-of date
        as_of_date = self._get_latest_soma_date()
        if as_of_date is None:
            return None

        self._sleep(0.25)

        # Step 2: fetch holdings summary for that date
        url = f"{BASE_URL}/soma/holdings/summary.json"
        params = {"asOfDate": as_of_date}
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"NYFed: failed to fetch SOMA holdings: {e}")
            return None

        # Navigate the response to find Treasury total par value
        soma_tsy = self._parse_soma_holdings(data)
        if soma_tsy is None:
            logger.warning("NYFed: could not parse Treasury par value from SOMA response")
            return None

        df = pd.DataFrame(
            [{"date": pd.Timestamp(as_of_date), "SOMA_TSY": soma_tsy}]
        ).set_index("date")
        logger.info(f"NYFed: SOMA Treasury holdings as of {as_of_date}: ${soma_tsy:.1f}B")
        return df

    def _get_latest_soma_date(self) -> Optional[str]:
        """Return the most recent SOMA as-of date (YYYY-MM-DD string)."""
        url = f"{BASE_URL}/soma/asofdates/list.json"
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"NYFed: failed to fetch SOMA as-of dates: {e}")
            return None

        # Response contains a list of dates under 'soma.asOfDates' or similar
        dates = data.get("soma", {}).get("asOfDates", [])
        if not dates:
            # Try alternate structure
            dates = data.get("asOfDates", [])
        if not dates:
            logger.warning("NYFed: no SOMA as-of dates found in response")
            return None

        # Dates come sorted; take the last (most recent)
        latest = sorted(dates)[-1]
        logger.debug(f"NYFed: latest SOMA as-of date is {latest}")
        return latest

    def _parse_soma_holdings(self, data: dict) -> Optional[float]:
        """Extract total Treasury par value in billions from SOMA summary."""
        # The summary endpoint nests data differently; try known keys
        holdings = data.get("soma", {}).get("summary", [])
        if not holdings:
            holdings = data.get("summary", [])

        for item in holdings:
            asset_type = item.get("assetType", "").lower()
            if "treasury" in asset_type or "tsy" in asset_type:
                par_value = item.get("parValue") or item.get("currentFaceValue")
                if par_value is not None:
                    # API returns par value in millions; convert to billions
                    return float(par_value) / 1_000
        # If no treasury-specific row, try total
        if holdings:
            total = holdings[0].get("parValue") or holdings[0].get("currentFaceValue")
            if total is not None:
                return float(total) / 1_000

        return None
