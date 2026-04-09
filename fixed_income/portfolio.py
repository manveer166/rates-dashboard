"""
portfolio.py — Portfolio analytics: beta, correlation, efficient frontier, Sharpe.

This module covers the portfolio-level analysis seen in the eSwaps & Bonds notebook:

1. Beta / Regression
   How much does one trade move per unit move in another?
   Used to hedge cross-currency or cross-tenor exposures.

2. Correlation matrix
   Which trades move together? Used to avoid inadvertent concentration.

3. Efficient Frontier
   Find the minimum-variance portfolio for a given expected return,
   or the maximum Sharpe portfolio. Based on Markowitz mean-variance.

4. Historical Sharpe analysis
   Rolling Sharpe of each trade — are we being paid for the risk?

5. Annual move indicator
   How much has each instrument moved in the last 12 months vs
   its historical distribution?
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Dict, List, Optional, Tuple
from .utils import zscore, percentile_rank, annualized_vol


# ---------------------------------------------------------------------------
# Beta and regression
# ---------------------------------------------------------------------------

def rolling_beta(
    y: pd.Series,
    x: pd.Series,
    window: int = 252,
) -> pd.Series:
    """
    Rolling OLS beta: how many bps does y move per 1bp move in x?

    beta_t = cov(y, x) / var(x)  over a rolling window.
    """
    y_chg = y.diff().dropna()
    x_chg = x.diff().dropna()
    aligned = pd.concat([y_chg, x_chg], axis=1).dropna()
    aligned.columns = ["y", "x"]

    betas = aligned["y"].rolling(window).cov(aligned["x"]) / aligned["x"].rolling(window).var()
    betas.name = f"beta({y.name}/{x.name})"
    return betas


def hedge_ratio(
    y: pd.Series,
    x: pd.Series,
    window: int = 252,
) -> float:
    """
    Current hedge ratio: units of x to hold per unit of y to be DV01-neutral
    on a regression basis.
    """
    b = rolling_beta(y, x, window)
    return float(b.dropna().iloc[-1])


def regression_summary(
    y: pd.Series,
    x: pd.Series,
    window: int = 252,
) -> Dict[str, float]:
    """
    OLS regression summary over the last <window> observations.

    Returns: beta, alpha (annualised), R², tracking_error.
    """
    y_chg = y.diff().dropna().tail(window)
    x_chg = x.diff().dropna().tail(window)
    aligned = pd.concat([y_chg, x_chg], axis=1).dropna()
    aligned.columns = ["y", "x"]

    if len(aligned) < 20:
        return {}

    x_vals = aligned["x"].values
    y_vals = aligned["y"].values
    x_mat = np.column_stack([np.ones(len(x_vals)), x_vals])
    coeffs, residuals, _, _ = np.linalg.lstsq(x_mat, y_vals, rcond=None)
    alpha_daily, beta = coeffs

    fitted = x_mat @ coeffs
    ss_res = np.sum((y_vals - fitted) ** 2)
    ss_tot = np.sum((y_vals - y_vals.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    resid = y_vals - fitted
    tracking_error_ann = float(resid.std() * np.sqrt(252) * 100)  # annualised bps

    return {
        "Beta": round(beta, 4),
        "Alpha (daily bps)": round(alpha_daily * 100, 3),
        "Alpha (ann bps)": round(alpha_daily * 100 * 252, 1),
        "R²": round(r2, 4),
        "Tracking Error (bps/yr)": round(tracking_error_ann, 2),
    }


# ---------------------------------------------------------------------------
# Efficient Frontier
# ---------------------------------------------------------------------------

def efficient_frontier(
    returns_df: pd.DataFrame,
    n_portfolios: int = 200,
    risk_free_rate: float = 0.0,
    annualise_factor: int = 252,
) -> pd.DataFrame:
    """
    Compute the mean-variance efficient frontier.

    Parameters
    ----------
    returns_df      : DataFrame of daily returns (bps or %) per trade/strategy
    n_portfolios    : number of frontier points to compute
    risk_free_rate  : annualised risk-free rate in same units as returns
    annualise_factor: trading days per year

    Returns DataFrame with columns:
        Return (ann), Vol (ann), Sharpe, Weights...
    """
    rets = returns_df.dropna()
    mu = rets.mean() * annualise_factor        # annualised expected return
    sigma = rets.cov() * annualise_factor      # annualised covariance
    n = len(mu)

    def portfolio_stats(weights):
        w = np.array(weights)
        p_ret = float(w @ mu)
        p_vol = float(np.sqrt(w @ sigma.values @ w))
        return p_ret, p_vol

    def neg_sharpe(weights):
        p_ret, p_vol = portfolio_stats(weights)
        return -(p_ret - risk_free_rate) / p_vol if p_vol > 0 else 0.0

    def min_vol(weights):
        return portfolio_stats(weights)[1]

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(0, 1)] * n  # long-only; remove for long/short
    w0 = np.ones(n) / n

    # Target return grid
    min_ret = float(mu.min())
    max_ret = float(mu.max())
    target_returns = np.linspace(min_ret, max_ret, n_portfolios)

    frontier_rows = []
    for target in target_returns:
        cons = constraints + [{"type": "eq", "fun": lambda w, t=target: portfolio_stats(w)[0] - t}]
        res = minimize(min_vol, w0, method="SLSQP",
                       constraints=cons, bounds=bounds,
                       options={"ftol": 1e-9, "maxiter": 1000})
        if res.success:
            p_ret, p_vol = portfolio_stats(res.x)
            sharpe = (p_ret - risk_free_rate) / p_vol if p_vol > 0 else 0.0
            row = {"Return (ann)": round(p_ret, 4), "Vol (ann)": round(p_vol, 4),
                   "Sharpe": round(sharpe, 4)}
            for i, col in enumerate(returns_df.columns):
                row[f"w_{col}"] = round(float(res.x[i]), 4)
            frontier_rows.append(row)

    return pd.DataFrame(frontier_rows) if frontier_rows else pd.DataFrame()


def max_sharpe_portfolio(
    returns_df: pd.DataFrame,
    risk_free_rate: float = 0.0,
    annualise_factor: int = 252,
    long_only: bool = True,
) -> Dict[str, float]:
    """
    Find the maximum Sharpe ratio portfolio (tangency portfolio).

    Returns dict with weights, expected return, vol, and Sharpe.
    """
    rets = returns_df.dropna()
    mu = rets.mean() * annualise_factor
    sigma = rets.cov() * annualise_factor
    n = len(mu)

    def neg_sharpe(weights):
        w = np.array(weights)
        p_ret = float(w @ mu)
        p_vol = float(np.sqrt(w @ sigma.values @ w))
        if p_vol <= 0:
            return 0.0
        return -(p_ret - risk_free_rate) / p_vol

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(0, 1)] * n if long_only else [(-1, 1)] * n
    w0 = np.ones(n) / n

    res = minimize(neg_sharpe, w0, method="SLSQP",
                   constraints=constraints, bounds=bounds,
                   options={"ftol": 1e-9, "maxiter": 1000})

    if not res.success:
        return {}

    w = res.x
    p_ret = float(w @ mu)
    p_vol = float(np.sqrt(w @ sigma.values @ w))
    sharpe = (p_ret - risk_free_rate) / p_vol if p_vol > 0 else 0.0

    result = {
        "Expected Return (ann)": round(p_ret, 4),
        "Volatility (ann)": round(p_vol, 4),
        "Sharpe": round(sharpe, 4),
    }
    for i, col in enumerate(returns_df.columns):
        result[f"w_{col}"] = round(float(w[i]), 4)
    return result


def min_variance_portfolio(
    returns_df: pd.DataFrame,
    annualise_factor: int = 252,
) -> Dict[str, float]:
    """Find the global minimum variance portfolio."""
    rets = returns_df.dropna()
    sigma = rets.cov() * annualise_factor
    n = len(sigma)

    def port_vol(weights):
        w = np.array(weights)
        return float(np.sqrt(w @ sigma.values @ w))

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(0, 1)] * n
    w0 = np.ones(n) / n

    res = minimize(port_vol, w0, method="SLSQP",
                   constraints=constraints, bounds=bounds)

    if not res.success:
        return {}

    w = res.x
    mu = rets.mean() * annualise_factor
    p_vol = port_vol(w)
    p_ret = float(w @ mu)

    result = {
        "Expected Return (ann)": round(p_ret, 4),
        "Volatility (ann)": round(p_vol, 4),
        "Sharpe": round(p_ret / p_vol, 4) if p_vol > 0 else 0.0,
    }
    for i, col in enumerate(returns_df.columns):
        result[f"w_{col}"] = round(float(w[i]), 4)
    return result


# ---------------------------------------------------------------------------
# Sharpe analysis
# ---------------------------------------------------------------------------

def rolling_sharpe(
    returns: pd.Series,
    window: int = 252,
    risk_free: float = 0.0,
    annualise: bool = True,
) -> pd.Series:
    """
    Rolling annualised Sharpe ratio.

    Sharpe_t = (mean_return - rf) / std_return × sqrt(annualise_factor)
    """
    excess = returns - risk_free / 252  # daily risk-free
    mu = excess.rolling(window).mean()
    sigma = excess.rolling(window).std()
    factor = np.sqrt(252) if annualise else 1.0
    result = mu / sigma * factor
    result.name = f"Sharpe({returns.name})"
    return result


def sharpe_table(
    returns_df: pd.DataFrame,
    windows: Optional[List[int]] = None,
    risk_free_ann: float = 0.0,
) -> pd.DataFrame:
    """
    Sharpe summary table for multiple return streams over different windows.

    Parameters
    ----------
    returns_df     : DataFrame of daily returns (one column per strategy)
    windows        : lookback windows in days, default [63, 126, 252, 504]
    risk_free_ann  : annualised risk-free rate in same units as returns
    """
    if windows is None:
        windows = [63, 126, 252, 504]

    window_labels = {63: "3M", 126: "6M", 252: "1Y", 504: "2Y"}
    rows = {}
    for col in returns_df.columns:
        s = returns_df[col].dropna()
        row = {}
        for w in windows:
            label = window_labels.get(w, f"{w}d")
            tail = s.tail(w)
            if len(tail) < 10:
                row[f"Sharpe ({label})"] = np.nan
                continue
            excess = tail - risk_free_ann / 252
            sr = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else np.nan
            row[f"Sharpe ({label})"] = round(sr, 2) if not np.isnan(sr) else np.nan

        # Also add annualised return and vol
        row["Ann Return"] = round(float(s.tail(252).mean() * 252), 4)
        row["Ann Vol"] = round(float(s.tail(252).std() * np.sqrt(252)), 4)
        rows[col] = row

    return pd.DataFrame(rows).T


# ---------------------------------------------------------------------------
# Annual move indicator (from Gamma PDF)
# ---------------------------------------------------------------------------

def annual_move_indicator(
    rate_df: pd.DataFrame,
    window: int = 252,
) -> pd.DataFrame:
    """
    Compute the trailing 12-month move for each series and compare
    to the historical distribution of annual moves.

    Columns per series:
        Current | 1Y ago | Annual Move (bps) | Z-score of move | Pctile

    This answers: "Is this a historically large or small annual move?"
    """
    rows = {}
    for col in rate_df.columns:
        s = rate_df[col].dropna()
        if len(s) < window + 20:
            continue
        current = float(s.iloc[-1])
        one_yr_ago = float(s.iloc[-window - 1]) if len(s) > window + 1 else np.nan
        annual_move = (current - one_yr_ago) * 100 if not np.isnan(one_yr_ago) else np.nan

        # Distribution of all rolling annual moves
        all_moves = s.diff(window).dropna() * 100  # bps
        z_move = (annual_move - float(all_moves.mean())) / float(all_moves.std()) \
            if all_moves.std() > 0 else np.nan
        pctile = float(np.sum(all_moves < annual_move)) / len(all_moves) * 100 \
            if len(all_moves) > 0 else np.nan

        rows[col] = {
            "Current (%)": round(current, 3),
            "1Y Ago (%)": round(one_yr_ago, 3) if not np.isnan(one_yr_ago) else np.nan,
            "Annual Move (bps)": round(annual_move, 1) if not np.isnan(annual_move) else np.nan,
            "Z-score of Move": round(z_move, 2) if not np.isnan(z_move) else np.nan,
            "Pctile of Move": round(pctile, 1) if not np.isnan(pctile) else np.nan,
        }

    return pd.DataFrame(rows).T


# ---------------------------------------------------------------------------
# Cross-country correlation comparison
# ---------------------------------------------------------------------------

def cross_country_beta(
    domestic_series: pd.Series,
    foreign_series: pd.Series,
    window: int = 252,
) -> pd.DataFrame:
    """
    Rolling beta of domestic rate changes vs foreign rate changes.
    Used for cross-currency rate hedging and relative value.

    Returns DataFrame with: rolling_beta, rolling_correlation, rolling_r2.
    """
    d_chg = domestic_series.diff().dropna()
    f_chg = foreign_series.diff().dropna()
    aligned = pd.concat([d_chg, f_chg], axis=1).dropna()
    aligned.columns = ["domestic", "foreign"]

    beta = aligned["domestic"].rolling(window).cov(aligned["foreign"]) / \
           aligned["foreign"].rolling(window).var()
    corr = aligned["domestic"].rolling(window).corr(aligned["foreign"])
    # R² = correlation²
    r2 = corr ** 2

    result = pd.DataFrame({"beta": beta, "correlation": corr, "r2": r2})
    result.name = f"{domestic_series.name} vs {foreign_series.name}"
    return result.dropna()


def multi_country_beta_table(
    rate_df: pd.DataFrame,
    base_col: str,
    compare_cols: List[str],
    window: int = 252,
) -> pd.DataFrame:
    """
    Beta and correlation of multiple countries vs a base country.

    Parameters
    ----------
    rate_df     : DataFrame with country rate columns
    base_col    : base/reference country (e.g. 'USD_10Y')
    compare_cols: other countries (e.g. ['EUR_10Y', 'GBP_10Y', 'JPY_10Y'])
    """
    rows = []
    for col in compare_cols:
        if col not in rate_df.columns:
            continue
        stats = cross_country_beta(rate_df[col], rate_df[base_col], window)
        current_beta = float(stats["beta"].iloc[-1]) if len(stats) > 0 else np.nan
        current_corr = float(stats["correlation"].iloc[-1]) if len(stats) > 0 else np.nan
        current_r2 = float(stats["r2"].iloc[-1]) if len(stats) > 0 else np.nan
        rows.append({
            "Country": col,
            "vs": base_col,
            "Beta": round(current_beta, 3),
            "Correlation": round(current_corr, 3),
            "R²": round(current_r2, 3),
        })
    return pd.DataFrame(rows)
