"""
OLS regression and rolling regression utilities.
"""

import logging
import warnings
from typing import Union

import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.regression.rolling import RollingOLS

logger = logging.getLogger(__name__)


def run_ols(
    y: pd.Series,
    X: Union[pd.DataFrame, pd.Series],
    add_const: bool = True,
) -> dict:
    """
    Run OLS regression of y on X.

    Parameters
    ----------
    y         : Dependent variable
    X         : Independent variable(s)
    add_const : Whether to add a constant term

    Returns
    -------
    dict with model, r2, params, pvalues, conf_int, residuals, summary_html
    """
    if isinstance(X, pd.Series):
        X = X.to_frame()

    combined = pd.concat([y, X], axis=1).dropna()
    if len(combined) < 10:
        logger.warning("Insufficient data for OLS (< 10 observations)")
        return {}

    y_clean = combined.iloc[:, 0]
    X_clean = combined.iloc[:, 1:]
    if add_const:
        X_clean = sm.add_constant(X_clean)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = sm.OLS(y_clean, X_clean).fit()

    return {
        "model":        model,
        "r2":           model.rsquared,
        "adj_r2":       model.rsquared_adj,
        "params":       model.params,
        "pvalues":      model.pvalues,
        "conf_int":     model.conf_int(),
        "residuals":    model.resid,
        "fitted":       model.fittedvalues,
        "nobs":         int(model.nobs),
        "aic":          model.aic,
        "bic":          model.bic,
        "summary_html": model.summary().as_html(),
        "y_name":       y.name,
        "x_names":      list(X.columns),
    }


def run_rolling_regression(
    y: pd.Series,
    x: pd.Series,
    window: int = 63,
) -> pd.DataFrame:
    """
    Rolling OLS regression of y on x (with constant).

    Parameters
    ----------
    y      : Dependent variable
    x      : Single independent variable
    window : Rolling window in trading days (63 ≈ 3 months, 252 ≈ 1 year)

    Returns
    -------
    DataFrame with columns: alpha, beta, and optionally t-stats
    """
    combined = pd.concat([y, x], axis=1).dropna()
    if len(combined) < window:
        logger.warning(f"Not enough data for rolling regression (need {window}, got {len(combined)})")
        return pd.DataFrame()

    y_c = combined.iloc[:, 0]
    X_c = sm.add_constant(combined.iloc[:, 1])

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rols   = RollingOLS(y_c, X_c, window=window)
        result = rols.fit(reset=int(window))

    params = result.params.copy()
    params.columns = ["alpha", "beta"]
    return params


def correlation_matrix(df: pd.DataFrame, method: str = "pearson") -> pd.DataFrame:
    """
    Compute pairwise correlation matrix for all numeric columns in df.

    Parameters
    ----------
    df     : DataFrame (e.g. master DataFrame or spreads)
    method : 'pearson', 'spearman', or 'kendall'

    Returns
    -------
    Correlation matrix DataFrame
    """
    numeric = df.select_dtypes(include=[np.number])
    return numeric.corr(method=method)


def change_correlation_matrix(df: pd.DataFrame, periods: int = 1, method: str = "pearson") -> pd.DataFrame:
    """
    Correlation matrix on *changes* (first differences) rather than levels.
    Levels are often non-stationary; change correlations are more meaningful.
    """
    changes = df.diff(periods).dropna()
    return correlation_matrix(changes, method=method)
