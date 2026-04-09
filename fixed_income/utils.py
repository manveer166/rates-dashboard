"""
utils.py — Core statistical utilities for fixed income analysis.

Z-score: (X - mean) / sigma over a rolling window.
Used across all trade types (swaps, bonds, spreads, flies) to identify
how rich/cheap an instrument is relative to its own history.
"""

import numpy as np
import pandas as pd
from typing import Union, Optional, List, Tuple


# ---------------------------------------------------------------------------
# Z-score helpers
# ---------------------------------------------------------------------------

def zscore(series: pd.Series, window: int = 252) -> pd.Series:
    """
    Rolling z-score: (X - rolling_mean) / rolling_std.

    Parameters
    ----------
    series : pd.Series  — time series of rates / spreads
    window : int        — lookback in business days (default 252 = 1 year)

    Returns
    -------
    pd.Series of z-scores (NaN for first <window> observations)
    """
    mu = series.rolling(window, min_periods=int(window * 0.8)).mean()
    sigma = series.rolling(window, min_periods=int(window * 0.8)).std()
    return (series - mu) / sigma


def zscore_current(series: pd.Series, window: int = 252) -> float:
    """Return the most recent z-score value."""
    return float(zscore(series, window).iloc[-1])


def percentile_rank(series: pd.Series, window: int = 252) -> pd.Series:
    """
    Rolling percentile rank (0–100).
    Answers: "what % of past observations was this level below?"
    """
    def _rank(x):
        return float(np.sum(x < x[-1])) / len(x) * 100.0

    return series.rolling(window, min_periods=int(window * 0.8)).apply(_rank, raw=True)


# ---------------------------------------------------------------------------
# Rolling window statistics
# ---------------------------------------------------------------------------

def rolling_mean(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=int(window * 0.5)).mean()


def rolling_std(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=int(window * 0.5)).std()


def realized_std(series: pd.Series, window: int) -> float:
    """Realized standard deviation over last <window> observations."""
    tail = series.dropna().tail(window)
    return float(tail.std())


def realized_std_last_period(series: pd.Series, window: int) -> float:
    """
    Std dev of the period BEFORE the last <window> observations.
    Used in wedge analysis to compare current vs prior vol regime.
    """
    data = series.dropna()
    period = data.iloc[-(2 * window): -window]
    return float(period.std()) if len(period) > 0 else np.nan


def annualized_vol(series: pd.Series, window: int = 252, freq: int = 252) -> float:
    """Annualized volatility from daily changes."""
    changes = series.diff().dropna().tail(window)
    return float(changes.std() * np.sqrt(freq))


# ---------------------------------------------------------------------------
# Change / delta helpers
# ---------------------------------------------------------------------------

def bps_change(series: pd.Series, periods: int = 1) -> pd.Series:
    """Basis-point change (assumes series is in % or bps)."""
    return series.diff(periods) * 100  # convert pct → bps if needed


def pct_change_ann(series: pd.Series, periods: int = 252) -> pd.Series:
    """Annualised percentage change."""
    return series.pct_change(periods) * 100


# ---------------------------------------------------------------------------
# Date utilities
# ---------------------------------------------------------------------------

def get_date_path_serial_number(date: pd.Timestamp) -> int:
    """
    Serial date number used to index into date-path arrays.
    Counts business days since a reference epoch (2000-01-03).
    """
    ref = pd.Timestamp("2000-01-03")
    bdays = pd.bdate_range(ref, date)
    return len(bdays) - 1


def business_days_between(start: pd.Timestamp, end: pd.Timestamp) -> int:
    """Number of business days between two dates (inclusive of start)."""
    return len(pd.bdate_range(start, end))


def expiry_dates(start_date: pd.Timestamp, periods: int, freq: str = "M") -> List[pd.Timestamp]:
    """
    Generate a list of expiry dates (e.g. monthly IMM dates).
    freq: 'M' = end of month, 'Q' = quarterly, 'W' = weekly
    """
    dates = pd.date_range(start=start_date, periods=periods, freq=freq)
    return [pd.Timestamp(d) for d in dates]


# ---------------------------------------------------------------------------
# Summary statistics for a single series
# ---------------------------------------------------------------------------

def summary_stats(series: pd.Series, windows: Optional[List[int]] = None) -> pd.DataFrame:
    """
    Produce a summary table:
        Current | 1W ago | 1M ago | 3M ago | 6M ago | 1Y ago | Z-score(1Y)

    Parameters
    ----------
    series  : pd.Series with DatetimeIndex
    windows : list of lookback periods in business days; default [5,21,63,126,252]
    """
    if windows is None:
        windows = [5, 21, 63, 126, 252]

    labels = ["1W", "1M", "3M", "6M", "1Y"]
    series = series.dropna()
    current = series.iloc[-1]

    row = {"Current": round(current, 4)}
    for label, w in zip(labels, windows):
        if len(series) > w:
            row[f"{label} ago"] = round(series.iloc[-w - 1], 4)
            row[f"Chg {label}"] = round((current - series.iloc[-w - 1]) * 100, 1)  # bps
        else:
            row[f"{label} ago"] = np.nan
            row[f"Chg {label}"] = np.nan

    row["Z-score (1Y)"] = round(zscore_current(series, 252), 2)
    row["Pctile (1Y)"] = round(float(percentile_rank(series, 252).iloc[-1]), 1)

    return pd.DataFrame([row])


# ---------------------------------------------------------------------------
# Multi-series z-score table (used in the weekly update tables)
# ---------------------------------------------------------------------------

def zscore_table(
    df: pd.DataFrame,
    window: int = 252,
    cols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Compute z-scores for multiple series in a DataFrame.

    Returns a DataFrame with columns = series names,
    index = ['Current', 'Z-score', 'Pctile', '1M chg', '3M chg', '1Y chg']
    """
    if cols is None:
        cols = list(df.columns)

    records = {}
    for col in cols:
        s = df[col].dropna()
        if len(s) < 10:
            continue
        curr = s.iloc[-1]
        z = zscore_current(s, window)
        pct = float(percentile_rank(s, window).iloc[-1])
        chg_1m = (curr - s.iloc[-22]) * 100 if len(s) > 22 else np.nan
        chg_3m = (curr - s.iloc[-63]) * 100 if len(s) > 63 else np.nan
        chg_1y = (curr - s.iloc[-252]) * 100 if len(s) > 252 else np.nan
        records[col] = {
            "Current": round(curr, 4),
            "Z-score": round(z, 2),
            "Pctile": round(pct, 1),
            "1M chg (bps)": round(chg_1m, 1),
            "3M chg (bps)": round(chg_3m, 1),
            "1Y chg (bps)": round(chg_1y, 1),
        }

    return pd.DataFrame(records).T


# ---------------------------------------------------------------------------
# Correlation utilities
# ---------------------------------------------------------------------------

def rolling_correlation(
    x: pd.Series,
    y: pd.Series,
    window: int = 252,
) -> pd.Series:
    """Rolling Pearson correlation between two series."""
    return x.rolling(window).corr(y)


def correlation_matrix(df: pd.DataFrame, method: str = "pearson") -> pd.DataFrame:
    """Full correlation matrix across columns."""
    return df.corr(method=method)


def top_correlated_pairs(
    df: pd.DataFrame,
    n: int = 10,
    method: str = "pearson",
) -> pd.DataFrame:
    """Return top-N most correlated (abs) pairs as a tidy DataFrame."""
    corr = correlation_matrix(df, method)
    pairs = (
        corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
        .stack()
        .reset_index()
    )
    pairs.columns = ["Series A", "Series B", "Correlation"]
    pairs["Abs Corr"] = pairs["Correlation"].abs()
    return pairs.sort_values("Abs Corr", ascending=False).head(n).drop(columns="Abs Corr")
