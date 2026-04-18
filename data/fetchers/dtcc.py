"""
Fetch USD interest rate swap activity data from DTCC SDR public dissemination.

This is a BEST-EFFORT data source. DTCC's public API endpoints change frequently
and the data format is not guaranteed to be stable. The fetcher is designed to
degrade gracefully: if the data is unavailable, it returns an empty DataFrame
and logs a warning rather than breaking the pipeline.

No API key is required -- DTCC SDR public dissemination data is freely available.
"""

import io
import logging
import zipfile
from typing import Optional

import pandas as pd

from data.fetchers.base import BaseFetcher, load_cache, save_cache

logger = logging.getLogger(__name__)

# TODO: DTCC endpoints change periodically. If fetches start failing, check
# https://pddata.dtcc.com/ppd/cftcreportlist.do for updated URLs and data
# formats. The SEC (securities-based) and CFTC (commodities-based) portals
# may also swap paths. Last verified: 2024-Q4.

# Base URL for DTCC SDR public data portal
_DTCC_BASE_URL = "https://pddata.dtcc.com/ppd/api/report"

# Cumulative report (ZIP containing CSV) -- fallback if slice API fails
_DTCC_CUMULATIVE_URL = (
    f"{_DTCC_BASE_URL}/cumulative/sec/CUMULATIVE_CREDITS_SEC.zip"
)

# Slice report endpoint -- preferred for date-range queries
_DTCC_SLICE_URL = f"{_DTCC_BASE_URL}/SEC"

# Columns we produce -- downstream code should reference these names
DTCC_COLUMNS = [
    "DTCC_IRS_VOLUME",   # total USD IRS notional traded (billions)
    "DTCC_IRS_COUNT",    # number of trades
    "DTCC_PAY_RATIO",    # payer / (payer + receiver) ratio
    "DTCC_TENOR_2Y",     # notional in 0-3Y bucket (billions)
    "DTCC_TENOR_5Y",     # notional in 3-7Y bucket (billions)
    "DTCC_TENOR_10Y",    # notional in 7-15Y bucket (billions)
    "DTCC_TENOR_30Y",    # notional in 15Y+ bucket (billions)
]


class DTCCFetcher(BaseFetcher):
    """Fetch USD IRS swap activity from DTCC SDR public dissemination.

    This fetcher attempts to pull data from DTCC's public reports. Because
    DTCC frequently changes its API surface and data format, all fetch
    operations are wrapped in broad exception handling. A failure here must
    never break the rest of the data pipeline.
    """

    def __init__(self, start_date: str, end_date: str, use_cache: bool = True):
        super().__init__(start_date, end_date, use_cache)

    def fetch(self) -> pd.DataFrame:
        cache_key = (
            f"dtcc_{self.start.strftime('%Y%m%d')}_{self.end.strftime('%Y%m%d')}"
        )
        if self.use_cache:
            cached = load_cache(cache_key)
            if cached is not None:
                return cached

        # Try the slice API first, then fall back to cumulative download
        raw = self._fetch_slice_reports()
        if raw is None or raw.empty:
            raw = self._fetch_cumulative_report()

        if raw is None or raw.empty:
            logger.warning(
                "DTCC data unavailable -- all fetch attempts failed. "
                "The dashboard will display 'DTCC data unavailable'."
            )
            return pd.DataFrame()

        df = self._parse_and_aggregate(raw)
        if df.empty:
            logger.warning(
                "DTCC data fetched but produced no USD IRS rows after parsing."
            )
            return pd.DataFrame()

        save_cache(cache_key, df)
        return df

    # ------------------------------------------------------------------
    # Fetch strategies
    # ------------------------------------------------------------------

    def _fetch_slice_reports(self) -> Optional[pd.DataFrame]:
        """Attempt to fetch daily slice reports from the DTCC SEC endpoint.

        The slice API accepts date parameters and returns JSON or CSV depending
        on the endpoint version. We try both common param formats.
        """
        try:
            params = {
                "reportDate": self.end.strftime("%m/%d/%Y"),
                "assetClass": "IR",
                "currency": "USD",
            }
            logger.info(
                f"DTCC: attempting slice fetch for {self.end.strftime('%Y-%m-%d')}"
            )
            resp = self.session.get(
                _DTCC_SLICE_URL, params=params, timeout=30
            )
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            if "json" in content_type:
                df = pd.json_normalize(resp.json())
            elif "zip" in content_type or "octet-stream" in content_type:
                df = self._read_zip_csv(resp.content)
            else:
                # Attempt CSV parse as a last resort
                df = pd.read_csv(io.StringIO(resp.text))

            logger.info(f"DTCC slice: got {len(df)} rows")
            self._sleep(0.5)
            return df

        except Exception as e:
            logger.warning(f"DTCC slice fetch failed: {e}")
            return None

    def _fetch_cumulative_report(self) -> Optional[pd.DataFrame]:
        """Download the cumulative ZIP report as a fallback.

        The cumulative file is large and contains all asset classes. We filter
        to USD IRS after download.
        """
        try:
            logger.info("DTCC: attempting cumulative report download")
            resp = self.session.get(_DTCC_CUMULATIVE_URL, timeout=60)
            resp.raise_for_status()
            df = self._read_zip_csv(resp.content)
            logger.info(f"DTCC cumulative: got {len(df)} rows before filtering")
            self._sleep(1.0)
            return df

        except Exception as e:
            logger.warning(f"DTCC cumulative fetch failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_zip_csv(content: bytes) -> Optional[pd.DataFrame]:
        """Extract the first CSV from a ZIP archive in memory."""
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
                if not csv_names:
                    logger.warning("DTCC ZIP contained no CSV files")
                    return None
                with zf.open(csv_names[0]) as f:
                    return pd.read_csv(f, low_memory=False)
        except Exception as e:
            logger.warning(f"DTCC ZIP extraction failed: {e}")
            return None

    def _parse_and_aggregate(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Filter to USD IRS trades and aggregate into daily summary rows.

        DTCC column names vary across report versions. We attempt multiple
        known column-name variants and skip gracefully if the schema has
        changed again.
        """
        try:
            raw.columns = [c.strip().upper() for c in raw.columns]

            # --- Identify the product / asset class column ---
            product_col = self._find_column(
                raw,
                ["PRODUCT_TYPE", "PRODUCT TYPE", "ASSET_CLASS", "ASSET CLASS",
                 "TAXONOMY", "SUB_ASSET_CLASS", "SUB ASSET CLASS"],
            )
            currency_col = self._find_column(
                raw,
                ["NOTIONAL_CURRENCY_1", "NOTIONAL CURRENCY 1",
                 "CURRENCY", "NOTIONAL_CURRENCY", "NOTIONAL CURRENCY"],
            )
            notional_col = self._find_column(
                raw,
                ["ROUNDED_NOTIONAL_AMOUNT_1", "ROUNDED NOTIONAL AMOUNT 1",
                 "NOTIONAL_AMOUNT_1", "NOTIONAL AMOUNT 1",
                 "NOTIONAL", "ORIGINAL_NOTIONAL", "ORIGINAL NOTIONAL"],
            )
            date_col = self._find_column(
                raw,
                ["EXECUTION_TIMESTAMP", "EXECUTION TIMESTAMP",
                 "EFFECTIVE_DATE", "EFFECTIVE DATE",
                 "TRADE_DATE", "TRADE DATE", "REPORT_DATE", "REPORT DATE"],
            )
            tenor_col = self._find_column(
                raw,
                ["EXPIRATION_DATE", "EXPIRATION DATE",
                 "END_DATE", "END DATE", "MATURITY_DATE", "MATURITY DATE"],
            )
            direction_col = self._find_column(
                raw,
                ["OPTION_TYPE", "OPTION TYPE", "BUYSELL",
                 "BUY_SELL", "BUY SELL", "DIRECTION",
                 "PAYER_RECEIVER", "PAYER RECEIVER"],
            )

            if notional_col is None or date_col is None:
                logger.warning(
                    "DTCC: could not identify required columns "
                    f"(notional={notional_col}, date={date_col}). "
                    f"Available columns: {list(raw.columns[:20])}"
                )
                return pd.DataFrame()

            # --- Filter to USD interest rate swaps ---
            mask = pd.Series(True, index=raw.index)
            if product_col is not None:
                irs_terms = ["INTEREST RATE", "IRS", "SWAP", "IR"]
                mask &= raw[product_col].astype(str).str.upper().apply(
                    lambda x: any(t in x for t in irs_terms)
                )
            if currency_col is not None:
                mask &= raw[currency_col].astype(str).str.upper() == "USD"

            filtered = raw.loc[mask].copy()
            if filtered.empty:
                return pd.DataFrame()

            # --- Parse dates and notionals ---
            filtered["_date"] = pd.to_datetime(
                filtered[date_col], errors="coerce"
            ).dt.normalize()
            filtered["_notional"] = pd.to_numeric(
                filtered[notional_col], errors="coerce"
            )
            filtered = filtered.dropna(subset=["_date", "_notional"])

            # Restrict to requested date range
            filtered = filtered[
                (filtered["_date"] >= self.start)
                & (filtered["_date"] <= self.end)
            ]
            if filtered.empty:
                return pd.DataFrame()

            # --- Compute tenor buckets (years to maturity) ---
            if tenor_col is not None:
                filtered["_tenor_date"] = pd.to_datetime(
                    filtered[tenor_col], errors="coerce"
                )
                filtered["_years"] = (
                    (filtered["_tenor_date"] - filtered["_date"]).dt.days / 365.25
                )
            else:
                filtered["_years"] = float("nan")

            # --- Compute directional signal ---
            if direction_col is not None:
                dir_upper = filtered[direction_col].astype(str).str.upper()
                filtered["_is_payer"] = dir_upper.isin(
                    ["PAY", "PAYER", "P", "BUY", "B"]
                )
            else:
                filtered["_is_payer"] = float("nan")

            # --- Aggregate by date ---
            result = self._aggregate_daily(filtered)
            return result

        except Exception as e:
            logger.warning(f"DTCC parse/aggregate failed: {e}")
            return pd.DataFrame()

    def _aggregate_daily(self, df: pd.DataFrame) -> pd.DataFrame:
        """Roll trade-level rows into daily summary metrics."""
        to_billions = 1e-9
        records = []

        for date, grp in df.groupby("_date"):
            total_notional = grp["_notional"].sum() * to_billions
            trade_count = len(grp)

            # Directional ratio
            if grp["_is_payer"].notna().any():
                n_payer = grp["_is_payer"].sum()
                pay_ratio = n_payer / trade_count if trade_count > 0 else float("nan")
            else:
                pay_ratio = float("nan")

            # Tenor buckets
            tenor_2y = (
                grp.loc[grp["_years"] <= 3, "_notional"].sum() * to_billions
            )
            tenor_5y = (
                grp.loc[
                    (grp["_years"] > 3) & (grp["_years"] <= 7), "_notional"
                ].sum()
                * to_billions
            )
            tenor_10y = (
                grp.loc[
                    (grp["_years"] > 7) & (grp["_years"] <= 15), "_notional"
                ].sum()
                * to_billions
            )
            tenor_30y = (
                grp.loc[grp["_years"] > 15, "_notional"].sum() * to_billions
            )

            records.append(
                {
                    "DTCC_IRS_VOLUME": round(total_notional, 3),
                    "DTCC_IRS_COUNT": trade_count,
                    "DTCC_PAY_RATIO": round(pay_ratio, 4) if pd.notna(pay_ratio) else float("nan"),
                    "DTCC_TENOR_2Y": round(tenor_2y, 3),
                    "DTCC_TENOR_5Y": round(tenor_5y, 3),
                    "DTCC_TENOR_10Y": round(tenor_10y, 3),
                    "DTCC_TENOR_30Y": round(tenor_30y, 3),
                    "_date": date,
                }
            )

        if not records:
            return pd.DataFrame()

        result = pd.DataFrame(records).set_index("_date")
        result.index.name = None
        result = result.sort_index()
        return result

    @staticmethod
    def _find_column(df: pd.DataFrame, candidates: list) -> Optional[str]:
        """Return the first column name from candidates that exists in df."""
        upper_cols = {c.upper(): c for c in df.columns}
        for name in candidates:
            key = name.upper().strip()
            if key in upper_cols:
                return upper_cols[key]
        return None
