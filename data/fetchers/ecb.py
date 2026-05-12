"""ECB Statistical Data Warehouse — euro-area AAA government yield curve.

Pulls daily spot rates from the ECB's published AAA-rated euro-area government
bond yield curve (the standard EUR risk-free benchmark used by EUR rates
desks). One series per tenor; CSV format, no API key required.

Series key: YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_<tenor>

Tenors offered: 3M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y
"""

from __future__ import annotations

import io
import logging

import pandas as pd

from data.fetchers.base import BaseFetcher, load_cache, save_cache

logger = logging.getLogger(__name__)

# ECB's AAA euro-area sovereign zero-coupon spot curve.  Daily, all from one
# dataset (YC), one series per tenor.
ECB_SERIES = {
    "EU_3M":  "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_3M",
    "EU_6M":  "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_6M",
    "EU_1Y":  "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y",
    "EU_2Y":  "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y",
    "EU_3Y":  "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_3Y",
    "EU_5Y":  "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_5Y",
    "EU_7Y":  "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_7Y",
    "EU_10Y": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
    "EU_20Y": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_20Y",
    "EU_30Y": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_30Y",
}

ECB_BASE = "https://data-api.ecb.europa.eu/service/data/YC/"


class ECBFetcher(BaseFetcher):
    """Fetch ECB AAA euro-area yield curve from the SDW."""

    def fetch(self) -> pd.DataFrame:
        cache_key = f"ecb_{self.start.strftime('%Y%m%d')}_{self.end.strftime('%Y%m%d')}"
        if self.use_cache:
            cached = load_cache(cache_key)
            if cached is not None and cached.index.max() >= self.end - pd.Timedelta(days=7):
                return cached

        frames: list[pd.Series] = []
        for col_name, series_key in ECB_SERIES.items():
            url = (
                f"{ECB_BASE}{series_key}"
                f"?format=csvdata"
                f"&startPeriod={self.start.strftime('%Y-%m-%d')}"
                f"&endPeriod={self.end.strftime('%Y-%m-%d')}"
            )
            try:
                r = self.session.get(url, timeout=30)
                r.raise_for_status()
                df = pd.read_csv(io.StringIO(r.text))
                if "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
                    logger.warning("ECB %s: unexpected columns %s", series_key, list(df.columns))
                    continue
                s = pd.Series(
                    pd.to_numeric(df["OBS_VALUE"], errors="coerce").values,
                    index=pd.to_datetime(df["TIME_PERIOD"]),
                    name=col_name,
                )
                frames.append(s)
                logger.info("ECB: fetched %s -> %s (%d rows)", series_key, col_name, len(s))
            except Exception as e:
                logger.warning("ECB fetch failed for %s: %s", series_key, e)
            self._sleep(0.1)

        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, axis=1).sort_index()
        out = out[~out.index.duplicated(keep="last")]
        save_cache(cache_key, out)
        return out
