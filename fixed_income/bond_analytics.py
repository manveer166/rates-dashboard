"""
bond_analytics.py — Bond mathematics: DV01, convexity, asset swaps, box swaps,
                    cross-currency basis, and swap spreads.

Key concepts
------------
DV01 (Dollar Value of 01)
    The change in bond/swap price for a 1bp parallel shift in yield.
    For a fixed-rate bond: DV01 ≈ -modified_duration × dirty_price × notional × 0.0001

Convexity
    Second-order sensitivity: for large yield moves the actual price change
    exceeds the DV01 approximation. Favourable for receivers, unfavourable for payers.

Asset Swap Spread (ASW)
    The spread over LIBOR/SOFR that equates the NPV of a fixed-rate bond's cash
    flows to its market price. Measures bond cheapness relative to swaps.
    ASW > 0 → bond yields more than the swap curve → cheap.

Box Swap (Swap Spread Spread)
    The difference between two swap spreads at different tenors.
    E.g. (10Y swap spread) − (2Y swap spread) = 2s10s box.
    Used to trade the slope of the swap-spread curve.

Cross-Currency Basis
    The additional spread paid/received when swapping notional across currencies
    in a cross-currency swap. Negative basis = USD funding premium.
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Dict, Tuple
from scipy.optimize import brentq


# ---------------------------------------------------------------------------
# Cash-flow schedules
# ---------------------------------------------------------------------------

def bond_cashflows(
    coupon_rate: float,
    maturity_years: float,
    notional: float = 100.0,
    freq: int = 2,
) -> List[Tuple[float, float]]:
    """
    Generate (time_years, cashflow) pairs for a fixed-rate bullet bond.

    Parameters
    ----------
    coupon_rate   : annual coupon in % (e.g. 4.5)
    maturity_years: years to maturity
    notional      : face value (default 100)
    freq          : coupons per year (2 = semi-annual, US convention)
    """
    coupon_pmt = notional * (coupon_rate / 100) / freq
    n_periods = int(round(maturity_years * freq))
    dt = 1.0 / freq
    cfs = []
    for i in range(1, n_periods):
        cfs.append((i * dt, coupon_pmt))
    # Final coupon + principal
    cfs.append((maturity_years, coupon_pmt + notional))
    return cfs


# ---------------------------------------------------------------------------
# Bond pricing and yield
# ---------------------------------------------------------------------------

def bond_price(
    cashflows: List[Tuple[float, float]],
    ytm: float,
    freq: int = 2,
) -> float:
    """
    Price a bond given yield-to-maturity (YTM) using semi-annual compounding.

    P = sum [ CF_t / (1 + ytm/freq)^(t * freq) ]
    """
    r = ytm / 100.0
    price = 0.0
    for t, cf in cashflows:
        price += cf / (1 + r / freq) ** (t * freq)
    return price


def bond_ytm(
    cashflows: List[Tuple[float, float]],
    price: float,
    freq: int = 2,
    guess: float = 4.0,
) -> float:
    """
    Solve for YTM given market price using Brent's method.
    Returns YTM in %.
    """
    def objective(ytm_pct):
        return bond_price(cashflows, ytm_pct, freq) - price

    try:
        return float(brentq(objective, 0.001, 50.0, xtol=1e-8))
    except ValueError:
        return np.nan


# ---------------------------------------------------------------------------
# Duration and DV01
# ---------------------------------------------------------------------------

def modified_duration(
    cashflows: List[Tuple[float, float]],
    ytm: float,
    freq: int = 2,
) -> float:
    """
    Modified duration of a bond.

    ModDur = MacaulayDuration / (1 + ytm / (freq * 100))
    """
    r = ytm / 100.0
    price = bond_price(cashflows, ytm, freq)
    mac_dur = 0.0
    for t, cf in cashflows:
        pv_cf = cf / (1 + r / freq) ** (t * freq)
        mac_dur += t * pv_cf
    mac_dur /= price
    mod_dur = mac_dur / (1 + r / freq)
    return mod_dur


def dv01_bond(
    cashflows: List[Tuple[float, float]],
    ytm: float,
    notional: float = 1_000_000.0,
    freq: int = 2,
) -> float:
    """
    DV01 of a bond position = change in value for 1bp increase in yield.

    DV01 = -ModDur × Dirty_Price × Notional × 0.0001

    Returns DV01 in dollars (negative for long bond, i.e. yields up → price down).
    """
    price = bond_price(cashflows, ytm, freq) / 100.0  # as decimal
    md = modified_duration(cashflows, ytm, freq)
    return -md * price * notional * 0.0001


def convexity(
    cashflows: List[Tuple[float, float]],
    ytm: float,
    freq: int = 2,
) -> float:
    """
    Convexity of a bond.

    Conv = [ sum( t*(t+1/freq) * CF_t / (1+r/freq)^(t*freq+2) ) ] / Price

    Higher convexity → more price appreciation when yields fall than
    price loss when yields rise (positive for long bond).
    """
    r = ytm / 100.0
    price = bond_price(cashflows, ytm, freq)
    conv = 0.0
    for t, cf in cashflows:
        n = t * freq
        conv += cf * n * (n + 1) / (1 + r / freq) ** (n + 2)
    conv /= (price * freq ** 2)
    return conv


def price_change_approx(
    dv01: float,
    convexity_val: float,
    delta_yield_bps: float,
    notional: float = 1_000_000.0,
) -> float:
    """
    Approximate price change using duration + convexity.

    ΔP ≈ DV01 × Δy + 0.5 × Convexity × (Δy)² × P
    where Δy in bps.
    """
    dy = delta_yield_bps / 10000.0  # convert bps → decimal
    delta_p = dv01 * delta_yield_bps + 0.5 * convexity_val * dy ** 2 * notional
    return delta_p


# ---------------------------------------------------------------------------
# Asset Swap Spread
# ---------------------------------------------------------------------------

def asset_swap_spread(
    bond_cashflows: List[Tuple[float, float]],
    bond_price_pct: float,
    swap_curve_tenors: List[float],
    swap_curve_rates: List[float],
    freq: int = 2,
) -> float:
    """
    Par asset swap spread: spread over swap curve that equates bond NPV to price.

    Method: solve for spread s such that:
      sum( (CF_t + s/freq × notional) / discount_factor(t) ) = bond_price

    where discount factors come from the swap (SOFR) curve.

    Returns spread in bps.
    """
    notional = 100.0
    price = bond_price_pct  # as % of par

    def _discount(t: float) -> float:
        """Linear-interpolated continuous discount factor from swap curve."""
        r_pct = np.interp(t, swap_curve_tenors, swap_curve_rates)
        return np.exp(-r_pct / 100.0 * t)

    # NPV of fixed leg at zero spread
    npv_fixed = sum(cf * _discount(t) for t, cf in bond_cashflows)
    # NPV of floating notional exchange
    # Par ASW: floating leg NPV = notional at start - notional at end (discounted)
    t_end = bond_cashflows[-1][0]
    npv_float_par = notional * (1 - _discount(t_end))

    # Solve for spread: sum( s/freq × notional × discount(t) ) = npv_fixed - price
    annuity = sum(_discount(t) * (notional / freq) for t, _ in bond_cashflows)

    if annuity == 0:
        return np.nan

    # ASW spread in decimal → bps
    asw_decimal = (npv_fixed - price) / annuity
    return round(asw_decimal * 10000, 2)  # bps


# ---------------------------------------------------------------------------
# Swap Spread
# ---------------------------------------------------------------------------

def swap_spread(swap_rate_pct: float, treasury_yield_pct: float) -> float:
    """
    Swap spread = swap rate - Treasury yield (same tenor), in bps.
    Positive swap spread means swaps trade at a premium to Treasuries.
    """
    return (swap_rate_pct - treasury_yield_pct) * 100


def swap_spread_series(
    swap_df: pd.DataFrame,
    treasury_df: pd.DataFrame,
    tenor: str,
) -> pd.Series:
    """
    Time series of swap spread for a given tenor.

    Parameters
    ----------
    swap_df     : DataFrame with swap rate columns, e.g. '10Y'
    treasury_df : DataFrame with treasury yield columns, e.g. '10Y'
    tenor       : column name present in both DataFrames
    """
    aligned = pd.concat([swap_df[tenor], treasury_df[tenor]], axis=1)
    aligned.columns = ["swap", "treasury"]
    aligned = aligned.dropna()
    return (aligned["swap"] - aligned["treasury"]) * 100


# ---------------------------------------------------------------------------
# Box swap (swap spread of spreads)
# ---------------------------------------------------------------------------

def box_swap(
    swap_spread_long: float,
    swap_spread_short: float,
) -> float:
    """
    Box swap = swap_spread(long tenor) - swap_spread(short tenor), in bps.

    E.g. 10Y swap spread = 20bps, 2Y swap spread = 30bps → box = -10bps.
    Box normalises for absolute rate level moves by trading the *slope*
    of the swap spread curve.
    """
    return swap_spread_long - swap_spread_short


def box_swap_series(
    swap_df: pd.DataFrame,
    treasury_df: pd.DataFrame,
    long_tenor: str,
    short_tenor: str,
) -> pd.Series:
    """Time series of the box swap for two tenors."""
    ss_long = swap_spread_series(swap_df, treasury_df, long_tenor)
    ss_short = swap_spread_series(swap_df, treasury_df, short_tenor)
    aligned = pd.concat([ss_long, ss_short], axis=1).dropna()
    aligned.columns = [long_tenor, short_tenor]
    result = aligned[long_tenor] - aligned[short_tenor]
    result.name = f"{long_tenor}/{short_tenor} Box"
    return result


# ---------------------------------------------------------------------------
# Cross-currency basis
# ---------------------------------------------------------------------------

def xccy_basis_carry(
    domestic_rate: float,
    foreign_rate: float,
    basis_spread_bps: float,
    fx_forward_premium_bps: float = 0.0,
    holding_months: float = 1.0,
) -> float:
    """
    Net carry on a cross-currency basis swap (receive foreign, pay domestic + basis).

    carry = (foreign_rate - domestic_rate + basis_spread) * (holding_months/12) * 100
            + fx_forward_premium

    All rates in %; basis_spread and fx_forward_premium in bps.
    Returns carry in bps over the holding period.
    """
    rate_diff_bps = (foreign_rate - domestic_rate) * 100
    total_carry = (rate_diff_bps + basis_spread_bps + fx_forward_premium_bps) * (holding_months / 12)
    return round(total_carry, 2)


def xccy_carry_table(
    rate_df: pd.DataFrame,
    basis_df: pd.DataFrame,
    currency_pairs: List[Tuple[str, str]],
    tenor: str = "10Y",
    holding_months: float = 1.0,
) -> pd.DataFrame:
    """
    Build a cross-currency carry table for multiple pairs.

    Parameters
    ----------
    rate_df        : DataFrame with columns like 'USD_10Y', 'EUR_10Y', etc.
    basis_df       : DataFrame with XCCY basis columns like 'EUR_USD_10Y' (in bps)
    currency_pairs : list of (domestic_ccy, foreign_ccy) tuples
    tenor          : maturity tenor
    """
    rows = []
    for dom, fgn in currency_pairs:
        dom_col = f"{dom}_{tenor}"
        fgn_col = f"{fgn}_{tenor}"
        basis_col = f"{fgn}_{dom}_{tenor}"

        if dom_col not in rate_df.columns or fgn_col not in rate_df.columns:
            continue

        dom_rate = float(rate_df[dom_col].dropna().iloc[-1])
        fgn_rate = float(rate_df[fgn_col].dropna().iloc[-1])
        basis = float(basis_df[basis_col].dropna().iloc[-1]) if basis_col in basis_df.columns else 0.0

        carry = xccy_basis_carry(dom_rate, fgn_rate, basis, 0.0, holding_months)
        rows.append({
            "Pair": f"{fgn}/{dom}",
            f"{dom} {tenor} (%)": round(dom_rate, 3),
            f"{fgn} {tenor} (%)": round(fgn_rate, 3),
            "Basis (bps)": round(basis, 1),
            "Carry (bps)": carry,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Quick analytics on a bond given just yield + maturity (no cashflow schedule)
# ---------------------------------------------------------------------------

def quick_analytics(
    coupon_rate: float,
    maturity_years: float,
    ytm: float,
    notional: float = 1_000_000.0,
    freq: int = 2,
) -> Dict[str, float]:
    """
    Compute price, DV01, convexity for a plain vanilla bond.

    Parameters
    ----------
    coupon_rate   : coupon in % (e.g. 4.5)
    maturity_years: years to maturity
    ytm           : yield-to-maturity in % (e.g. 4.8)
    notional      : face value in dollars
    freq          : coupon frequency

    Returns dict with Price, DV01 ($), Modified Duration, Convexity.
    """
    cfs = bond_cashflows(coupon_rate, maturity_years, 100.0, freq)
    price = bond_price(cfs, ytm, freq)
    md = modified_duration(cfs, ytm, freq)
    dv = dv01_bond(cfs, ytm, notional, freq)
    conv = convexity(cfs, ytm, freq)

    return {
        "Price (%)": round(price, 4),
        "YTM (%)": round(ytm, 4),
        "Modified Duration": round(md, 4),
        f"DV01 ($ per {int(notional/1e6)}M)": round(dv, 0),
        "Convexity": round(conv, 4),
    }
