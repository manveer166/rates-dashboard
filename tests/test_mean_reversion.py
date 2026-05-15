"""Tests for the OU / AR(1) mean-reversion fit."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import math

import numpy as np
import pandas as pd
import pytest


# Reproducible seed across tests
@pytest.fixture(autouse=True)
def _seed():
    np.random.seed(0)


def _simulate_ou(half_life: float, mu: float, sigma: float, n: int) -> pd.Series:
    """Generate an OU sample path with known parameters."""
    theta = math.log(2) / half_life
    x = np.zeros(n)
    x[0] = mu
    for i in range(1, n):
        x[i] = (x[i - 1]
                 + theta * (mu - x[i - 1])
                 + sigma * np.random.randn())
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(x, index=idx)


def test_fit_recovers_half_life_for_long_sample():
    """A long OU sample should recover the half-life within ±30%.
    Wider tolerance reflects the Euler-discretisation bias in the
    simulator and the typical noise floor on a finite sample."""
    import fixed_income as fi
    true_hl = 30
    s = _simulate_ou(half_life=true_hl, mu=4.0, sigma=0.05, n=5000)
    fit = fi.fit_ou(s, window_days=5000, horizon_days=21)
    assert fit.valid
    assert 0.70 * true_hl < fit.half_life_days < 1.30 * true_hl, (
        f"recovered half-life {fit.half_life_days:.1f} not within 30% of {true_hl}"
    )


def test_fit_recovers_long_run_mean():
    """μ should come back within 10% of the true value."""
    import fixed_income as fi
    mu = 4.0
    s = _simulate_ou(half_life=30, mu=mu, sigma=0.05, n=5000)
    fit = fi.fit_ou(s, window_days=2000)
    assert fit.valid
    assert math.isclose(fit.long_run_mean, mu, abs_tol=0.05)


def test_fit_signs_expected_move_correctly():
    """If X_0 > μ, expected move should be NEGATIVE (towards μ from above)."""
    import fixed_income as fi
    # Build a series where the last value is well above the long-run mean
    s = _simulate_ou(half_life=30, mu=4.0, sigma=0.01, n=2000)
    s.iloc[-1] = 5.0   # force a positive dislocation
    fit = fi.fit_ou(s, window_days=500, horizon_days=21)
    assert fit.valid
    assert fit.dislocation > 0
    assert fit.expected_move_h < 0


def test_fit_returns_invalid_on_too_little_data():
    """Fewer than 20 obs → fit.valid = False, no crash."""
    import fixed_income as fi
    s = pd.Series([1.0, 1.1, 1.2, 1.05])
    fit = fi.fit_ou(s, window_days=252, horizon_days=21)
    assert not fit.valid


def test_fit_returns_long_half_life_on_random_walk():
    """A random walk has b ≈ 1 in expectation. In finite samples the fit
    can find spurious mean reversion; that's a known property of AR(1)
    on integrated series. We require either invalid (b ≥ 1) or a
    long fitted half-life (≥ 40 days) — both indicate "don't trust
    this fit for tactical reversion calls."
    """
    import fixed_income as fi
    np.random.seed(0)
    n = 1000
    x = np.cumsum(np.random.randn(n) * 0.1)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    s = pd.Series(x, index=idx)
    fit = fi.fit_ou(s, window_days=500, horizon_days=21)
    assert (not fit.valid) or fit.half_life_days >= 40


def test_mean_reversion_bps_is_zero_when_at_mean():
    """X_0 = μ → expected move = 0 → mean_reversion_bps = 0."""
    import fixed_income as fi
    s = _simulate_ou(half_life=30, mu=4.0, sigma=0.01, n=2000)
    s.iloc[-1] = s.iloc[-200:-1].mean()   # set last to the recent mean
    mr = fi.mean_reversion_bps(s, is_receive=True, horizon_days=21)
    # Won't be exactly 0 because the fitted μ ≠ actual mean exactly,
    # but should be tiny.
    assert abs(mr) < 1.0
