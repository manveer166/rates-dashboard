"""Compute yield curve spreads and swap spreads."""

import pandas as pd

from config import SPREAD_DEFINITIONS


def compute_spreads(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all spread series defined in config.SPREAD_DEFINITIONS.

    Parameters
    ----------
    df : Master DataFrame from DataPipeline

    Returns
    -------
    DataFrame with one column per spread (in basis points where both
    inputs are in % – the difference is already in pct points, so we
    optionally multiply by 100 if you prefer bps). We keep as pct points
    (i.e. 10Y - 2Y in percentage points) to match Bloomberg convention.
    """
    spreads = pd.DataFrame(index=df.index)

    for name, (col_a, col_b) in SPREAD_DEFINITIONS.items():
        if col_a in df.columns and col_b in df.columns:
            spreads[name] = df[col_a] - df[col_b]

    return spreads.dropna(how="all")


def compute_zscore(series: pd.Series, window: int = 252) -> pd.Series:
    """Rolling z-score of a spread series (252 trading-day window = 1 year)."""
    roll_mean = series.rolling(window).mean()
    roll_std  = series.rolling(window).std()
    return (series - roll_mean) / roll_std


def spread_summary(spreads: pd.DataFrame) -> pd.DataFrame:
    """
    Return a summary table with current value, 1M/3M/1Y ago, and z-score.
    """
    rows = []
    for col in spreads.columns:
        s = spreads[col].dropna()
        if s.empty:
            continue
        current = s.iloc[-1]
        rows.append({
            "Spread": col,
            "Current (pp)": round(current, 3),
            "1M Ago":       round(s.iloc[-22], 3) if len(s) > 22  else None,
            "3M Ago":       round(s.iloc[-63], 3) if len(s) > 63  else None,
            "1Y Ago":       round(s.iloc[-252], 3) if len(s) > 252 else None,
            "52W High":     round(s.tail(252).max(), 3),
            "52W Low":      round(s.tail(252).min(), 3),
            "Z-Score (1Y)": round(compute_zscore(s).iloc[-1], 2) if len(s) >= 252 else None,
        })
    return pd.DataFrame(rows).set_index("Spread")
