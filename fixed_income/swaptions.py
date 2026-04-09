"""
swaptions.py — Swaption pricing and expected return analysis.

What is a swaption?
-------------------
A swaption is an option to enter into an interest rate swap at a future date.

  Payer swaption   : right to PAY fixed / receive floating at expiry
                     (profits if rates rise — like a bond short)
  Receiver swaption: right to RECEIVE fixed / pay floating at expiry
                     (profits if rates fall — like a bond long)

Key inputs:
  • Expiry        : when the option can be exercised (e.g. 1Y)
  • Tail (tenor)  : length of the underlying swap (e.g. 10Y)
  → Written as "1Y10Y" swaption (1 year into a 10-year swap)

Pricing models used here
-------------------------
1. Black's model (log-normal)  — market standard for positive rates
2. Bachelier (normal)          — better for negative rate environments
3. SABR                        — handles vol smile/skew
4. Expected return analysis    — carry, rolldown, theta vs realised vol

Vol surfaces
-----------
Implied vols are quoted as a matrix of expiry × tenor.
ATM vols are the most liquid; OTM vols encode the skew.
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq, minimize
from typing import Dict, List, Optional, Tuple
from .utils import zscore, percentile_rank, rolling_std
from .carry_rolldown import interpolate_rate
from .wedges import forward_swap_rate


# Standard swaption expiry and tail labels
EXPIRY_LABELS = ["1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y"]
TAIL_LABELS   = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y"]

EXPIRY_YEARS  = {"1M": 1/12, "3M": 0.25, "6M": 0.5,
                 "1Y": 1.0, "2Y": 2.0, "5Y": 5.0, "10Y": 10.0}
TAIL_YEARS    = {"1Y": 1.0, "2Y": 2.0, "3Y": 3.0, "5Y": 5.0,
                 "7Y": 7.0, "10Y": 10.0, "15Y": 15.0, "20Y": 20.0, "30Y": 30.0}


# ---------------------------------------------------------------------------
# Annuity (swap DV01 proxy)
# ---------------------------------------------------------------------------

def swap_annuity(
    forward_rate: float,
    tail_years: float,
    freq: int = 2,
) -> float:
    """
    Present value of an annuity paying 1 per period for `tail_years`.
    Used to convert swaption price from rate-space to bps.

    A(F, T) = sum_{i=1}^{N} 1/freq / (1 + F/freq)^i
    """
    r = forward_rate / 100.0
    n = int(tail_years * freq)
    if r == 0:
        return tail_years
    return (1 - (1 + r / freq) ** (-n)) / (r / freq) / freq


# ---------------------------------------------------------------------------
# Black's model (log-normal)
# ---------------------------------------------------------------------------

def black_swaption(
    forward_rate: float,
    strike: float,
    vol_lognormal: float,
    expiry_years: float,
    tail_years: float,
    swaption_type: str = "payer",
    notional: float = 1.0,
) -> float:
    """
    Black's model for a swaption.

    Price = Annuity × [F × N(d1) - K × N(d2)]  (payer)
    Price = Annuity × [K × N(-d2) - F × N(-d1)]  (receiver)

    Parameters
    ----------
    forward_rate  : forward swap rate in %
    strike        : option strike rate in %
    vol_lognormal : Black implied vol (decimal, e.g. 0.30 for 30%)
    expiry_years  : option expiry in years
    tail_years    : underlying swap length in years
    swaption_type : 'payer' or 'receiver'
    notional      : notional in millions

    Returns swaption premium in bps of notional.
    """
    F = forward_rate / 100.0
    K = strike / 100.0
    if F <= 0 or K <= 0:
        return np.nan

    sigma_t = vol_lognormal * np.sqrt(expiry_years)
    if sigma_t <= 0:
        if swaption_type == "payer":
            return max(F - K, 0.0) * 10000
        else:
            return max(K - F, 0.0) * 10000

    d1 = (np.log(F / K) + 0.5 * vol_lognormal ** 2 * expiry_years) / sigma_t
    d2 = d1 - sigma_t

    annuity = swap_annuity(forward_rate, tail_years)

    if swaption_type == "payer":
        price_pct = annuity * (F * norm.cdf(d1) - K * norm.cdf(d2))
    else:
        price_pct = annuity * (K * norm.cdf(-d2) - F * norm.cdf(-d1))

    return round(price_pct * 10000, 2)  # bps


# ---------------------------------------------------------------------------
# Bachelier (Normal) model for swaptions
# ---------------------------------------------------------------------------

def bachelier_swaption(
    forward_rate: float,
    strike: float,
    vol_normal_bps: float,
    expiry_years: float,
    tail_years: float,
    swaption_type: str = "payer",
) -> float:
    """
    Bachelier (normal) swaption price.

    Price = Annuity × sigma_T × [d × N(d) + n(d)]
    where d = (F - K) / sigma_T,  sigma_T = vol_normal × sqrt(T)

    Parameters
    ----------
    vol_normal_bps : normal vol in bps/year (e.g. 80 bps/yr)
    All rates in %.

    Returns premium in bps.
    """
    F = forward_rate  # in %
    K = strike        # in %
    sigma_t = vol_normal_bps / 100.0 * np.sqrt(expiry_years)  # convert bps → %
    annuity = swap_annuity(forward_rate, tail_years)

    if sigma_t <= 0:
        if swaption_type == "payer":
            return max(F - K, 0.0) * 100 * annuity
        else:
            return max(K - F, 0.0) * 100 * annuity

    d = (F - K) / sigma_t

    if swaption_type == "payer":
        price_pct = annuity * sigma_t * (d * norm.cdf(d) + norm.pdf(d))
    else:
        price_pct = annuity * sigma_t * (-d * norm.cdf(-d) + norm.pdf(d))

    return round(price_pct * 100, 2)  # bps


def bachelier_implied_vol_swaption(
    market_price_bps: float,
    forward_rate: float,
    strike: float,
    expiry_years: float,
    tail_years: float,
    swaption_type: str = "payer",
) -> float:
    """Solve for Bachelier implied vol (bps/yr) from a market swaption price."""
    def objective(vol_bps):
        return bachelier_swaption(forward_rate, strike, vol_bps,
                                  expiry_years, tail_years, swaption_type) - market_price_bps
    try:
        return float(brentq(objective, 0.1, 5000.0, xtol=1e-4))
    except ValueError:
        return np.nan


# ---------------------------------------------------------------------------
# Swaption greeks
# ---------------------------------------------------------------------------

def swaption_greeks(
    forward_rate: float,
    strike: float,
    vol_normal_bps: float,
    expiry_years: float,
    tail_years: float,
    swaption_type: str = "payer",
) -> Dict[str, float]:
    """
    Bachelier swaption greeks.

    Delta : sensitivity to forward rate (bps of annuity-weighted move)
    Gamma : convexity (second-order delta)
    Vega  : sensitivity to implied vol (per 1 bps/yr move in vol)
    Theta : time decay per calendar day (in bps)
    """
    annuity = swap_annuity(forward_rate, tail_years)
    sigma_t = vol_normal_bps / 100.0 * np.sqrt(expiry_years)

    if sigma_t <= 0:
        return {"delta": 1.0 if forward_rate > strike else 0.0,
                "gamma": 0.0, "vega": 0.0, "theta": 0.0}

    d = (forward_rate - strike) / (sigma_t * 100)  # normalise: rates in %

    if swaption_type == "payer":
        delta = annuity * norm.cdf(d)    # per % move in forward
    else:
        delta = -annuity * norm.cdf(-d)

    # gamma and vega in Bachelier framework
    gamma = annuity * norm.pdf(d) / (sigma_t * 100)
    vega = annuity * np.sqrt(expiry_years) * norm.pdf(d) / 100  # per bps/yr vol

    # Theta (finite difference)
    price_now = bachelier_swaption(forward_rate, strike, vol_normal_bps,
                                   expiry_years, tail_years, swaption_type)
    dt = 1 / 365.0
    if expiry_years > dt:
        price_dt = bachelier_swaption(forward_rate, strike, vol_normal_bps,
                                      expiry_years - dt, tail_years, swaption_type)
        theta = price_dt - price_now
    else:
        theta = 0.0

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "vega": round(vega, 4),
        "theta": round(theta, 4),
    }


# ---------------------------------------------------------------------------
# SABR model (captures vol smile)
# ---------------------------------------------------------------------------

def sabr_vol(
    F: float,
    K: float,
    T: float,
    alpha: float,
    beta: float,
    rho: float,
    nu: float,
) -> float:
    """
    Hagan et al. SABR implied normal volatility approximation.

    Parameters: alpha=initial vol, beta=CEV exponent, rho=correlation, nu=vol-of-vol.
    Returns normal vol in the same units as F and K.
    """
    if abs(F - K) < 1e-6:  # ATM
        fk_mid = F
        vol = alpha * (
            1 + ((1 - beta) ** 2 / 24 * alpha ** 2 / fk_mid ** (2 - 2 * beta)
                 + 0.25 * rho * beta * nu * alpha / fk_mid ** (1 - beta)
                 + (2 - 3 * rho ** 2) / 24 * nu ** 2) * T
        )
        return vol

    fk_mid = np.sqrt(F * K)
    z = nu / alpha * fk_mid ** (1 - beta) * np.log(F / K)
    x = np.log((np.sqrt(1 - 2 * rho * z + z ** 2) + z - rho) / (1 - rho))

    factor1 = alpha / (fk_mid ** (1 - beta) * (1 + (1 - beta) ** 2 / 24 * np.log(F / K) ** 2
                                                 + (1 - beta) ** 4 / 1920 * np.log(F / K) ** 4))
    factor2 = z / (x + 1e-10)
    factor3 = 1 + ((1 - beta) ** 2 / 24 * alpha ** 2 / fk_mid ** (2 - 2 * beta)
                    + 0.25 * rho * beta * nu * alpha / fk_mid ** (1 - beta)
                    + (2 - 3 * rho ** 2) / 24 * nu ** 2) * T

    return factor1 * factor2 * factor3


def sabr_calibrate(
    strikes: List[float],
    market_vols: List[float],
    F: float,
    T: float,
    beta: float = 0.5,
) -> Dict[str, float]:
    """
    Calibrate SABR parameters (alpha, rho, nu) to market vol quotes.

    Parameters
    ----------
    strikes     : list of strike rates
    market_vols : corresponding market implied vols (same units as F)
    F           : ATM forward rate
    T           : expiry in years
    beta        : CEV exponent (typically 0.5 for rates)
    """
    def objective(params):
        alpha, rho, nu = params
        if alpha <= 0 or nu <= 0 or abs(rho) >= 1:
            return 1e10
        errors = []
        for K, market_v in zip(strikes, market_vols):
            model_v = sabr_vol(F, K, T, alpha, beta, rho, nu)
            errors.append((model_v - market_v) ** 2)
        return sum(errors)

    # Initial guess from ATM vol
    atm_vol = np.interp(F, strikes, market_vols)
    x0 = [atm_vol * F ** (1 - beta), 0.0, 0.3]
    bounds = [(1e-4, None), (-0.999, 0.999), (1e-4, None)]

    result = minimize(objective, x0, method="L-BFGS-B", bounds=bounds)
    if result.success:
        alpha, rho, nu = result.x
        return {"alpha": round(alpha, 6), "beta": beta,
                "rho": round(rho, 4), "nu": round(nu, 4)}
    return {"alpha": np.nan, "beta": beta, "rho": np.nan, "nu": np.nan}


# ---------------------------------------------------------------------------
# Expected return analysis (from Swaptions PDF)
# ---------------------------------------------------------------------------

def swaption_expected_return(
    forward_rate: float,
    strike: float,
    vol_normal_bps: float,
    expiry_years: float,
    tail_years: float,
    realised_vol_bps: float,
    carry_bps: float = 0.0,
    swaption_type: str = "payer",
    n_scenarios: int = 50_000,
    seed: int = 42,
) -> Dict[str, float]:
    """
    Expected return of a bought swaption given a realised vol assumption.

    The key insight: a swaption is cheap if realised_vol > implied_vol.
    Expected P&L = E[payoff at realised vol] - premium paid at implied vol.

    Parameters
    ----------
    vol_normal_bps    : implied normal vol (what you pay)
    realised_vol_bps  : expected realised vol over expiry
    carry_bps         : carry earned while holding the swaption
    """
    # Premium at implied vol
    premium = bachelier_swaption(forward_rate, strike, vol_normal_bps,
                                 expiry_years, tail_years, swaption_type)

    # Simulate forward rate at expiry using realised vol
    rng = np.random.default_rng(seed)
    sigma_t_real = realised_vol_bps / 100.0 * np.sqrt(expiry_years)
    F_T = rng.normal(forward_rate, sigma_t_real * 100, n_scenarios)

    annuity = swap_annuity(forward_rate, tail_years)
    if swaption_type == "payer":
        payoffs = np.maximum(F_T - strike, 0.0) * annuity * 100  # bps
    else:
        payoffs = np.maximum(strike - F_T, 0.0) * annuity * 100

    e_payoff = float(np.mean(payoffs))
    e_pnl = e_payoff - premium + carry_bps
    std_pnl = float(np.std(payoffs - premium))
    prob_profit = float(np.mean(payoffs > premium))
    sharpe = e_pnl / std_pnl if std_pnl > 0 else np.nan

    greeks = swaption_greeks(forward_rate, strike, vol_normal_bps,
                             expiry_years, tail_years, swaption_type)

    return {
        "Premium (bps)": round(premium, 2),
        "E[Payoff] (bps)": round(e_payoff, 2),
        "E[P&L] (bps)": round(e_pnl, 2),
        "Std P&L (bps)": round(std_pnl, 2),
        "Sharpe": round(sharpe, 2) if not np.isnan(sharpe) else np.nan,
        "Prob Profit": round(prob_profit, 3),
        "Impl Vol (bps/yr)": round(vol_normal_bps, 1),
        "Real Vol (bps/yr)": round(realised_vol_bps, 1),
        "Vol Ratio (real/impl)": round(realised_vol_bps / vol_normal_bps, 3),
        "Delta": greeks["delta"],
        "Theta/day (bps)": greeks["theta"],
    }


# ---------------------------------------------------------------------------
# Vol surface builder
# ---------------------------------------------------------------------------

def build_vol_surface(
    expiry_labels: List[str],
    tail_labels: List[str],
    implied_vols: List[List[float]],
) -> pd.DataFrame:
    """
    Build a swaption vol surface DataFrame.

    Parameters
    ----------
    expiry_labels  : row labels, e.g. ['1M','3M','6M','1Y','2Y','5Y','10Y']
    tail_labels    : column labels, e.g. ['1Y','2Y','5Y','10Y','20Y','30Y']
    implied_vols   : 2D list [expiry][tail] of normal vols in bps/yr

    Returns DataFrame with expiry as index, tail as columns.
    """
    return pd.DataFrame(implied_vols, index=expiry_labels, columns=tail_labels)


def vol_surface_zscore(
    current_surface: pd.DataFrame,
    surface_history: Dict[str, pd.DataFrame],
    window: int = 252,
) -> pd.DataFrame:
    """
    Compute z-scores for each point on the vol surface relative to history.

    Parameters
    ----------
    current_surface  : current vol surface (expiry × tail)
    surface_history  : dict of {date_str: vol_surface_df}

    Returns DataFrame of z-scores with same shape as current_surface.
    """
    dates = sorted(surface_history.keys())
    zscores = pd.DataFrame(index=current_surface.index,
                           columns=current_surface.columns, dtype=float)

    for exp in current_surface.index:
        for tail in current_surface.columns:
            history = []
            for d in dates:
                try:
                    v = float(surface_history[d].loc[exp, tail])
                    history.append(v)
                except (KeyError, ValueError):
                    continue

            if len(history) < 20:
                zscores.loc[exp, tail] = np.nan
                continue

            h = np.array(history[-window:])
            curr_val = float(current_surface.loc[exp, tail])
            z = (curr_val - h.mean()) / h.std() if h.std() > 0 else 0.0
            zscores.loc[exp, tail] = round(z, 2)

    return zscores


# ---------------------------------------------------------------------------
# Swaption screening: find cheap/rich points on the vol surface
# ---------------------------------------------------------------------------

def swaption_screen(
    vol_surface: pd.DataFrame,
    realised_vol_surface: pd.DataFrame,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    Screen the swaption vol surface for cheap/rich implied vols vs realised.

    vol_ratio = implied_vol / realised_vol
    < 1 → implied cheap (buy), > 1 → implied rich (sell)
    """
    rows = []
    for exp in vol_surface.index:
        for tail in vol_surface.columns:
            try:
                impl = float(vol_surface.loc[exp, tail])
                real = float(realised_vol_surface.loc[exp, tail])
                if np.isnan(impl) or np.isnan(real) or real == 0:
                    continue
                ratio = impl / real
                rows.append({
                    "Expiry": exp,
                    "Tail": tail,
                    "Instrument": f"{exp}{tail}",
                    "Implied Vol (bps/yr)": round(impl, 1),
                    "Realised Vol (bps/yr)": round(real, 1),
                    "Vol Ratio (impl/real)": round(ratio, 3),
                    "View": "BUY" if ratio < 0.85 else ("SELL" if ratio > 1.15 else "NEUTRAL"),
                })
            except (ValueError, KeyError):
                continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Sort: most extreme ratio first
    df["abs_dev"] = (df["Vol Ratio (impl/real)"] - 1.0).abs()
    return df.sort_values("abs_dev", ascending=False).drop(columns="abs_dev").head(top_n).reset_index(drop=True)
