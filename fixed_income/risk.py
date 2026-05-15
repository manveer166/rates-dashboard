"""
risk.py — Single source of truth for DV01 / convexity / transaction costs.

Why this module exists
----------------------
Previously the code had:
  • `trade_setup.approx_dv01()` — a closed-form modified-duration shortcut
  • `bond_analytics.dv01_bond()` + `convexity()` — proper cash-flow-based math
…and the scanner / backtester / trade builder used the shortcut, while the
proper math sat unused. This module makes the proper math the default and
exposes a small, consistent API every consumer can call.

What's still an approximation
-----------------------------
We assume each tenor's observed par yield IS the yield-to-maturity of a
hypothetical par bond at that tenor with semi-annual coupons (USD swap /
Treasury convention). No multi-curve OIS discounting; no separate
collateral/funding curve. Standard for research-grade analytics — see the
Methodology page in the dashboard for the full list of assumptions.

Conventions
-----------
  • Yields in %                 (e.g. 4.46 for 4.46%)
  • DV01 in $ per bp per $1M notional unless stated otherwise
  • Convexity in standard bond-units (price-pct change per yield-pct² × 1e4)
  • All math uses semi-annual compounding (freq=2)
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

from .bond_analytics import bond_cashflows, bond_price, modified_duration


# ---------------------------------------------------------------------------
# Core risk per $1M face on a par bond at given tenor + yield
# ---------------------------------------------------------------------------

def dv01_par(tenor_years: float,
             par_yield_pct: float,
             notional: float = 1_000_000.0,
             freq: int = 2) -> float:
    """DV01 of a par bond at given tenor + yield. $ per bp.

    For a par bond, dirty price = 100 and DV01 = ModDur × Price × Notional × bp.
    Equivalent to the closed-form `(1 − (1+y/f)^(−fT))/y × N × 1e-4` — this
    function exists as the named entry point so all callers go through the
    same math.
    """
    cfs = bond_cashflows(coupon_rate=par_yield_pct,
                         maturity_years=tenor_years,
                         notional=100.0, freq=freq)
    md = modified_duration(cfs, par_yield_pct, freq=freq)
    price_decimal = bond_price(cfs, par_yield_pct, freq=freq) / 100.0
    return md * price_decimal * notional * 1e-4


def convexity_par(tenor_years: float,
                  par_yield_pct: float,
                  freq: int = 2) -> float:
    """Convexity of a par bond at given tenor + yield (unitless 'C').

    Standard definition: C = (1/P) × Σ_i (n_i (n_i+1) / freq²) × CF_i / (1+y/f)^(n_i+2)
    where n_i = t_i × freq. Returned in bond-convexity units; for a yield
    move of dy bps the price-pct change from convexity is
        0.5 × C × (dy/1e4)²    (i.e. ½·C·dy²)
    """
    cfs = bond_cashflows(coupon_rate=par_yield_pct,
                         maturity_years=tenor_years,
                         notional=100.0, freq=freq)
    # Inlined version of bond_analytics.convexity to avoid the circular
    # import surprise when this module loads first.
    r = par_yield_pct / 100.0
    price = bond_price(cfs, par_yield_pct, freq=freq)
    conv = 0.0
    for t, cf in cfs:
        n = t * freq
        conv += cf * n * (n + 1) / (1 + r / freq) ** (n + 2)
    return conv / (price * freq ** 2)


def convexity_pickup_dollars(tenor_years: float,
                              par_yield_pct: float,
                              yield_move_bps: float,
                              notional: float = 1_000_000.0,
                              freq: int = 2) -> float:
    """Dollar P&L from the convexity term for a yield move of `yield_move_bps`.

    Receiver convention: positive return when yields FALL. Convexity is
    always favourable for a long-bond / receiver leg, regardless of the
    move's direction (½·C·dy² ≥ 0).
    """
    conv = convexity_par(tenor_years, par_yield_pct, freq=freq)
    dy = yield_move_bps / 1e4         # bps → decimal
    # Price change from convexity, as fraction of notional
    price_chg_frac = 0.5 * conv * dy * dy
    return price_chg_frac * notional


def convexity_pickup_bps(tenor_years: float,
                          par_yield_pct: float,
                          yield_move_bps: float,
                          notional: float = 1_000_000.0,
                          freq: int = 2) -> float:
    """Convexity P&L expressed as bps of equivalent yield move at the same DV01.

    Lets you add convexity directly to a carry+rolldown total in bps:
        E[Ret]_bps = carry + rolldown + convexity_pickup_bps
    """
    dv01 = dv01_par(tenor_years, par_yield_pct, notional=notional, freq=freq)
    if dv01 <= 0:
        return 0.0
    dollar_pickup = convexity_pickup_dollars(
        tenor_years, par_yield_pct, yield_move_bps, notional=notional, freq=freq)
    return dollar_pickup / dv01


# ---------------------------------------------------------------------------
# Multi-leg structure convexity (DV01-neutral curves and flies)
# ---------------------------------------------------------------------------

def spread_convexity_bps(short_tenor: float, short_yield_pct: float,
                          long_tenor: float, long_yield_pct: float,
                          yield_move_bps: float,
                          freq: int = 2) -> float:
    """Net convexity P&L of a DV01-neutral receive-long / pay-short curve trade,
    expressed as bps of yield on the LONG leg.

    Sign convention: receive the long tenor (positive convexity), pay the
    short tenor (negative convexity, but small). Net is positive for
    typical curve receivers (10Y dominates 2Y).
    """
    dv01_short = dv01_par(short_tenor, short_yield_pct, freq=freq)
    dv01_long  = dv01_par(long_tenor,  long_yield_pct,  freq=freq)
    if dv01_long <= 0 or dv01_short <= 0:
        return 0.0
    # DV01-neutral: pay short with notional ratio = dv01_long / dv01_short
    ratio = dv01_long / dv01_short
    pickup_long  = convexity_pickup_dollars(long_tenor,  long_yield_pct,
                                              yield_move_bps, notional=1e6, freq=freq)
    pickup_short = convexity_pickup_dollars(short_tenor, short_yield_pct,
                                              yield_move_bps,
                                              notional=ratio * 1e6, freq=freq)
    net_dollar = pickup_long - pickup_short   # receive long, pay short
    return net_dollar / dv01_long


def fly_convexity_bps(w1_tenor: float, w1_yield_pct: float,
                       b_tenor:  float, b_yield_pct:  float,
                       w2_tenor: float, w2_yield_pct: float,
                       yield_move_bps: float,
                       freq: int = 2) -> float:
    """Net convexity P&L of a DV01-neutral receive-belly / pay-wings fly,
    expressed as bps of yield on the BELLY leg.

    For typical 2/5/10 receivers the short wings (especially long-end 10Y+)
    dominate; net convexity is usually NEGATIVE. This is a real risk the
    scanner should surface.
    """
    dv01_w1 = dv01_par(w1_tenor, w1_yield_pct, freq=freq)
    dv01_b  = dv01_par(b_tenor,  b_yield_pct,  freq=freq)
    dv01_w2 = dv01_par(w2_tenor, w2_yield_pct, freq=freq)
    if min(dv01_w1, dv01_b, dv01_w2) <= 0:
        return 0.0
    # DV01-neutral: belly notional 1, each wing notional 0.5 × dv01_b/dv01_wi
    r1 = 0.5 * dv01_b / dv01_w1
    r2 = 0.5 * dv01_b / dv01_w2
    pickup_b  = convexity_pickup_dollars(b_tenor,  b_yield_pct,
                                           yield_move_bps, notional=1e6, freq=freq)
    pickup_w1 = convexity_pickup_dollars(w1_tenor, w1_yield_pct,
                                           yield_move_bps, notional=r1 * 1e6, freq=freq)
    pickup_w2 = convexity_pickup_dollars(w2_tenor, w2_yield_pct,
                                           yield_move_bps, notional=r2 * 1e6, freq=freq)
    net_dollar = pickup_b - pickup_w1 - pickup_w2
    return net_dollar / dv01_b


# ---------------------------------------------------------------------------
# Transaction cost lookup — market-standard round-trip bid/ask widths.
# These are the bps you pay to enter AND exit a position. Values are
# practitioner consensus for USD on-the-run benchmarks circa 2024-26.
# Off-the-run and long-end widen materially.
# ---------------------------------------------------------------------------

# Per-leg bid/ask in bps yield (one-way). Round-trip = 2x.
_BID_ASK_BPS_TREASURY = {
    "1Y":  0.5,  "2Y":  0.5,  "3Y":  0.5,
    "5Y":  0.5,  "7Y":  0.7,  "10Y": 0.5,
    "20Y": 1.5,  "30Y": 1.5,  "40Y": 2.0,
}
_BID_ASK_BPS_SWAP = {
    "1Y":  0.25, "2Y":  0.25, "3Y":  0.25,
    "5Y":  0.25, "7Y":  0.50, "10Y": 0.25,
    "20Y": 0.75, "30Y": 0.75,
}


def _tenor_to_label(t: float) -> str:
    """Map float tenor (years) to nearest standard tenor label."""
    labels = sorted(_BID_ASK_BPS_TREASURY.keys(),
                    key=lambda s: float(s.replace("Y", "")))
    target = float(t)
    best = min(labels, key=lambda lbl: abs(float(lbl.replace("Y", "")) - target))
    return best


def bid_ask_bps(tenor_years: float, instrument: str = "treasury") -> float:
    """One-way bid/ask spread in bps for a single leg of the given tenor.

    instrument: "treasury" (default) or "swap". Swaps are tighter than
    cash because of the depth of dealer interest at standard quarterly
    fixings.
    """
    table = (_BID_ASK_BPS_SWAP if instrument == "swap"
             else _BID_ASK_BPS_TREASURY)
    return float(table.get(_tenor_to_label(tenor_years), 1.0))


def round_trip_cost_bps(legs: List[Tuple[float, float]],
                         instrument: str = "treasury") -> float:
    """Total round-trip transaction cost for a multi-leg trade.

    legs: list of (tenor_years, dv01_weight) tuples. dv01_weight = the leg's
    fraction of total trade DV01 (sums to 1 for outright; spread = 1+ratio
    normalised; fly = 1+0.5+0.5 normalised).

    Returns bps of yield-equivalent cost per unit of leg-1 DV01.
    """
    if not legs:
        return 0.0
    return 2.0 * sum(bid_ask_bps(t, instrument) * w for t, w in legs)


# Convenience for the standard shapes the scanner / backtester uses:

def tcost_outright_bps(tenor_years: float, instrument: str = "treasury") -> float:
    """Round-trip transaction cost for an outright (1 leg)."""
    return 2.0 * bid_ask_bps(tenor_years, instrument)


def tcost_curve_bps(short_tenor: float, long_tenor: float,
                    short_yield: float = 4.0, long_yield: float = 4.0,
                    instrument: str = "treasury") -> float:
    """Round-trip cost for a DV01-neutral curve. Bps of yield-equivalent
    on the long leg."""
    dv01_s = dv01_par(short_tenor, short_yield)
    dv01_l = dv01_par(long_tenor,  long_yield)
    if dv01_l <= 0 or dv01_s <= 0:
        return 0.0
    ratio_short = dv01_l / dv01_s   # short notional in units of long notional
    # The short leg costs bid_ask_short × ratio bps_of_short_yield, which is
    # bid_ask_short bps of THE SHORT TENOR; to compare on the long leg we
    # need to convert via DV01s — but bps are bps, the legs are DV01-matched
    # so the cost in $ is bid_ask_long × dv01_long + bid_ask_short × dv01_short × ratio.
    # In bps-of-long-yield that's: bid_ask_long + bid_ask_short × (dv01_short × ratio / dv01_long)
    # = bid_ask_long + bid_ask_short × 1 = bid_ask_long + bid_ask_short.
    return 2.0 * (bid_ask_bps(long_tenor, instrument)
                  + bid_ask_bps(short_tenor, instrument))


def tcost_fly_bps(w1_tenor: float, b_tenor: float, w2_tenor: float,
                  instrument: str = "treasury") -> float:
    """Round-trip cost for a DV01-neutral fly. Bps of yield on the belly.

    Same DV01-equivalence argument as the curve: each leg's bid/ask
    expressed in bps yield contributes one-for-one to the belly-bps cost
    (the wings' notional ratios convert the dollar bid/ask back to the
    same bp yield equivalent on the belly)."""
    return 2.0 * (bid_ask_bps(b_tenor, instrument)
                  + bid_ask_bps(w1_tenor, instrument)
                  + bid_ask_bps(w2_tenor, instrument))


# ---------------------------------------------------------------------------
# Backwards-compatible alias used across the codebase
# ---------------------------------------------------------------------------

def approx_dv01(tenor_years: float, rate_pct: float = 4.0) -> float:
    """Alias of dv01_par. Kept so existing call sites keep working
    while we migrate them to the named function over time."""
    return dv01_par(tenor_years, rate_pct)
