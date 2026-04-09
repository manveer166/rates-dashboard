"""
Nelson-Siegel yield curve fitting.

Model: y(tau) = beta0
              + beta1 * (1 - exp(-tau/lam)) / (tau/lam)
              + beta2 * [(1 - exp(-tau/lam)) / (tau/lam) - exp(-tau/lam)]

beta0 = long-run level
beta1 = short-term loading (negative → upward-sloping curve)
beta2 = medium-term curvature (hump)
lam   = decay parameter (controls where hump peaks)
"""

import logging
import warnings

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeWarning, curve_fit

from config import TENOR_LABELS, TENOR_YEARS

logger = logging.getLogger(__name__)

_TAU_DENSE = np.linspace(1 / 12, 30, 300)   # for smooth curve plotting


def nelson_siegel(tau: np.ndarray, beta0: float, beta1: float, beta2: float, lam: float) -> np.ndarray:
    """Evaluate the Nelson-Siegel model at tenor(s) tau."""
    tau  = np.asarray(tau, dtype=float)
    lam  = max(lam, 1e-6)   # prevent division by zero
    exp_term   = np.exp(-tau / lam)
    load_factor = (1 - exp_term) / (tau / lam)
    return beta0 + beta1 * load_factor + beta2 * (load_factor - exp_term)


def fit_curve(yields_row: pd.Series) -> dict:
    """
    Fit Nelson-Siegel to a single date's yield curve.

    Parameters
    ----------
    yields_row : Series indexed by tenor labels (e.g. "1M", "3M", ..., "30Y")

    Returns
    -------
    dict with keys: beta0, beta1, beta2, lambda, rmse, fitted_dense, success
    """
    tenors_all = np.array(TENOR_YEARS)
    rates_all  = yields_row.reindex(TENOR_LABELS).values.astype(float)

    mask = ~np.isnan(rates_all)
    if mask.sum() < 4:
        return _failed_fit()

    tenors = tenors_all[mask]
    rates  = rates_all[mask]

    p0     = [rates.mean(), -0.5, 0.5, 1.5]
    bounds = ([0, -10, -10, 0.1], [25, 10, 10, 15])

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", OptimizeWarning)
            popt, _ = curve_fit(
                nelson_siegel, tenors, rates,
                p0=p0, bounds=bounds, maxfev=10_000,
            )
        fitted_dense = nelson_siegel(_TAU_DENSE, *popt)
        residuals    = rates - nelson_siegel(tenors, *popt)
        rmse         = float(np.sqrt(np.mean(residuals ** 2)))

        return {
            "beta0":        float(popt[0]),
            "beta1":        float(popt[1]),
            "beta2":        float(popt[2]),
            "lambda":       float(popt[3]),
            "rmse":         rmse,
            "fitted_dense": fitted_dense,
            "tau_dense":    _TAU_DENSE,
            "success":      True,
        }
    except Exception as e:
        logger.debug(f"Nelson-Siegel fit failed: {e}")
        return _failed_fit()


def fit_history(df: pd.DataFrame, freq: str = "W") -> pd.DataFrame:
    """
    Fit Nelson-Siegel to each row (date) in df, returns DataFrame of parameters.

    Parameters
    ----------
    df   : DataFrame with TENOR_LABELS columns and DatetimeIndex
    freq : Resample frequency for fitting (default weekly to save time)

    Returns
    -------
    DataFrame with columns [beta0, beta1, beta2, lambda, rmse]
    """
    available = [c for c in TENOR_LABELS if c in df.columns]
    sub = df[available].resample(freq).last().dropna(how="all")

    results = []
    for date, row in sub.iterrows():
        fit = fit_curve(row)
        if fit["success"]:
            results.append({
                "date":   date,
                "beta0":  fit["beta0"],
                "beta1":  fit["beta1"],
                "beta2":  fit["beta2"],
                "lambda": fit["lambda"],
                "rmse":   fit["rmse"],
            })

    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results).set_index("date")


def _failed_fit() -> dict:
    return {
        "beta0": np.nan, "beta1": np.nan, "beta2": np.nan,
        "lambda": np.nan, "rmse": np.nan,
        "fitted_dense": np.full_like(_TAU_DENSE, np.nan),
        "tau_dense": _TAU_DENSE,
        "success": False,
    }
