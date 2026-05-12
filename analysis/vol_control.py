"""
vol_control.py — Institutional vol-control fund flow engine.

Methodology
-----------
Vol-control funds target a fixed portfolio volatility.  When realised vol
rises they de-risk (sell); when vol falls they re-risk (buy).

Core mechanics
~~~~~~~~~~~~~~
  vol_used   = max(EWMA_30d, EWMA_90d)          # conservative estimate
  exposure   = (target_vol / vol_used).clip(0, max_lev)
  equity_AUM = exposure × total_AUM
  daily_flow = Δ(equity_AUM)

EWMA formulation (RiskMetrics, 1994)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  var_t = (1 − λ) · r_t² + λ · var_{t-1}

implemented via:  pd.Series.ewm(alpha=1−λ, adjust=False).mean()

This is the ONLY correct formulation.  The normalised-window approach
(w /= w.sum()) is a WMA approximation — it changes the effective λ and
breaks the forward-projection convergence property.

Forward projection
~~~~~~~~~~~~~~~~~~
Given the EWMA variance state at time T, each future period follows:

  var_{T+k} = (1 − λ) · σ_fwd²/252 + λ · var_{T+k-1}

Vol does NOT jump instantly to σ_fwd.  It converges exponentially with
half-life ≈ −log(2) / log(λ) days:
  λ = 0.94 → half-life ≈ 11 days
  λ = 0.97 → half-life ≈ 23 days

Data sources
~~~~~~~~~~~~
yfinance equity indices as futures proxies.
Limitation: cash vs. futures basis (~0.1% US, larger Asia).
For production: replace with CME/Eurex futures via Bloomberg/Databento.
VIX overlay available for implied-vol cross-check.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

# ── Constants ─────────────────────────────────────────────────────────────────

TDPY        = 252          # trading days per year
MAX_LEV     = 1.5          # max exposure multiplier
MIN_HIST    = 252          # minimum trading-day history required
DATA_START  = "2012-01-01" # fetch from here for enough EWMA warm-up

# Market universe  {display_name: (yfinance_ticker, AUM_weight)}
# Weights reflect approximate institutional allocation (sums to 1)
MARKETS: Dict[str, Tuple[str, float]] = {
    "S&P 500 E-mini":     ("^GSPC",     0.28),
    "Nasdaq 100 E-mini":  ("^NDX",      0.11),
    "Russell 2000":       ("^RUT",      0.05),
    "Euro Stoxx 50":      ("^STOXX50E", 0.07),
    "DAX 30":             ("^GDAXI",    0.07),
    "FTSE 100":           ("^FTSE",     0.05),
    "TOPIX / Nikkei":     ("^N225",     0.05),
    "Hang Seng":          ("^HSI",      0.04),
    "SPI 200":            ("^AXJO",     0.04),
    "CAC 40":             ("^FCHI",     0.04),
    "Kospi 200":          ("^KS11",     0.03),
}


# ── Core EWMA functions ───────────────────────────────────────────────────────

def ewma_variance_series(returns: pd.Series, lam: float) -> pd.Series:
    """
    Recursive EWMA variance:  var_t = (1−λ)·r_t² + λ·var_{t-1}

    pandas ewm(alpha=α, adjust=False) implements:
        y_t = α·x_t + (1−α)·y_{t-1}
    Setting α = 1−λ gives the RiskMetrics formula exactly.
    """
    alpha = 1.0 - lam
    return (returns ** 2).ewm(alpha=alpha, adjust=False).mean()


def ewma_vol_series(returns: pd.Series, lam: float) -> pd.Series:
    """Annualised EWMA vol (decimal). e.g. 0.15 = 15%."""
    return np.sqrt(ewma_variance_series(returns, lam) * TDPY)


def vol_used_series(vol_30: pd.Series, vol_90: pd.Series) -> pd.Series:
    """
    Conservative realised vol = max(30d EWMA, 90d EWMA).

    The max ensures that a recent spike (captured by the fast 30d window)
    is not diluted by the slower 90d window — forcing de-risking even when
    the long-run window looks calm.
    """
    return pd.concat([vol_30, vol_90], axis=1).max(axis=1)


def exposure_series(vol: pd.Series, target_vol: float,
                    max_lev: float = MAX_LEV) -> pd.Series:
    """Fractional equity allocation = target_vol / vol_used, capped."""
    safe_vol = vol.replace(0, np.nan).ffill()
    return (target_vol / safe_vol).clip(upper=max_lev).fillna(0)


# ── Forward projection ────────────────────────────────────────────────────────

def project_ewma_state(
    last_var: float,
    forward_annual_vol: float,
    lam: float,
    periods: int,
) -> np.ndarray:
    """
    Propagate the EWMA variance state forward under a constant vol assumption.

    Returns an array of annualised vols of length `periods`.

    The key property: convergence is GRADUAL, not instant.
    A high-vol spike embedded in the EWMA state decays at rate λ per day.
    """
    fwd_daily_var = (forward_annual_vol / np.sqrt(TDPY)) ** 2
    out = np.empty(periods)
    var = last_var
    for i in range(periods):
        var = (1.0 - lam) * fwd_daily_var + lam * var
        out[i] = var
    return np.sqrt(out * TDPY)            # annualised vol array


def build_forward_flows(
    prices: pd.Series,
    total_aum: float,
    mkt_weight: float,
    target_vol: float,
    lambda_30: float,
    lambda_90: float,
    forward_vols: Sequence[float],
    periods_fwd: int,
) -> pd.DataFrame:
    """
    Build daily and cumulative forward flow projections for one market.

    Returns a DataFrame indexed by future business-day dates with columns:
        Daily Flow (XX%)     — $bn per day
        Cumulative Flow (XX%) — $bn cumulative

    Each forward_vol scenario produces its own pair of columns.
    """
    if len(prices) < MIN_HIST:
        return pd.DataFrame()

    returns   = np.log(prices / prices.shift(1)).dropna()
    var30_ser = ewma_variance_series(returns, lambda_30)
    var90_ser = ewma_variance_series(returns, lambda_90)
    v30_hist  = np.sqrt(var30_ser * TDPY)
    v90_hist  = np.sqrt(var90_ser * TDPY)
    vol_hist  = vol_used_series(v30_hist, v90_hist)
    exp_hist  = exposure_series(vol_hist, target_vol)

    last_var30 = float(var30_ser.iloc[-1])
    last_var90 = float(var90_ser.iloc[-1])
    last_exp   = float(exp_hist.iloc[-1])
    mkt_aum    = total_aum * mkt_weight

    future_dates = pd.date_range(
        prices.index[-1] + pd.Timedelta(days=1),
        periods=periods_fwd,
        freq="B",
    )

    frames = []
    for fv in forward_vols:
        fwd_v30  = project_ewma_state(last_var30, fv, lambda_30, periods_fwd)
        fwd_v90  = project_ewma_state(last_var90, fv, lambda_90, periods_fwd)
        fwd_vu   = np.maximum(fwd_v30, fwd_v90)
        fwd_exp  = np.clip(
            np.where(fwd_vu > 0, target_vol / fwd_vu, 0.0),
            0.0, MAX_LEV,
        )
        # Daily change in AUM allocation → flow
        all_exp     = np.concatenate([[last_exp], fwd_exp])
        daily_flow  = np.diff(all_exp) * mkt_aum / 1e9   # $bn

        label = f"{fv:.0%}"
        frames.append(pd.DataFrame({
            f"Daily Flow ({label})":      daily_flow,
            f"Cumulative Flow ({label})": np.cumsum(daily_flow),
        }, index=future_dates))

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1)


# ── Multi-market scenario flows table ─────────────────────────────────────────

def _current_exposure(
    prices: pd.Series,
    target_vol: float,
    lambda_30: float,
    lambda_90: float,
) -> float:
    """Compute current vol-control exposure fraction for one market."""
    r   = np.log(prices / prices.shift(1)).dropna()
    v30 = float(ewma_vol_series(r, lambda_30).iloc[-1])
    v90 = float(ewma_vol_series(r, lambda_90).iloc[-1])
    vu  = max(v30, v90)
    return min(target_vol / vu if vu > 0 else 0.0, MAX_LEV)


def build_flows_table(
    mkt_prices: Dict[str, Optional[pd.Series]],
    mkt_weights: Dict[str, float],
    total_aum: float,
    target_vol: float,
    lambda_30: float,
    lambda_90: float,
) -> pd.DataFrame:
    """
    Build the scenario flows table for all markets ($MM).

    Columns
    -------
    Flat           : 5-day flat market (vol slowly decays → re-risk)
    Up +2σ         : 5-day +2σ shock  (vol rises  → de-risk)
    Down -2.5σ     : 5-day −2.5σ shock (vol spikes → heavy de-risk)
    Last Week      : realised change over last 5 trading days
    Last Month     : realised change over last 21 trading days

    Calculation
    -----------
    For each scenario, we extend the price path by 5 business days using
    the implied daily return (z × daily_σ), recompute EWMA vols, then:
        flow_$MM = (new_exposure − cur_exposure) × mkt_AUM_$MM
    """
    rows = []

    for mkt, prices in mkt_prices.items():
        w       = mkt_weights.get(mkt, 0.0)
        aum_mm  = total_aum * w / 1e6             # $ × weight → $MM  (total_aum is in $)

        if prices is None or len(prices) < MIN_HIST:
            rows.append({
                "Market": mkt,
                "Flat": 0, "Up +2σ": 0, "Down -2.5σ": 0,
                "Last Week": 0, "Last Month": 0,
            })
            continue

        r         = np.log(prices / prices.shift(1)).dropna()
        cur_exp   = _current_exposure(prices, target_vol, lambda_30, lambda_90)
        daily_sig = float(ewma_vol_series(r, lambda_30).iloc[-1]) / np.sqrt(TDPY)

        fwd_days = 5
        pi = pd.date_range(
            prices.index[-1] + pd.Timedelta(days=1),
            periods=fwd_days, freq="B",
        )

        def _scenario_flow(z: float) -> int:
            fwd_r  = np.full(fwd_days, z * daily_sig)
            fwd_p  = prices.iloc[-1] * np.exp(np.cumsum(fwd_r))
            ext    = pd.concat([prices, pd.Series(fwd_p, index=pi)])
            ne     = _current_exposure(ext, target_vol, lambda_30, lambda_90)
            return int(round((ne - cur_exp) * aum_mm))

        def _hist_flow(lb: int) -> int:
            if len(prices) < lb + MIN_HIST // 2:
                return 0
            old = _current_exposure(
                prices.iloc[:-lb], target_vol, lambda_30, lambda_90
            )
            return int(round((cur_exp - old) * aum_mm))

        rows.append({
            "Market":      mkt,
            "Flat":        _scenario_flow(0.0),
            "Up +2σ":      _scenario_flow(+2.0),
            "Down -2.5σ":  _scenario_flow(-2.5),
            "Last Week":   _hist_flow(5),
            "Last Month":  _hist_flow(21),
        })

    df = pd.DataFrame(rows).set_index("Market")
    # Totals row
    tot      = df.sum(numeric_only=True)
    tot.name = "Totals"
    return pd.concat([df, tot.to_frame().T])


# ── Data loader (cached outside Streamlit context) ────────────────────────────

def load_market_prices(
    markets: Dict[str, Tuple[str, float]] = MARKETS,
    start: str = DATA_START,
) -> Dict[str, Optional[pd.Series]]:
    """
    Fetch daily close prices for all markets from Yahoo Finance.

    Returns dict {market_name: pd.Series | None}.
    None if data unavailable or too short.
    """
    out: Dict[str, Optional[pd.Series]] = {}
    for name, (ticker, _) in markets.items():
        try:
            raw = yf.download(ticker, start=start, auto_adjust=True,
                              progress=False)
            if raw is None or raw.empty:
                out[name] = None
                continue
            s = raw["Close"].squeeze().dropna()
            s.index = pd.to_datetime(s.index.date)
            out[name] = s if len(s) >= MIN_HIST else None
        except Exception:
            out[name] = None
    return out


def load_sp500(start: str = DATA_START) -> pd.Series:
    """Convenience loader — returns S&P 500 close price series."""
    raw = yf.download("^GSPC", start=start, auto_adjust=True,
                      progress=False)
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    s = raw["Close"].squeeze().dropna()
    s.index = pd.to_datetime(s.index.date)
    return s
