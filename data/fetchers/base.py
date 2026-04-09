"""Base fetcher with caching, retry logic, and session management."""

import time
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def get_session(retries: int = 3, backoff: float = 0.5) -> requests.Session:
    """Return a requests Session with retry logic and browser-like headers."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/xml,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    return session


def load_cache(key: str):
    """Load a cached DataFrame from parquet, or return None if missing."""
    path = CACHE_DIR / f"{key}.parquet"
    if path.exists():
        try:
            df = pd.read_parquet(path)
            logger.debug(f"Cache hit: {key}")
            return df
        except Exception as e:
            logger.warning(f"Cache read failed for {key}: {e}")
    return None


def save_cache(key: str, df: pd.DataFrame) -> None:
    """Persist a DataFrame to parquet cache."""
    path = CACHE_DIR / f"{key}.parquet"
    try:
        df.to_parquet(path)
        logger.debug(f"Cache saved: {key}")
    except Exception as e:
        logger.warning(f"Cache write failed for {key}: {e}")


class BaseFetcher(ABC):
    """Abstract base class for all data fetchers."""

    def __init__(self, start_date: str, end_date: str, use_cache: bool = True):
        self.start = pd.Timestamp(start_date)
        self.end   = pd.Timestamp(end_date)
        self.use_cache = use_cache
        self.session = get_session()

    @abstractmethod
    def fetch(self) -> pd.DataFrame:
        """Fetch data and return a DataFrame with DatetimeIndex."""
        ...

    def _sleep(self, seconds: float = 0.5) -> None:
        time.sleep(seconds)
