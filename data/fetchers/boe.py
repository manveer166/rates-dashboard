"""Bank of England — UK gilt nominal par yields via the IADB CSV endpoint.

Single CSV request returns daily par yields for all requested tenors.  Free,
no key required.  IADB series codes:

  IUDSNPY  =  2Y nominal par yield
  IUDMNPY  =  5Y nominal par yield
  IUDLNPY  = 10Y nominal par yield

(These are the tenors BoE publishes to IADB; longer points exist in their
Excel curve files but aren't on the public IADB.)
"""

from __future__ import annotations

import io
import logging

import pandas as pd

from data.fetchers.base import BaseFetcher, load_cache, save_cache

logger = logging.getLogger(__name__)

BOE_SERIES = {
    "UK_2Y":  "IUDSNPY",
    "UK_5Y":  "IUDMNPY",
    "UK_10Y": "IUDLNPY",
}

BOE_BASE = (
    "https://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp"
    "?csv.x=yes&CSVF=TN&UsingCodes=Y"
)


class BoEFetcher(BaseFetcher):
    """Fetch UK gilt nominal par yields (IUDSNPY/IUDMNPY/IUDLNPY) from BoE IADB."""

    def fetch(self) -> pd.DataFrame:
        cache_key = f"boe_{self.start.strftime('%Y%m%d')}_{self.end.strftime('%Y%m%d')}"
        if self.use_cache:
            cached = load_cache(cache_key)
            if cached is not None and cached.index.max() >= self.end - pd.Timedelta(days=7):
                return cached

        codes = ",".join(BOE_SERIES.values())
        # BoE expects dd/Mon/YYYY  (e.g. 01/Apr/2026)
        url = (
            f"{BOE_BASE}"
            f"&Datefrom={self.start.strftime('%d/%b/%Y')}"
            f"&Dateto={self.end.strftime('%d/%b/%Y')}"
            f"&SeriesCodes={codes}"
        )
        try:
            r = self.session.get(url, timeout=30, allow_redirects=True)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
        except Exception as e:
            logger.warning("BoE IADB fetch failed: %s", e)
            return pd.DataFrame()

        if "DATE" not in df.columns:
            logger.warning("BoE IADB: unexpected columns %s", list(df.columns))
            return pd.DataFrame()

        df["DATE"] = pd.to_datetime(df["DATE"], format="%d %b %Y", errors="coerce")
        df = df.dropna(subset=["DATE"]).set_index("DATE").sort_index()

        # Rename the IADB codes to our friendly column names
        rename = {code: name for name, code in BOE_SERIES.items()}
        df = df.rename(columns=rename)
        # Drop any unexpected columns
        df = df[[c for c in BOE_SERIES.keys() if c in df.columns]]
        df = df[~df.index.duplicated(keep="last")]

        logger.info("BoE: fetched %d rows for %s", len(df), list(df.columns))
        save_cache(cache_key, df)
        return df
