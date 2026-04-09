"""
wedges.py — Wedge trade analytics for interest rate markets.

What is a wedge?
----------------
A wedge is a trade that monetises the difference between:
  (a) the IMPLIED move priced into the forward curve, and
  (b) the REALISED move that actually occurs.

In swap markets a "wedge" typically refers to:

  Wedge = (Forward Swap Rate at horizon) − (Current Par Swap Rate)
        ≈ carry + rolldown over the period

If a market prices in a large forward move but you expect the curve to
be stable, you earn the wedge by staying in the position.

The key risk measure is:
  Wedge / (Annualised Vol × sqrt(T))  — i.e. a Sharpe-like ratio

A high absolute wedge relative to vol = attractive trade.

Wedge buckets
-------------
The Barclays code ran wedge analysis across a grid of:
  Buckets: 1Y, 2Y, 3Y, 4Y, 5Y, 7Y, 10Y, 15Y, 20Y, 30Y (forward start)
  Tails:   1Y, 2Y, 3Y, 5Y, 10Y (swap maturity after forward start)

This produces an N×M grid of wedge values, sorted to find the best
carry-adjusted trades.
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Dict, Tuple
from .utils import zscore, percentile_rank, realized_std, realized_std_last_period
from .carry_rolldown import interpolate_rate


# ---------------------------------------------------------------------------
# Forward swap rate calculation
# ---------------------------------------------------------------------------

def forward_swap_rate(
    curve_tenors: List[float],
    curve_rates: List[float],
    forward_start: float,
    tail_tenor: float,
) -> float:
    """
    Compute the par forward swap rate for a swap starting at `forward_start`
    years with tenor `tail_tenor` years.

    Uses the approximation:
      forward_rate(s, T) ≈ [ r(s+T)×(s+T) - r(s)×s ] / T
    (interpolated from the par swap curve — valid for flat or near-flat curves)

    Parameters
    ----------
    curve_tenors  : list of benchmark tenor years
    curve_rates   : corresponding par swap rates in %
    forward_start : start of forward period in years (e.g. 1.0 for 1Y1Y)
    tail_tenor    : length of the forward swap in years (e.g. 1.0 for 1Y1Y)

    Returns forward swap rate in %.
    """
    end = forward_start + tail_tenor
    rate_end = interpolate_rate(curve_tenors, curve_rates, end)
    rate_start = interpolate_rate(curve_tenors, curve_rates, forward_start)
    if tail_tenor == 0:
        return rate_end
    fwd = (rate_end * end - rate_start * forward_start) / tail_tenor
    return round(fwd, 6)


def wedge(
    curve_tenors: List[float],
    curve_rates: List[float],
    forward_start: float,
    tail_tenor: float,
    spot_swap_rate: Optional[float] = None,
) -> float:
    """
    Wedge = forward_swap_rate - spot_swap_rate (for the same tail_tenor).

    If spot_swap_rate not provided it is interpolated from the curve.

    Returns wedge in bps.
    """
    fwd = forward_swap_rate(curve_tenors, curve_rates, forward_start, tail_tenor)
    if spot_swap_rate is None:
        spot_swap_rate = interpolate_rate(curve_tenors, curve_rates, tail_tenor)
    return (fwd - spot_swap_rate) * 100  # bps


# ---------------------------------------------------------------------------
# Wedge grid
# ---------------------------------------------------------------------------

FORWARD_STARTS = [1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0]   # years
TAIL_TENORS    = [1.0, 2.0, 3.0, 5.0, 10.0]               # years

FORWARD_LABELS = ["1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y"]
TAIL_LABELS    = ["1Y", "2Y", "3Y", "5Y", "10Y"]


def wedge_grid(
    curve_tenors: List[float],
    curve_rates: List[float],
    forward_starts: Optional[List[float]] = None,
    tail_tenors: Optional[List[float]] = None,
) -> pd.DataFrame:
    """
    Build a full wedge grid: rows = forward start, columns = tail tenor.

    Returns DataFrame of wedge values in bps.
    """
    if forward_starts is None:
        forward_starts = FORWARD_STARTS
    if tail_tenors is None:
        tail_tenors = TAIL_TENORS

    rows = {}
    for fs in forward_starts:
        row_label = f"{int(fs)}Y" if fs == int(fs) else f"{fs}Y"
        rows[row_label] = {}
        for tt in tail_tenors:
            col_label = f"{int(tt)}Y" if tt == int(tt) else f"{tt}Y"
            try:
                w = wedge(curve_tenors, curve_rates, fs, tt)
            except Exception:
                w = np.nan
            rows[row_label][col_label] = round(w, 2)

    return pd.DataFrame(rows).T  # rows=forward_start, cols=tail


# ---------------------------------------------------------------------------
# Wedge with vol adjustment (wedge / vol = risk-adjusted carry)
# ---------------------------------------------------------------------------

def vol_adjusted_wedge(
    wedge_bps: float,
    rate_series: pd.Series,
    forward_start_years: float,
    vol_window: int = 63,
) -> float:
    """
    Sharpe-like wedge metric = wedge / (vol × sqrt(T)).

    Annualised volatility is computed over `vol_window` days of daily changes.
    T = forward_start_years (the horizon over which the wedge is earned).

    A value > 1.0 means the wedge compensates more than 1 standard deviation.
    """
    changes = rate_series.diff().dropna().tail(vol_window)
    daily_vol = float(changes.std())
    ann_vol = daily_vol * np.sqrt(252) * 100  # bps/year
    horizon_vol = ann_vol * np.sqrt(forward_start_years)
    if horizon_vol <= 0:
        return np.nan
    return round(wedge_bps / horizon_vol, 4)


def wedge_sharpe_grid(
    curve_tenors: List[float],
    curve_rates: List[float],
    rate_df: pd.DataFrame,
    tenor_col_map: Dict[str, str],
    forward_starts: Optional[List[float]] = None,
    tail_tenors: Optional[List[float]] = None,
    vol_window: int = 63,
) -> pd.DataFrame:
    """
    Build a vol-adjusted wedge (Sharpe) grid.

    Parameters
    ----------
    curve_tenors  : list of curve tenor years
    curve_rates   : corresponding rates in %
    rate_df       : DataFrame of rate history (for vol calculation)
    tenor_col_map : dict mapping tail tenor (str) → column in rate_df
                    e.g. {'1Y': 'DGS1', '5Y': 'DGS5', '10Y': 'DGS10'}
    """
    if forward_starts is None:
        forward_starts = FORWARD_STARTS
    if tail_tenors is None:
        tail_tenors = TAIL_TENORS

    rows = {}
    for fs in forward_starts:
        row_label = f"{int(fs)}Y" if fs == int(fs) else f"{fs}Y"
        rows[row_label] = {}
        for tt in tail_tenors:
            col_label = f"{int(tt)}Y" if tt == int(tt) else f"{tt}Y"
            try:
                w = wedge(curve_tenors, curve_rates, fs, tt)
                # Use the tail-tenor series for vol
                tail_label = col_label
                if tail_label in tenor_col_map:
                    series = rate_df[tenor_col_map[tail_label]].dropna()
                    sharpe = vol_adjusted_wedge(w, series, fs, vol_window)
                else:
                    sharpe = np.nan
            except Exception:
                sharpe = np.nan
            rows[row_label][col_label] = sharpe

    return pd.DataFrame(rows).T


# ---------------------------------------------------------------------------
# Wedge change: how the wedge has evolved
# ---------------------------------------------------------------------------

def wedge_history(
    curve_df: pd.DataFrame,
    tenor_col_map: Dict[str, str],
    forward_start: float,
    tail_tenor: float,
) -> pd.Series:
    """
    Compute the time series of a specific forward wedge.

    Parameters
    ----------
    curve_df      : DataFrame with tenor columns and DatetimeIndex
    tenor_col_map : dict {tenor_label → column_name} to build the curve
    forward_start : forward start in years
    tail_tenor    : tail tenor in years

    Returns pd.Series of wedge values in bps over time.
    """
    tenors = sorted([(float(k.replace("Y", "")), v)
                     for k, v in tenor_col_map.items()
                     if k.endswith("Y")],
                    key=lambda x: x[0])
    t_list = [t[0] for t in tenors]
    col_list = [t[1] for t in tenors]

    wedges = []
    dates = []
    for date, row in curve_df.iterrows():
        r_list = [row.get(c, np.nan) for c in col_list]
        if any(pd.isna(r) for r in r_list):
            continue
        try:
            w = wedge(t_list, r_list, forward_start, tail_tenor)
            wedges.append(w)
            dates.append(date)
        except Exception:
            continue

    s = pd.Series(wedges, index=pd.to_datetime(dates))
    s.name = f"{int(forward_start)}Y{int(tail_tenor)}Y wedge (bps)"
    return s


# ---------------------------------------------------------------------------
# Full wedge analysis: rank top trades
# ---------------------------------------------------------------------------

def run_wedge_analysis(
    curve_tenors: List[float],
    curve_rates: List[float],
    rate_df: pd.DataFrame,
    tenor_col_map: Dict[str, str],
    vol_window: int = 63,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    Run full wedge analysis and return ranked trade opportunities.

    Sorts by absolute vol-adjusted wedge (Sharpe) to find best risk-adjusted
    carry trades on the forward curve.

    Returns DataFrame with columns:
        Forward Start | Tail Tenor | Wedge (bps) | Vol (bps/yr) | Sharpe | Z-score
    """
    rows = []
    for fs in FORWARD_STARTS:
        for tt in TAIL_TENORS:
            try:
                w = wedge(curve_tenors, curve_rates, fs, tt)
                fs_label = f"{int(fs)}Y"
                tt_label = f"{int(tt)}Y"
                tail_col = tenor_col_map.get(tt_label)
                if tail_col and tail_col in rate_df.columns:
                    series = rate_df[tail_col].dropna()
                    changes = series.diff().dropna().tail(vol_window)
                    ann_vol = float(changes.std() * np.sqrt(252) * 100)
                    horizon_vol = ann_vol * np.sqrt(fs)
                    sharpe = w / horizon_vol if horizon_vol > 0 else np.nan
                    # Historical wedge history for z-score
                    w_hist = wedge_history(rate_df, tenor_col_map, fs, tt)
                    z = float(zscore(w_hist, 252).iloc[-1]) if len(w_hist) > 252 else np.nan
                else:
                    ann_vol = np.nan
                    sharpe = np.nan
                    z = np.nan

                rows.append({
                    "Forward Start": f"{fs_label}",
                    "Tail Tenor": f"{tt_label}",
                    "Instrument": f"{fs_label}{tt_label}",
                    "Wedge (bps)": round(w, 2),
                    "Vol (bps/yr)": round(ann_vol, 1) if not np.isnan(ann_vol) else np.nan,
                    "Sharpe": round(sharpe, 3) if not np.isnan(sharpe) else np.nan,
                    "Z-score (1Y)": round(z, 2) if not np.isnan(z) else np.nan,
                })
            except Exception:
                continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["Abs Sharpe"] = df["Sharpe"].abs()
    df = df.sort_values("Abs Sharpe", ascending=False).drop(columns="Abs Sharpe")
    return df.head(top_n).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Vol regime check (from Wedges PDF)
# ---------------------------------------------------------------------------

def vol_regime_check(
    rate_series: pd.Series,
    short_window: int = 21,
    long_window: int = 63,
) -> Dict[str, float]:
    """
    Check if current vol regime is high or low relative to recent history.
    Used as a filter: prefer to buy wedges when vol is cheap.

    Returns dict with current_vol, prior_period_vol, vol_ratio.
    """
    current_vol = realized_std(rate_series.diff().dropna() * 100, short_window)
    prior_vol = realized_std_last_period(rate_series.diff().dropna() * 100, short_window)
    ratio = current_vol / prior_vol if prior_vol > 0 else np.nan

    return {
        "Current Vol (bps)": round(current_vol, 2),
        "Prior Period Vol (bps)": round(prior_vol, 2),
        "Vol Ratio": round(ratio, 3) if not np.isnan(ratio) else np.nan,
        "Regime": "HIGH" if ratio and ratio > 1.2 else ("LOW" if ratio and ratio < 0.8 else "NORMAL"),
    }
