"""
mean_reversion.py — Ornstein-Uhlenbeck fits for rates RV trades.

Replaces the previous 50% / half-period heuristic ("assume half the
dislocation reverts over the holding horizon") with empirically-fit
half-lives.

Model
-----
We assume each rates series (an outright yield, a DV01-weighted curve
spread, or a fly) follows an Ornstein-Uhlenbeck process:

    dX_t = θ (μ − X_t) dt + σ dW_t

This is the simplest mean-reverting continuous-time model with three
intuitive parameters:
    μ        long-run mean the series is pulled towards
    θ > 0    speed of mean reversion (higher = pulled back faster)
    σ        diffusion volatility

In discrete time, the same model is an AR(1):

    X_t = c + b · X_{t-1} + ε_t,     b = e^{-θ Δt},    c = μ (1 − b)

We fit by OLS on `X_t` regressed on `X_{t-1}`. Standard manoeuvres:

    half_life  = ln(2) / θ                        (in same units as Δt)
    fitted_μ   = c / (1 − b)
    E[X_h | X_0] = μ + (X_0 − μ) · e^{-θ h}
    E[ΔX over h] = (μ − X_0) · (1 − e^{-θ h})

Half-life is the workhorse. A 30-day half-life means a 100-bp
dislocation is expected to halve to 50 bps in 30 days, regardless of
the absolute level. A 250-day half-life means the same dislocation
would take a year to halve — much less useful for monthly-holding RV.

Caveats / limitations
---------------------
  • Assumes constant μ and θ. In reality both shift across regimes —
    a flat curve in a hiking cycle has different mean and decay than
    in a cutting cycle. The Regime page is the right place to look at
    regime-conditional behaviour.
  • Sample window matters: too short and the fit is unstable; too long
    and the assumed-constant-μ approximation breaks down. We default
    to 252 days (1Y) which matches the dashboard's standard Z window.
  • For series with a trend (e.g. yields rising secularly), the OLS
    fit will absorb the trend into μ. Use the half-life to judge
    plausibility — a half-life of >300 days probably means there's no
    real mean reversion in the sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class OUFit:
    """Result of a one-shot OU/AR(1) fit on a time series."""

    half_life_days: float       # Days to halve a dislocation. inf if no reversion.
    long_run_mean: float        # Implied μ (in the units of the input series).
    theta_annual: float         # Reversion speed per year (252 trading days).
    current: float              # Latest observation (X_0).
    dislocation: float          # X_0 − μ. Positive = trade is too high.
    expected_move_h: float      # E[ΔX over horizon h] = (μ − X_0)(1 − e^{−θh}).
    horizon_days: int           # Horizon used for expected_move_h.
    r_squared: float            # AR(1) regression R² — sanity check on the fit.
    n_obs: int                  # Number of observations the fit used.
    valid: bool                 # False if data was insufficient or the fit
                                # implies non-stationary (b ≥ 1 or b ≤ 0).


def fit_ou(series: pd.Series,
           window_days: int = 252,
           horizon_days: int = 21) -> OUFit:
    """Fit an OU process to the tail of `series` and report fit + forecast.

    series:       any indexed numeric series (yields, spreads, flies)
    window_days:  use the last N observations for the fit (default 252)
    horizon_days: forecast horizon for expected_move_h (default 21 = ~1M)

    Returns an OUFit with sensible fallbacks if data is too sparse or the
    fit comes back non-mean-reverting.
    """
    s = pd.Series(series, copy=False).dropna()
    if len(s) < 30:
        return _empty_fit(float(s.iloc[-1]) if len(s) else float("nan"),
                          horizon_days)
    s = s.iloc[-window_days:]

    x_prev = s.iloc[:-1].values
    x_curr = s.iloc[1:].values
    n = len(x_prev)
    if n < 20 or float(np.std(x_prev)) <= 0:
        return _empty_fit(float(s.iloc[-1]), horizon_days)

    # OLS: x_curr = c + b * x_prev + ε
    mean_prev = float(np.mean(x_prev))
    mean_curr = float(np.mean(x_curr))
    cov_xy = float(np.mean((x_prev - mean_prev) * (x_curr - mean_curr)))
    var_x  = float(np.mean((x_prev - mean_prev) ** 2))
    if var_x <= 0:
        return _empty_fit(float(s.iloc[-1]), horizon_days)
    b = cov_xy / var_x
    c = mean_curr - b * mean_prev

    # Diagnostics
    residuals = x_curr - (c + b * x_prev)
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((x_curr - mean_curr) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Convert to OU parameters. b must be in (0, 1) for a stationary
    # mean-reverting process. b ≤ 0 → oscillatory (not the model we want),
    # b ≥ 1 → non-stationary (random walk or worse).
    if not (0.0 < b < 1.0):
        return OUFit(
            half_life_days=float("inf"),
            long_run_mean=float(mean_prev),
            theta_annual=0.0,
            current=float(s.iloc[-1]),
            dislocation=float(s.iloc[-1] - mean_prev),
            expected_move_h=0.0,
            horizon_days=horizon_days,
            r_squared=r2,
            n_obs=n,
            valid=False,
        )

    theta_daily = -np.log(b)               # θ * Δt with Δt = 1 day
    half_life = float(np.log(2.0) / theta_daily)
    mu = float(c / (1.0 - b))
    theta_annual = float(theta_daily * 252.0)
    current = float(s.iloc[-1])
    expected_move = float((mu - current) * (1.0 - b ** horizon_days))

    return OUFit(
        half_life_days=half_life,
        long_run_mean=mu,
        theta_annual=theta_annual,
        current=current,
        dislocation=float(current - mu),
        expected_move_h=expected_move,
        horizon_days=horizon_days,
        r_squared=r2,
        n_obs=n,
        valid=True,
    )


def _empty_fit(current: float, horizon_days: int) -> OUFit:
    return OUFit(
        half_life_days=float("inf"),
        long_run_mean=current,
        theta_annual=0.0,
        current=current,
        dislocation=0.0,
        expected_move_h=0.0,
        horizon_days=horizon_days,
        r_squared=0.0,
        n_obs=0,
        valid=False,
    )


# ---------------------------------------------------------------------------
# Convenience: turn an OU fit into a single "expected bps move" suitable for
# adding to a Scanner E[Ret] column. Sign-aware for receive trades.
# ---------------------------------------------------------------------------

def mean_reversion_bps(series: pd.Series,
                        is_receive: bool = True,
                        window_days: int = 252,
                        horizon_days: int = 21) -> float:
    """Expected mean-reversion P&L over `horizon_days`, in bps yield-equiv.

    For an OUTRIGHT receive of a yield:
        if z > 0 (yield rich), expected move down → +P&L for receiver
        if z < 0 (yield cheap), expected move up   → -P&L for receiver
    The math handles the sign for you: `expected_move_h` is in the same
    units as the series, so for yields (in %) we multiply by 100 to get
    bps; for a series that's already in bps, pass the right scale.

    The returned bps is sign-flipped for `is_receive=True` because a
    drop in yield (negative expected_move) is profit for a receiver.
    """
    fit = fit_ou(series, window_days=window_days, horizon_days=horizon_days)
    if not fit.valid:
        return 0.0
    # series may be in % (yields) or in bps-equivalents (spreads). The caller
    # is expected to use a series whose unit matches what they want back —
    # for the scanner we use the yield series in % so expected_move is in
    # % and we convert to bps via *100.
    bps = fit.expected_move_h * 100.0
    return -bps if is_receive else bps
