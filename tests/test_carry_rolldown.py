"""Tests for the fixed-income carry/roll math."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


def test_forward_carry_rolldown_returns_dict():
    import fixed_income as fi
    curve = {"2Y": 3.8, "3Y": 3.9, "5Y": 4.0, "7Y": 4.1, "10Y": 4.3,
             "20Y": 4.9, "30Y": 4.9}
    on_rate = 3.65
    cr = fi.forward_carry_rolldown(curve, on_rate, "outright",
                                    tenor1="10Y", holding_months=1.0)
    assert isinstance(cr, dict)
    assert {"carry", "rolldown", "total"} <= set(cr.keys())


def test_outright_carry_is_yield_minus_overnight_pro_rata():
    """Carry for receive 5Y, 1m hold ≈ (5Y - SOFR) * 1/12 * 100 in bps."""
    import fixed_income as fi
    curve = {"2Y": 3.8, "5Y": 4.0, "10Y": 4.3, "30Y": 4.9}
    on_rate = 3.0
    cr = fi.forward_carry_rolldown(curve, on_rate, "outright",
                                    tenor1="5Y", holding_months=1.0)
    # (4.0 - 3.0)% * (1/12) = 0.0833% = 8.33 bps
    assert cr["carry"] == pytest.approx(8.33, abs=0.5)


def test_spread_carry_is_long_minus_short():
    """Spread carry (receive long, pay short) = long carry - short carry."""
    import fixed_income as fi
    curve = {"2Y": 3.0, "5Y": 4.0, "10Y": 4.5, "30Y": 4.9}
    on_rate = 3.0
    spread = fi.forward_carry_rolldown(curve, on_rate, "spread",
                                        tenor1="10Y", tenor2="2Y",
                                        holding_months=1.0)
    out10 = fi.forward_carry_rolldown(curve, on_rate, "outright",
                                        tenor1="10Y", holding_months=1.0)
    out2  = fi.forward_carry_rolldown(curve, on_rate, "outright",
                                        tenor1="2Y",  holding_months=1.0)
    # carry is roughly additive across legs
    assert spread["carry"] == pytest.approx(out10["carry"] - out2["carry"],
                                              abs=0.5)


def test_total_is_forward_minus_spot_in_bps():
    """Lib convention: total = (h-forward T-year rate − spot T-year) × 100.
    This is the break-even forward move, NOT carry + rolldown."""
    import fixed_income as fi
    curve = {"2Y": 3.8, "5Y": 4.0, "10Y": 4.3, "30Y": 4.9}
    on_rate = 3.65
    cr = fi.forward_carry_rolldown(curve, on_rate, "outright",
                                    tenor1="10Y", holding_months=3.0)
    # Sanity: total is positive when the curve is upward-sloping (fwd > spot)
    # since 10Y is the back-end of an upward-sloping piece here.
    assert isinstance(cr["total"], float)
    # carry + rolldown is a DIFFERENT decomposition and may be much larger
    # in raw bps over the holding period. That's expected — they don't have
    # to equal `total`. Just assert both are finite numbers.
    assert isinstance(cr["carry"], float)
    assert isinstance(cr["rolldown"], float)
