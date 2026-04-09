"""
spread_options.py — Pricing and analysis of spread options on interest rate spreads.

What is a spread option?
------------------------
A spread option gives the right (but not obligation) to receive/pay
the DIFFERENCE between two rates at expiry — e.g. the 2s10s spread.

  Payoff (call) = max(S_T - K, 0)   where S = rate(10Y) - rate(2Y)
  Payoff (put)  = max(K - S_T, 0)

They are used to:
  • Take a view on curve shape without being long/short rates outright
  • Hedge a curve steepener/flattener at a specific level
  • Express relative-value views with defined risk

Pricing approaches used here
-----------------------------
1. Kirk's approximation  — closed-form, fast, good for near-ATM options
2. Monte Carlo simulation — accurate, handles correlation explicitly
3. Bachelier (Normal) model — appropriate for rate spreads (can go negative)

All inputs in basis points (bps), outputs in bps.
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq
from typing import Optional, Tuple, List, Dict
from .utils import zscore, percentile_rank, rolling_std


# ---------------------------------------------------------------------------
# Bachelier (Normal) model — preferred for spread options
# ---------------------------------------------------------------------------

def bachelier_price(
    forward_spread: float,
    strike: float,
    vol_bps_pa: float,
    expiry_years: float,
    option_type: str = "call",
) -> float:
    """
    Bachelier (arithmetic Brownian motion) option price for rate spreads.

    Assumes spread ~ Normal(F, sigma²T) where sigma is in bps/year.

    Parameters
    ----------
    forward_spread : current forward spread in bps
    strike         : strike spread in bps
    vol_bps_pa     : normal volatility in bps/year (annualised)
    expiry_years   : option expiry in years
    option_type    : 'call' (own spread widens) or 'put' (spread tightens)

    Returns option premium in bps.
    """
    sigma_t = vol_bps_pa * np.sqrt(expiry_years)
    if sigma_t <= 0:
        if option_type == "call":
            return max(forward_spread - strike, 0.0)
        else:
            return max(strike - forward_spread, 0.0)

    d = (forward_spread - strike) / sigma_t
    if option_type == "call":
        price = (forward_spread - strike) * norm.cdf(d) + sigma_t * norm.pdf(d)
    else:
        price = (strike - forward_spread) * norm.cdf(-d) + sigma_t * norm.pdf(d)
    return round(price, 4)


def bachelier_implied_vol(
    market_price: float,
    forward_spread: float,
    strike: float,
    expiry_years: float,
    option_type: str = "call",
) -> float:
    """Solve for implied normal vol from a market price using Brent's method."""
    def objective(vol):
        return bachelier_price(forward_spread, strike, vol, expiry_years, option_type) - market_price

    try:
        return float(brentq(objective, 0.01, 5000.0, xtol=1e-6))
    except ValueError:
        return np.nan


def bachelier_greeks(
    forward_spread: float,
    strike: float,
    vol_bps_pa: float,
    expiry_years: float,
    option_type: str = "call",
) -> Dict[str, float]:
    """
    Bachelier option greeks.

    Delta : dPrice/dForwardSpread  (≈ probability of exercise)
    Gamma : d²Price/dF²            (convexity of option value)
    Vega  : dPrice/dVol            (sensitivity to vol)
    Theta : dPrice/dTime           (time decay per day)
    """
    sigma_t = vol_bps_pa * np.sqrt(expiry_years)
    if sigma_t <= 0:
        return {"delta": 1.0 if forward_spread > strike else 0.0,
                "gamma": 0.0, "vega": 0.0, "theta": 0.0}

    d = (forward_spread - strike) / sigma_t

    if option_type == "call":
        delta = norm.cdf(d)
    else:
        delta = norm.cdf(d) - 1.0  # negative for put

    gamma = norm.pdf(d) / sigma_t
    vega = np.sqrt(expiry_years) * norm.pdf(d)       # per 1 bps/year vol move
    # Theta: time decay (dPrice/dT, negative)
    price_now = bachelier_price(forward_spread, strike, vol_bps_pa, expiry_years, option_type)
    dt = 1.0 / 365.0
    if expiry_years > dt:
        price_dt = bachelier_price(forward_spread, strike, vol_bps_pa, expiry_years - dt, option_type)
        theta = price_dt - price_now  # per calendar day (usually negative)
    else:
        theta = 0.0

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "vega": round(vega, 4),
        "theta": round(theta, 4),
    }


# ---------------------------------------------------------------------------
# Kirk's approximation (log-normal, for non-negative spreads)
# ---------------------------------------------------------------------------

def kirks_price(
    F1: float,
    F2: float,
    K: float,
    sigma1: float,
    sigma2: float,
    rho: float,
    T: float,
    option_type: str = "call",
) -> float:
    """
    Kirk's approximation for a spread option on (F1 - F2) vs strike K.
    All values in bps; sigma in fractional (e.g. 0.20 for 20%).

    Spread call: max(F1 - F2 - K, 0)
    More accurate than Bachelier when both rates are strictly positive.
    """
    F2K = F2 + K
    if F2K <= 0:
        return 0.0

    F_ratio = F1 / F2K
    sigma_eff = np.sqrt(
        sigma1 ** 2
        + (sigma2 * F2 / F2K) ** 2
        - 2 * rho * sigma1 * sigma2 * F2 / F2K
    )

    if sigma_eff * np.sqrt(T) <= 0:
        if option_type == "call":
            return max(F1 - F2 - K, 0.0)
        else:
            return max(K + F2 - F1, 0.0)

    d1 = (np.log(F_ratio) + 0.5 * sigma_eff ** 2 * T) / (sigma_eff * np.sqrt(T))
    d2 = d1 - sigma_eff * np.sqrt(T)

    if option_type == "call":
        return F1 * norm.cdf(d1) - F2K * norm.cdf(d2)
    else:
        return F2K * norm.cdf(-d2) - F1 * norm.cdf(-d1)


# ---------------------------------------------------------------------------
# Monte Carlo pricing (with full correlation)
# ---------------------------------------------------------------------------

def mc_spread_option(
    F1: float,
    F2: float,
    K: float,
    sigma1_bps: float,
    sigma2_bps: float,
    rho: float,
    T: float,
    option_type: str = "call",
    n_paths: int = 100_000,
    seed: int = 42,
) -> Dict[str, float]:
    """
    Monte Carlo price for a spread option using the Bachelier (normal) model.

    Models: dS1 = sigma1 * dW1,  dS2 = sigma2 * dW2,  corr(dW1, dW2) = rho

    Parameters
    ----------
    F1, F2         : forward rates in bps
    K              : strike spread in bps
    sigma1_bps     : normal vol of rate1 (bps/year)
    sigma2_bps     : normal vol of rate2 (bps/year)
    rho            : correlation between the two rates
    T              : expiry in years
    n_paths        : number of Monte Carlo paths

    Returns dict with {'price', 'std_error', 'ci_low', 'ci_high'}.
    """
    rng = np.random.default_rng(seed)
    cov = np.array([[sigma1_bps ** 2 * T, rho * sigma1_bps * sigma2_bps * T],
                    [rho * sigma1_bps * sigma2_bps * T, sigma2_bps ** 2 * T]])
    shocks = rng.multivariate_normal([0, 0], cov, n_paths)
    S1_T = F1 + shocks[:, 0]
    S2_T = F2 + shocks[:, 1]
    spread_T = S1_T - S2_T

    if option_type == "call":
        payoffs = np.maximum(spread_T - K, 0.0)
    else:
        payoffs = np.maximum(K - spread_T, 0.0)

    price = float(np.mean(payoffs))
    se = float(np.std(payoffs) / np.sqrt(n_paths))
    return {
        "price": round(price, 4),
        "std_error": round(se, 4),
        "ci_low": round(price - 1.96 * se, 4),
        "ci_high": round(price + 1.96 * se, 4),
    }


# ---------------------------------------------------------------------------
# Expected return on a spread option strategy
# ---------------------------------------------------------------------------

def spread_option_expected_return(
    forward_spread: float,
    strike: float,
    vol_bps_pa: float,
    expiry_years: float,
    premium_paid: float,
    option_type: str = "call",
    n_scenarios: int = 1000,
) -> Dict[str, float]:
    """
    Compute expected return metrics for a bought spread option.

    Scenarios: spread_T ~ N(forward_spread, sigma²T)
    E[P&L] = E[payoff] - premium
    Sharpe = E[P&L] / std(P&L)

    Returns dict with E[PnL], Sharpe, prob_profit, breakeven.
    """
    sigma_t = vol_bps_pa * np.sqrt(expiry_years)
    rng = np.random.default_rng(42)
    spread_t = rng.normal(forward_spread, sigma_t, n_scenarios)

    if option_type == "call":
        payoffs = np.maximum(spread_t - strike, 0.0) - premium_paid
    else:
        payoffs = np.maximum(strike - spread_t, 0.0) - premium_paid

    e_pnl = float(np.mean(payoffs))
    std_pnl = float(np.std(payoffs))
    prob_profit = float(np.mean(payoffs > 0))
    sharpe = e_pnl / std_pnl if std_pnl > 0 else np.nan

    # Intrinsic value at forward
    intrinsic = max(forward_spread - strike, 0.0) if option_type == "call" else max(strike - forward_spread, 0.0)
    breakeven = strike + premium_paid if option_type == "call" else strike - premium_paid

    return {
        "E[P&L] (bps)": round(e_pnl, 2),
        "Std P&L (bps)": round(std_pnl, 2),
        "Sharpe": round(sharpe, 2) if not np.isnan(sharpe) else np.nan,
        "Prob Profit": round(prob_profit, 3),
        "Breakeven (bps)": round(breakeven, 2),
        "Intrinsic (bps)": round(intrinsic, 2),
        "Time Value (bps)": round(premium_paid - intrinsic, 2),
    }


# ---------------------------------------------------------------------------
# Historical spread analysis (z-score, vol regime)
# ---------------------------------------------------------------------------

def spread_option_setup(
    spread_series: pd.Series,
    expiry_months: int = 3,
    strike_type: str = "ATM",
    strike_offset_bps: float = 0.0,
    vol_window: int = 63,
) -> Dict[str, float]:
    """
    Set up a spread option trade from historical spread data.

    Parameters
    ----------
    spread_series    : historical spread in bps (e.g. 2s10s)
    expiry_months    : months to expiry
    strike_type      : 'ATM' (at-the-money), 'OTM', or 'custom'
    strike_offset_bps: offset from ATM for OTM options
    vol_window       : days for realised vol estimation

    Returns dict with pricing inputs and z-score context.
    """
    spread = spread_series.dropna()
    current = float(spread.iloc[-1])
    expiry_years = expiry_months / 12.0

    # Historical vol (realised, annualised)
    daily_changes = spread.diff().dropna()
    hist_vol_ann = float(daily_changes.tail(vol_window).std() * np.sqrt(252))

    # Z-score
    z = float(zscore(spread, 252).iloc[-1])
    pct = float(percentile_rank(spread, 252).iloc[-1])

    # Strike
    if strike_type == "ATM":
        strike = current
    elif strike_type == "OTM":
        # OTM call: strike above forward; OTM put: below
        strike = current + strike_offset_bps
    else:
        strike = current + strike_offset_bps

    # Bachelier price
    call_price = bachelier_price(current, strike, hist_vol_ann, expiry_years, "call")
    put_price = bachelier_price(current, strike, hist_vol_ann, expiry_years, "put")
    greeks_call = bachelier_greeks(current, strike, hist_vol_ann, expiry_years, "call")

    return {
        "Spread (bps)": round(current, 2),
        "Strike (bps)": round(strike, 2),
        "Hist Vol (bps/yr)": round(hist_vol_ann, 2),
        "Expiry (yrs)": expiry_years,
        "Call Price (bps)": round(call_price, 2),
        "Put Price (bps)": round(put_price, 2),
        "Call Delta": greeks_call["delta"],
        "Call Vega": greeks_call["vega"],
        "Z-score (1Y)": round(z, 2),
        "Pctile (1Y)": round(pct, 1),
    }


# ---------------------------------------------------------------------------
# Spread option screening table (multiple spreads)
# ---------------------------------------------------------------------------

def spread_option_screen(
    spread_dict: Dict[str, pd.Series],
    expiry_months: int = 3,
    vol_window: int = 63,
) -> pd.DataFrame:
    """
    Screen multiple spread series for spread option opportunities.

    Parameters
    ----------
    spread_dict  : dict of {name: spread_series_bps}
    expiry_months: option expiry
    vol_window   : vol estimation window

    Returns DataFrame sorted by absolute z-score (most extreme first).
    """
    rows = []
    for name, series in spread_dict.items():
        try:
            setup = spread_option_setup(series, expiry_months, "ATM", 0.0, vol_window)
            setup["Trade"] = name
            rows.append(setup)
        except Exception:
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).set_index("Trade")
    df["Abs Z"] = df["Z-score (1Y)"].abs()
    return df.sort_values("Abs Z", ascending=False).drop(columns="Abs Z")
