"""Tests for the risk module (DV01, convexity, transaction costs)."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import math

import pytest


# ── DV01 ─────────────────────────────────────────────────────────────────

def test_dv01_matches_closed_form_for_par_bond():
    """For a par bond, DV01 = ModDur × Price × Notional × 1e-4 should equal
    the closed-form `(1 − (1+y/2)^(−2T))/y × N × 1e-4`."""
    import fixed_income as fi

    for tenor, yld in [(2, 4.0), (5, 4.0), (10, 4.0), (30, 4.0),
                        (10, 2.5), (10, 6.0)]:
        r = yld / 100.0
        n = 2 * tenor
        closed_form = (1 - (1 + r / 2) ** (-n)) / r * 1_000_000 * 1e-4
        computed = fi.dv01_par(tenor, yld)
        assert math.isclose(closed_form, computed, rel_tol=1e-3), (
            f"DV01 mismatch at tenor={tenor}, yld={yld}: "
            f"closed-form={closed_form}, computed={computed}"
        )


def test_dv01_grows_with_tenor():
    """DV01 should be monotone in tenor at constant yield."""
    import fixed_income as fi
    yld = 4.0
    dv01s = [fi.dv01_par(t, yld) for t in [1, 2, 5, 10, 20, 30]]
    assert dv01s == sorted(dv01s)


def test_dv01_decreases_with_higher_yield():
    """Higher yield → lower DV01 (steeper discounting)."""
    import fixed_income as fi
    tenor = 10
    yields = [2.0, 4.0, 6.0, 8.0]
    dv01s = [fi.dv01_par(tenor, y) for y in yields]
    assert dv01s == sorted(dv01s, reverse=True)


# ── Convexity ────────────────────────────────────────────────────────────

def test_convexity_positive():
    """Convexity is always positive for a long bond."""
    import fixed_income as fi
    for tenor in [2, 5, 10, 30]:
        c = fi.convexity_par(tenor, 4.0)
        assert c > 0


def test_convexity_grows_with_tenor_quadratically():
    """Convexity scales roughly with T² for the par bond."""
    import fixed_income as fi
    c5 = fi.convexity_par(5, 4.0)
    c10 = fi.convexity_par(10, 4.0)
    c30 = fi.convexity_par(30, 4.0)
    # 10/5 ratio should be ~4 (quadratic); 30/10 ratio should be ~5-6
    assert 3.0 < c10 / c5 < 4.5
    assert 4.5 < c30 / c10 < 7.0


def test_convexity_pickup_zero_at_zero_move():
    """½·C·dy² = 0 when dy = 0."""
    import fixed_income as fi
    assert fi.convexity_pickup_dollars(10, 4.0, 0.0) == 0.0
    assert fi.convexity_pickup_bps(10, 4.0, 0.0) == 0.0


def test_convexity_pickup_symmetric_in_move_sign():
    """½·C·dy² is symmetric — long convexity helps the receiver either way."""
    import fixed_income as fi
    up = fi.convexity_pickup_dollars(10, 4.0, +50)
    dn = fi.convexity_pickup_dollars(10, 4.0, -50)
    assert math.isclose(up, dn, rel_tol=1e-9)


def test_fly_convexity_negative_when_wings_dominate():
    """Receive a belly fly with long-end wings → typically SHORT convexity."""
    import fixed_income as fi
    # 2/5/30 fly receiver: belly is 5Y, wings are 2Y + 30Y. The 30Y wing
    # has much more convexity than the 5Y belly + 2Y wing combined.
    conv = fi.fly_convexity_bps(2, 4.0, 5, 4.0, 30, 5.0, yield_move_bps=50)
    assert conv < 0, f"Expected negative convexity for fly with 30Y wing, got {conv}"


# ── Transaction costs ────────────────────────────────────────────────────

def test_tcost_round_trip_is_double_bid_ask():
    """Round-trip = 2× one-way bid/ask for a single leg."""
    import fixed_income as fi
    one_way = fi.bid_ask_bps(10, instrument="treasury")
    rt = fi.tcost_outright_bps(10, instrument="treasury")
    assert math.isclose(rt, 2.0 * one_way, rel_tol=1e-9)


def test_swaps_tighter_than_treasury():
    """Practitioner consensus: swaps are tighter than cash for benchmark tenors."""
    import fixed_income as fi
    for tenor in [2, 5, 10]:
        sw = fi.bid_ask_bps(tenor, instrument="swap")
        tr = fi.bid_ask_bps(tenor, instrument="treasury")
        assert sw <= tr, f"swap should be tighter at {tenor}Y"


def test_long_end_wider_than_belly():
    """30Y bid/ask should be wider than 5Y."""
    import fixed_income as fi
    assert fi.bid_ask_bps(30, "treasury") > fi.bid_ask_bps(5, "treasury")
