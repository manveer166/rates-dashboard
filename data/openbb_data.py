"""Macro / curve data fetcher — hybrid (direct APIs first, OpenBB fallback).

Design:
  • Direct APIs for everything that has a free keyless source — US Treasury
    via FRED, Japan via MoF, OECD CLI / CPI / unemployment via FRED's OECD
    mirrors. No AGPL exposure for any of these.
  • OpenBB-econdb as a FALLBACK for the Asian sovereign curves (China,
    Korea, Singapore, Taiwan) that don't have a clean direct keyless API.
    We use a slim 4-package OpenBB install (openbb + openbb-core +
    openbb-fixedincome + openbb-econdb) — not the full 30-package stack.

AGPL note:
  OpenBB Platform is AGPLv3. Using it inside a paid product (i.e. this
  dashboard's Pro tier) triggers the network-service clause: in strict
  reading you must release source under AGPL OR get a commercial license.
  The hybrid approach keeps the AGPL surface area minimal (4 packages,
  one endpoint, one function). See DEPLOY.md for the practical position.

Data sources used:
  • pandas_datareader → FRED  — US Treasury, OECD CLI / CPI / unemployment
                                / HPI / share-price-index mirrors
  • Japan MoF JGB daily CSV   — JGB curve (Shift-JIS, Reiwa-era dates)
  • OpenBB-econdb             — China / Korea / Singapore / Taiwan curves
  • data/fetchers/ECB         — used by consumers as their own EUR fallback
"""

from __future__ import annotations

import functools
import logging
from datetime import datetime, timedelta
from typing import Iterable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _safe(fn):
    """Decorator: swallow errors, return empty DataFrame, log warning.
    Lets the dashboard pages handle missing data gracefully."""
    @functools.wraps(fn)
    def _wrap(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:
            logger.warning("%s failed: %s", fn.__name__, e)
            return pd.DataFrame()
    return _wrap


# ── FRED helper (pandas_datareader, no key required) ─────────────────────

def _fred_series(sid: str, start: Optional[pd.Timestamp] = None) -> pd.Series:
    """Pull a single FRED series via pandas_datareader (no API key required).
    Returns empty Series on any failure — let callers degrade gracefully."""
    import warnings; warnings.filterwarnings("ignore")
    try:
        import pandas_datareader.data as web
    except ImportError:
        logger.warning("pandas_datareader not installed — FRED unavailable")
        return pd.Series(dtype=float)
    start = start or (datetime.today() - timedelta(days=10 * 365))
    try:
        s = web.DataReader(sid, "fred", start, datetime.today())
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        return s.dropna()
    except Exception as e:
        logger.warning("FRED series %s failed: %s", sid, e)
        return pd.Series(dtype=float)


# ── US Treasury yield curve ──────────────────────────────────────────────

# FRED constant-maturity Treasury series IDs, keyed by years.
FRED_UST_TENORS = {
    1 / 12: "DGS1MO",
    0.25:   "DGS3MO",
    0.5:    "DGS6MO",
    1:      "DGS1",
    2:      "DGS2",
    3:      "DGS3",
    5:      "DGS5",
    7:      "DGS7",
    10:     "DGS10",
    20:     "DGS20",
    30:     "DGS30",
}


@_safe
def yield_curve_us(date: Optional[str] = None) -> pd.DataFrame:
    """US Treasury par yield curve from FRED's constant-maturity series.

    Returns DataFrame with `maturity_years` + `rate` columns; `rate` is
    in decimal form (0.045 = 4.5%) to match the previous OpenBB return."""
    target = pd.to_datetime(date) if date else None
    rows = []
    for years, sid in FRED_UST_TENORS.items():
        s = _fred_series(sid)
        if s.empty:
            continue
        if target is not None:
            s = s[s.index <= target]
            if s.empty:
                continue
        rows.append({"maturity_years": float(years),
                     "rate":            float(s.iloc[-1]) / 100})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("maturity_years").reset_index(drop=True)


# ── Japan JGB curve via MoF daily CSV ────────────────────────────────────

@_safe
def _japan_yield_curve(date: Optional[str] = None) -> pd.DataFrame:
    """JGB yield curve from Japan MoF daily CSV (public, no key).

    The MoF file uses Shift-JIS encoding, Reiwa-era dates (e.g. `R8.5.13`
    = Reiwa year 8, May 13 = 2026-05-13), and kanji column headers like
    `1年` (year). Tenor order is fixed: 1Y, 2Y, ..., 10Y, 15Y, 20Y, 25Y,
    30Y, 40Y."""
    url = "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"
    # Header is on line 2; first line is just a Japanese title.
    df = pd.read_csv(url, encoding="cp932", skiprows=1, on_bad_lines="skip")
    if df.empty or len(df.columns) < 2:
        return pd.DataFrame()
    # Reiwa era → Gregorian: R{Y}.{M}.{D}  ->  (2018 + Y, M, D)
    def _reiwa(s: str):
        s = str(s).strip()
        if not s.startswith("R"):
            return pd.NaT
        try:
            y, m, d = s[1:].split(".")
            return pd.Timestamp(2018 + int(y), int(m), int(d))
        except Exception:
            return pd.NaT
    date_col = df.columns[0]
    df[date_col] = df[date_col].apply(_reiwa)
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
    # Tenors in fixed positional order (jgbcm.csv schema):
    tenors_years = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 30, 40]
    value_cols = df.columns[: len(tenors_years)]
    for c in value_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    target = pd.to_datetime(date) if date else df.index.max()
    candidates = df.loc[df.index <= target]
    if candidates.empty:
        return pd.DataFrame()
    snap = candidates.iloc[-1]
    rows = []
    for yrs, col in zip(tenors_years, value_cols):
        val = snap[col]
        if pd.isna(val):
            continue
        rows.append({"maturity_years": float(yrs), "rate": float(val) / 100})
    return (pd.DataFrame(rows).sort_values("maturity_years").reset_index(drop=True)
            if rows else pd.DataFrame())


# Asian sovereign markets we route through OpenBB-econdb (no clean keyless
# direct source for these — and the econdb provider works keyless inside
# the OpenBB SDK). Hong Kong is listed but econdb has no daily data.
_ECONDB_ASIA = {"china", "south_korea", "singapore", "taiwan",
                "hong_kong", "thailand"}


@_safe
def _econdb_yield_curve(country: str,
                        date: Optional[str] = None) -> pd.DataFrame:
    """Sovereign curve via OpenBB-econdb. Optional fallback for the
    Asian markets we don't have direct integrations for.

    Returns DataFrame with `maturity_years` + `rate` columns to match the
    direct fetchers' contract. Returns empty if openbb isn't installed or
    the provider has no data."""
    try:
        from openbb import obb
    except ImportError:
        logger.warning("openbb not installed — %s curve unavailable", country)
        return pd.DataFrame()
    kw = {"provider": "econdb", "country": country}
    if date:
        kw["date"] = date
    r = obb.fixedincome.government.yield_curve(**kw)
    df = r.to_dataframe()
    # econdb returns: date (index) | maturity (str) | rate (decimal) |
    # country | maturity_years. Keep only what consumers need.
    if df.empty or "maturity_years" not in df.columns or "rate" not in df.columns:
        return pd.DataFrame()
    out = df[["maturity_years", "rate"]].reset_index(drop=True)
    out["maturity_years"] = out["maturity_years"].astype(float)
    out["rate"] = out["rate"].astype(float)
    return out.sort_values("maturity_years").reset_index(drop=True)


@_safe
def yield_curve(country: str = "united_states",
                date: Optional[str] = None) -> pd.DataFrame:
    """Sovereign yield curve — hybrid routing.

    Direct keyless sources (no AGPL exposure):
      • united_states → FRED
      • japan         → MoF

    OpenBB-econdb fallback (AGPL — but we only use it for these):
      • china, south_korea, singapore, taiwan, hong_kong, thailand

    Other countries return empty — consuming pages have their own
    fallbacks (data/fetchers/ECB for euro-area, BoE IADB for UK).
    """
    if country == "united_states":
        return yield_curve_us(date=date)
    if country == "japan":
        return _japan_yield_curve(date=date)
    if country in _ECONDB_ASIA:
        return _econdb_yield_curve(country, date=date)
    return pd.DataFrame()


@_safe
def asia_yield_snapshot(countries: Iterable[str] = ("china", "japan",
                                                     "south_korea",
                                                     "singapore", "taiwan"),
                        date: Optional[str] = None) -> pd.DataFrame:
    """Latest sovereign yield curves across Asian markets.

    Japan via MoF (direct), the rest via OpenBB-econdb (keyless).
    Hong Kong's regulator retired their public yield API; Singapore is
    the standard practitioner proxy when needed."""
    out = []
    for c in countries:
        df = yield_curve(c, date=date)
        if df.empty:
            continue
        df = df.copy()
        df["country"] = c.replace("_", " ").title()
        out.append(df)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


# ── OECD-derived macro via FRED mirrors ──────────────────────────────────

# FRED hosts the canonical OECD CLI series under the pattern
# `{ISO3}LOLITONOSTSAM` — same data, no auth.
OECD_CLI_FRED = {
    "united_states":  "USALOLITONOSTSAM",
    "g7":             "G7LOLITONOSTSAM",
    "euro_area":      "EA19LOLITONOSTSAM",
    "germany":        "DEULOLITONOSTSAM",
    "japan":          "JPNLOLITONOSTSAM",
    "united_kingdom": "GBRLOLITONOSTSAM",
    "france":         "FRALOLITONOSTSAM",
    "canada":         "CANLOLITONOSTSAM",
    "china":          "CHNLOLITONOSTSAM",
}

# Consuming pages match on this label set (title-cased, spaces).
COUNTRY_LABEL = {
    "united_states":  "United States",
    "g7":             "G7",
    "euro_area":      "Euro Area",
    "germany":        "Germany",
    "japan":          "Japan",
    "united_kingdom": "United Kingdom",
    "france":         "France",
    "canada":         "Canada",
    "china":          "China",
    "australia":      "Australia",
    "south_korea":    "South Korea",
    "singapore":      "Singapore",
    "taiwan":         "Taiwan",
}


def _series_to_long(series_dict: dict,
                    label_map: Optional[dict] = None) -> pd.DataFrame:
    """Stack a {country_code: Series} mapping into long-form DataFrame:
    date index, `country` (label) + `value` columns. Matches OpenBB's
    OECD return shape so consuming pages don't need to change."""
    label_map = label_map or {}
    frames = []
    for code, s in series_dict.items():
        if s.empty:
            continue
        label = label_map.get(code, code.replace("_", " ").title())
        f = s.to_frame("value")
        f["country"] = label
        f.index.name = "date"
        frames.append(f)
    return pd.concat(frames).sort_index() if frames else pd.DataFrame()


@_safe
def oecd_cli(countries: Iterable[str] = ("united_states", "g7"),
             start: Optional[str] = None) -> pd.DataFrame:
    """OECD Composite Leading Indicator via FRED mirrors (level, 100 = trend)."""
    start_dt = (pd.to_datetime(start) if start
                else datetime.today() - timedelta(days=10 * 365))
    series = {}
    for c in countries:
        sid = OECD_CLI_FRED.get(c)
        if not sid:
            continue
        s = _fred_series(sid, start=start_dt)
        if not s.empty:
            series[c] = s[s.index >= start_dt]
    return _series_to_long(series, COUNTRY_LABEL)


# CPI: pull the index level from FRED then compute YoY / MoM ourselves so
# callers get a uniform transform parameter regardless of source series.
OECD_CPI_INDEX_FRED = {
    "united_states":  "CPIAUCSL",
    "euro_area":      "CP0000EZ19M086NEST",  # Eurostat HICP via FRED
    "united_kingdom": "GBRCPIALLMINMEI",
    "japan":          "JPNCPIALLMINMEI",
    "germany":        "DEUCPIALLMINMEI",
    "france":         "FRACPIALLMINMEI",
    "canada":         "CANCPIALLMINMEI",
}


@_safe
def cpi(countries: Iterable[str] = ("united_states", "euro_area",
                                      "united_kingdom"),
        start: Optional[str] = None,
        transform: str = "yoy") -> pd.DataFrame:
    """Headline CPI by country via FRED. transform: 'yoy' | 'mom' | 'index'."""
    start_dt = (pd.to_datetime(start) if start
                else datetime.today() - timedelta(days=5 * 365))
    # Pull ~13 extra months so YoY at start_dt has a real baseline.
    pull_start = start_dt - timedelta(days=400) if transform == "yoy" else start_dt
    series = {}
    for c in countries:
        sid = OECD_CPI_INDEX_FRED.get(c)
        if not sid:
            continue
        s = _fred_series(sid, start=pull_start)
        if s.empty:
            continue
        if transform == "yoy":
            s = s.pct_change(12) * 100
        elif transform == "mom":
            s = s.pct_change() * 100
        # 'index' → pass through
        s = s.dropna()
        s = s[s.index >= start_dt]
        if not s.empty:
            series[c] = s
    return _series_to_long(series, COUNTRY_LABEL)


# Harmonised unemployment rates (OECD) mirrored on FRED.
UNEMPL_FRED = {
    "united_states":  "UNRATE",
    "euro_area":      "LRHUTTTTEZM156S",
    "united_kingdom": "LRHUTTTTGBM156S",
    "japan":          "LRHUTTTTJPM156S",
    "germany":        "LRHUTTTTDEM156S",
    "france":         "LRHUTTTTFRM156S",
    "canada":         "LRHUTTTTCAM156S",
}


@_safe
def unemployment(countries: Iterable[str] = ("united_states", "euro_area"),
                 start: Optional[str] = None) -> pd.DataFrame:
    """Harmonised unemployment rates via FRED OECD mirrors."""
    start_dt = (pd.to_datetime(start) if start
                else datetime.today() - timedelta(days=5 * 365))
    series = {}
    for c in countries:
        sid = UNEMPL_FRED.get(c)
        if not sid:
            continue
        s = _fred_series(sid, start=start_dt)
        if not s.empty:
            series[c] = s[s.index >= start_dt]
    return _series_to_long(series, COUNTRY_LABEL)


# ── Backwards-compat shims (kept because pages may import them) ──────────

@_safe
def yield_curve_history(country: str = "united_states",
                        start: Optional[str] = None) -> pd.DataFrame:
    """OECD long-term interest-rate history via FRED mirrors."""
    series_map = {
        "united_states":  "DGS10",
        "united_kingdom": "IRLTLT01GBM156N",
        "germany":        "IRLTLT01DEM156N",
        "japan":          "IRLTLT01JPM156N",
        "euro_area":      "IRLTLT01EZM156N",
        "france":         "IRLTLT01FRM156N",
        "canada":         "IRLTLT01CAM156N",
    }
    sid = series_map.get(country, "DGS10")
    start_dt = (pd.to_datetime(start) if start
                else datetime.today() - timedelta(days=5 * 365))
    s = _fred_series(sid, start=start_dt)
    return s.to_frame("rate") if not s.empty else pd.DataFrame()


@_safe
def money_measures(start: Optional[str] = None) -> pd.DataFrame:
    """US M1 / M2 from FRED."""
    start_dt = (pd.to_datetime(start) if start
                else datetime.today() - timedelta(days=5 * 365))
    cols = {}
    for sid, label in [("M1SL", "M1"), ("M2SL", "M2")]:
        s = _fred_series(sid, start=start_dt)
        if not s.empty:
            cols[label] = s
    return pd.DataFrame(cols) if cols else pd.DataFrame()


@_safe
def house_price_index(countries: Iterable[str] = ("united_states",),
                      start: Optional[str] = None) -> pd.DataFrame:
    """House price index by country via FRED."""
    hpi = {
        "united_states":  "CSUSHPISA",
        "united_kingdom": "QGBR628BIS",
        "germany":        "QDEN628BIS",
        "japan":          "QJPN628BIS",
        "france":         "QFRN628BIS",
    }
    start_dt = (pd.to_datetime(start) if start
                else datetime.today() - timedelta(days=5 * 365))
    series = {}
    for c in countries:
        sid = hpi.get(c)
        if not sid:
            continue
        s = _fred_series(sid, start=start_dt)
        if not s.empty:
            series[c] = s
    return _series_to_long(series, COUNTRY_LABEL)


@_safe
def share_price_index(countries: Iterable[str] = ("united_states",
                                                    "euro_area"),
                      start: Optional[str] = None) -> pd.DataFrame:
    """Share price index via FRED (US only — others need direct sources)."""
    sp = {"united_states": "SP500"}
    start_dt = (pd.to_datetime(start) if start
                else datetime.today() - timedelta(days=5 * 365))
    series = {}
    for c in countries:
        sid = sp.get(c)
        if not sid:
            continue
        s = _fred_series(sid, start=start_dt)
        if not s.empty:
            series[c] = s
    return _series_to_long(series, COUNTRY_LABEL)


# ── Health check ─────────────────────────────────────────────────────────

def ping() -> dict:
    """Confirm FRED is reachable. Replaces the previous OpenBB ping."""
    try:
        s = _fred_series("DGS10",
                          start=datetime.today() - timedelta(days=30))
        return {
            "ok":           not s.empty,
            "fred_latest":  s.index.max().strftime("%Y-%m-%d") if not s.empty else None,
            "source":       "FRED via pandas_datareader (no key required)",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
