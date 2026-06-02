"""Math-correctness regression tests for the fixed_income library.

These guard the invariants that took real audit time to establish — the
15× convexity bug fix in particular. Run from the project root with:

    ./.venv/bin/python -m pytest tests/ -v

The bar isn't full numerical accuracy (the dashboard already computes
these against live yields); it's *invariants* that would break ranking
or P&L attribution if they ever flipped sign or changed by a factor of
10.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# Make the repo root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import fixed_income as fi


# ── DV01 ─────────────────────────────────────────────────────────────────
class TestDV01:
    def test_dv01_positive(self):
        """Par DV01 is always positive for a receiver."""
        assert fi.dv01_par(tenor_years=5.0,  par_yield_pct=4.0) > 0
        assert fi.dv01_par(tenor_years=10.0, par_yield_pct=4.0) > 0
        assert fi.dv01_par(tenor_years=30.0, par_yield_pct=4.0) > 0

    def test_dv01_monotonic_in_tenor(self):
        """Longer tenor → higher DV01 at the same yield level."""
        d2  = fi.dv01_par(2.0,  4.0)
        d5  = fi.dv01_par(5.0,  4.0)
        d10 = fi.dv01_par(10.0, 4.0)
        d30 = fi.dv01_par(30.0, 4.0)
        assert d2 < d5 < d10 < d30

    def test_dv01_order_of_magnitude_10y_on_1m_notional(self):
        """DV01 of a 10y par bond at 4% on $1M is in the $700–$900 range
        ($ per bp). If a future change makes it $7 or $80,000, a units bug
        has been introduced."""
        dv01 = fi.dv01_par(10.0, 4.0)   # default notional = $1M
        assert 500 < dv01 < 1500, (
            f"10y DV01 = ${dv01:.2f} per bp on $1M — outside typical "
            "500–1500 range. Suggests a units bug."
        )

    def test_dv01_scales_linearly_with_notional(self):
        """$10M position should have 10× the DV01 of $1M."""
        d_1m  = fi.dv01_par(10.0, 4.0, notional=1_000_000)
        d_10m = fi.dv01_par(10.0, 4.0, notional=10_000_000)
        assert math.isclose(d_10m / d_1m, 10.0, rel_tol=1e-6)

    def test_dv01_falls_with_yield(self):
        """Higher yield → smaller DV01 (price-yield convexity → DV01 ↓)."""
        d_low  = fi.dv01_par(10.0, 2.0)
        d_high = fi.dv01_par(10.0, 8.0)
        assert d_low > d_high


# ── Convexity ────────────────────────────────────────────────────────────
class TestConvexity:
    def test_par_convexity_positive(self):
        """Par convexity is positive for a fixed-rate bond."""
        assert fi.convexity_par(5.0,  4.0) > 0
        assert fi.convexity_par(10.0, 4.0) > 0
        assert fi.convexity_par(30.0, 4.0) > 0

    def test_pickup_bps_positive_for_receiver(self):
        """Receiver convexity pickup in bps-eq is positive (½·C·dy² ≥ 0)."""
        pickup = fi.convexity_pickup_bps(
            tenor_years=10.0, par_yield_pct=4.0, yield_move_bps=100.0,
        )
        assert pickup > 0

    def test_pickup_bps_scales_with_move_squared(self):
        """Convexity is ½·C·dy² — doubling dy should ~4× the pickup."""
        p_low  = fi.convexity_pickup_bps(10.0, 4.0, yield_move_bps=50.0)
        p_high = fi.convexity_pickup_bps(10.0, 4.0, yield_move_bps=100.0)
        ratio = p_high / p_low
        assert 3.8 < ratio < 4.2, (
            f"yield_move doubled but pickup scaled {ratio:.3f}× "
            "(expected exactly 4×). Quadratic dependence may have broken."
        )

    def test_pickup_bps_NOT_overstated_15x(self):
        """Regression test for the 15× convexity overstatement bug.

        Before the fix, the convexity term in a 10y at 4% with a 100 bp
        move was being computed as price-bps and then added to yield-bps
        carry/roll, overstating Sharpe ~15×. Post-fix the pickup is yield-
        bps-equivalent, normalised through DV01.

        Sanity bound: a 10y at 4% with 100 bp move gives ~0.5 bp of
        yield-equivalent convexity. If this exceeds 10 bp, the units bug
        is back.
        """
        pickup = fi.convexity_pickup_bps(10.0, 4.0, yield_move_bps=100.0)
        assert pickup < 10, (
            f"Convexity pickup = {pickup:.2f} bp/yr — suspiciously large. "
            "The 15× bug may have regressed. Expected ≲ 1 bp/yr for these "
            "inputs (10y, 4%, 100 bp move)."
        )


# ── Spread / fly convexity ──────────────────────────────────────────────
class TestSpreadConvexity:
    def test_receive_long_curve_positive_net_convexity(self):
        """Receive 10y / pay 2y: long leg dominates → positive net
        convexity. (DV01-neutral structure.)"""
        net = fi.spread_convexity_bps(
            short_tenor=2.0,  short_yield_pct=4.0,
            long_tenor=10.0,  long_yield_pct=4.0,
            yield_move_bps=100.0,
        )
        assert net > 0

    def test_fly_receive_belly_negative_net_convexity(self):
        """Receive-belly 2/5/10 fly: long-end wings short more convexity
        than the belly carries → net is NEGATIVE. This is the result the
        Methodology page §7 sign-convention table describes."""
        net = fi.fly_convexity_bps(
            w1_tenor=2.0,  w1_yield_pct=4.0,
            b_tenor=5.0,   b_yield_pct=4.0,
            w2_tenor=10.0, w2_yield_pct=4.0,
            yield_move_bps=100.0,
        )
        assert net < 0, (
            f"Receive-belly 2/5/10 fly net convexity = {net:.4f} (expected "
            "negative). Sign convention may have flipped."
        )


# ── Transaction costs ───────────────────────────────────────────────────
class TestTransactionCosts:
    def test_outright_positive_finite(self):
        c = fi.tcost_outright_bps(10.0)
        assert 0 < c < 5   # plausible bid/ask half-spread bands

    def test_curve_at_least_outright(self):
        """Two-leg curve should cost ≥ a single outright."""
        c_curve   = fi.tcost_curve_bps(2.0, 10.0)
        c_outright = fi.tcost_outright_bps(10.0)
        assert c_curve >= c_outright

    def test_fly_costs_more_than_curve(self):
        """Three-leg fly should cost more than a curve."""
        c_fly   = fi.tcost_fly_bps(2.0, 5.0, 10.0)
        c_curve = fi.tcost_curve_bps(2.0, 10.0)
        assert c_fly >= c_curve

    def test_bid_ask_scales_with_tenor(self):
        """Longer tenor → wider bid/ask (less liquid further out)."""
        c2  = fi.bid_ask_bps(2.0)
        c30 = fi.bid_ask_bps(30.0)
        assert c2 <= c30


# ── Total return / addition invariant ───────────────────────────────────
class TestTotalReturn:
    def test_total_return_is_sum(self):
        """Helper exists and is purely additive."""
        assert fi.total_return(carry_bps=15.0, rolldown_bps=5.0) == 20.0

    def test_total_return_handles_negative(self):
        """Negative rolldown reduces total return."""
        assert fi.total_return(20.0, -5.0) == 15.0


# ── Smoke: importability + version ──────────────────────────────────────
def test_fi_exposes_documented_helpers():
    """The Methodology page references these names. Don't let a rename
    silently break the docs."""
    for name in (
        "dv01_par", "convexity_par",
        "convexity_pickup_bps", "spread_convexity_bps", "fly_convexity_bps",
        "tcost_outright_bps", "tcost_curve_bps", "tcost_fly_bps",
        "bid_ask_bps", "total_return",
    ):
        assert hasattr(fi, name), (
            f"fixed_income.{name} is gone — Methodology page links break."
        )
