"""OpenBB wrapper — single import surface for OpenBB-sourced datasets.

Why a wrapper:
  • OpenBB's `obb` object boots ~1.5s the first time it's imported (router
    cache + extension loading). We do that once here, lazy-style.
  • Many endpoints have multiple providers (federal_reserve, fred, fmp, ...).
    The wrapper picks a sensible free-no-key default and lets callers override.
  • All functions return tidy pandas DataFrames keyed by date.  No pydantic
    plumbing leaks into the dashboard pages.

Usage:
    from data.openbb_data import yield_curve_us, sovereign_cds, oecd_cli, bls_jolts

    df = yield_curve_us()              # one tenor per row, latest snapshot
    cds = sovereign_cds("DE", "FR")    # daily 5Y CDS spreads
    cli = oecd_cli(["G7", "US", "EA"]) # composite leading indicators
"""

from __future__ import annotations

import functools
import logging
from datetime import datetime, timedelta
from typing import Iterable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _obb():
    """Lazy import — first call takes ~1-2s (router/extension build)."""
    import warnings
    warnings.filterwarnings("ignore")
    from openbb import obb
    return obb


def _df(result) -> pd.DataFrame:
    """Tidy OpenBB OBBject → DataFrame, datetime-indexed if there's a date col."""
    try:
        df = result.to_dataframe()
    except Exception:
        try:
            return pd.DataFrame(result.results)
        except Exception:
            return pd.DataFrame()
    # Reset / re-index on the date column if needed
    for col in ("date", "Date", "datetime"):
        if col in df.columns:
            df = df.set_index(col)
            break
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index)
        except Exception:
            pass
    return df


def _safe(fn):
    """Decorator: swallow OpenBB errors, return empty df + log."""
    @functools.wraps(fn)
    def _wrap(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:
            logger.warning("OpenBB call %s failed: %s", fn.__name__, e)
            return pd.DataFrame()
    return _wrap


# ── Yield curves ─────────────────────────────────────────────────────────

@_safe
def yield_curve_us(date: Optional[str] = None) -> pd.DataFrame:
    """Today's US Treasury par yield curve from the Fed (free, no key)."""
    kw = {"provider": "federal_reserve"}
    if date:
        kw["date"] = date
    return _df(_obb().fixedincome.government.yield_curve(**kw))


# Countries econdb supports for yield_curve (keyless).
# Hong Kong is listed but populated empty as of 2026-05 — use Singapore as a
# practical HK proxy (currency-board market with similar dynamics).
ECONDB_YIELD_COUNTRIES = [
    "australia", "canada", "china", "hong_kong", "india", "japan", "mexico",
    "new_zealand", "russia", "saudi_arabia", "singapore", "south_africa",
    "south_korea", "taiwan", "thailand", "united_kingdom", "united_states",
]


@_safe
def yield_curve(country: str = "united_states",
                date: Optional[str] = None) -> pd.DataFrame:
    """Sovereign yield curve for any econdb-supported country (keyless).

    Returns DataFrame indexed by maturity_years with a 'rate' column.
    Empty if the provider has no data for the country/date.
    """
    kw = {"provider": "econdb", "country": country}
    if date: kw["date"] = date
    return _df(_obb().fixedincome.government.yield_curve(**kw))


@_safe
def asia_yield_snapshot(countries: Iterable[str] = ("china", "japan",
                                                      "south_korea",
                                                      "singapore", "taiwan"),
                        date: Optional[str] = None) -> pd.DataFrame:
    """Latest sovereign yield curves across Asian markets.  Tidy long form:
    one row per (country, maturity_years, rate)."""
    out: list = []
    for c in countries:
        df = yield_curve(c, date=date)
        if df.empty:
            continue
        df = df.copy()
        df["country"] = c.replace("_", " ").title()
        out.append(df)
    return pd.concat(out) if out else pd.DataFrame()


@_safe
def yield_curve_history(country: str = "united_states",
                        start: Optional[str] = None) -> pd.DataFrame:
    """OECD historical yield curve (long-rate) for a country."""
    start = start or (datetime.today() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
    return _df(_obb().economy.long_term_interest_rate(country=country,
                                                       start_date=start,
                                                       provider="oecd"))


# Note on key-required endpoints (deferred — need user-supplied keys):
#   • sovereign CDS               → needs fmp_api_key or tradingeconomics_key
#   • fixedincome.spreads.tcm     → needs fred_api_key
#   • fixedincome.government.tips_yields → needs fred_api_key
#   • bls JOLTS via OpenBB        → needs bls_api_key (FRED has JTSJOL/JTSQUR/JTSLDR free)
#   • imf_indicators              → needs subscription
# All below endpoints work keyless against public providers.


# ── OECD composite leading indicators ────────────────────────────────────

@_safe
def oecd_cli(countries: Iterable[str] = ("united_states", "g7"),
             start: Optional[str] = None) -> pd.DataFrame:
    """OECD Composite Leading Indicator — recession-probability proxy.

    Valid country codes: united_states, united_kingdom, germany, france,
    italy, japan, china, india, canada, brazil, mexico, australia,
    south_korea, indonesia, spain, south_africa, turkey, g7, g20, asia5,
    europe4, north_america, all.
    """
    start = start or (datetime.today() - timedelta(days=10 * 365)).strftime("%Y-%m-%d")
    return _df(_obb().economy.composite_leading_indicator(
        country=",".join(countries), start_date=start, provider="oecd",
    ))


# ── OECD multi-country macro (keyless) ───────────────────────────────────

@_safe
def cpi(countries: Iterable[str] = ("united_states", "euro_area", "united_kingdom"),
        start: Optional[str] = None,
        transform: str = "yoy") -> pd.DataFrame:
    """Headline CPI across countries. transform: 'yoy' (default), 'mom', 'index'."""
    start = start or (datetime.today() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
    return _df(_obb().economy.cpi(
        country=",".join(countries),
        transform=transform,
        start_date=start,
    ))


@_safe
def unemployment(countries: Iterable[str] = ("united_states", "euro_area"),
                 start: Optional[str] = None) -> pd.DataFrame:
    """OECD-harmonised unemployment rates."""
    start = start or (datetime.today() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
    return _df(_obb().economy.unemployment(
        country=",".join(countries), start_date=start,
    ))


@_safe
def money_measures(start: Optional[str] = None) -> pd.DataFrame:
    """US monetary aggregates (M1, M2, M2 components) via federal_reserve."""
    start = start or (datetime.today() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
    return _df(_obb().economy.money_measures(start_date=start))


@_safe
def house_price_index(countries: Iterable[str] = ("united_states",),
                      start: Optional[str] = None) -> pd.DataFrame:
    """OECD harmonised house price index."""
    start = start or (datetime.today() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
    return _df(_obb().economy.house_price_index(
        country=",".join(countries), start_date=start,
    ))


@_safe
def share_price_index(countries: Iterable[str] = ("united_states", "euro_area"),
                      start: Optional[str] = None) -> pd.DataFrame:
    """OECD share-price index — cross-country equity benchmark."""
    start = start or (datetime.today() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
    return _df(_obb().economy.share_price_index(
        country=",".join(countries), start_date=start,
    ))


# ── Health check ─────────────────────────────────────────────────────────

def ping() -> dict:
    """Return which OpenBB extensions are loaded — useful for debugging."""
    try:
        obb = _obb()
        return {
            "ok": True,
            "extensions": [str(x) for x in obb.coverage.commands().keys()][:10]
            if hasattr(obb, "coverage") else ["?"],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
