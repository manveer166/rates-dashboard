"""
carry_rolldown.py — Carry and rolldown analytics for interest rate swaps and bonds.

Definitions
-----------
Carry     : The P&L earned by holding a position for one period assuming rates
            stay exactly where they are (funding cost vs coupon/yield received).
            For a receive-fixed swap: carry ≈ fixed_rate - overnight_rate (SOFR).
            In bps/month.

Rolldown  : The P&L earned as the instrument "rolls down" the yield curve with
            the passage of time — i.e. a 10Y swap becomes a 9Y11M swap after one
            month, and if the curve is upward sloping that means you receive a
            higher rate than you pay. In bps/month.

Total Return ≈ Carry + Rolldown  (ignoring convexity for short horizons)

These functions replicate the carry/rolldown column builders used in the
eSwaps & Bonds OneNote notebook, adapted to work on FRED / treasury.gov data.
"""

import numpy as np
import pandas as pd
from typing import Optional, List, Dict, Union


# ---------------------------------------------------------------------------
# Yield curve interpolation (needed to compute rolldown)
# ---------------------------------------------------------------------------

def interpolate_rate(
    tenors: List[float],
    rates: List[float],
    target_tenor: float,
) -> float:
    """
    Linear interpolation of yield curve at an arbitrary tenor.

    Parameters
    ----------
    tenors       : list of tenor years, e.g. [2, 5, 10, 30]
    rates        : corresponding par rates / yields in %
    target_tenor : tenor to interpolate, e.g. 9.917 (= 10Y rolled 1M)
    """
    tenors_arr = np.array(tenors, dtype=float)
    rates_arr = np.array(rates, dtype=float)
    return float(np.interp(target_tenor, tenors_arr, rates_arr))


# ---------------------------------------------------------------------------
# Swap carry
# ---------------------------------------------------------------------------

def swap_carry(
    fixed_rate: float,
    overnight_rate: float,
    tenor_years: float,
    dv01_per_bp: float = 1.0,
    holding_months: float = 1.0,
) -> float:
    """
    Carry on a receive-fixed interest rate swap (annualised bps → bps/period).

    carry = (fixed_rate - overnight_rate) * (holding_months / 12) * 100
            * dv01_normalisation

    Parameters
    ----------
    fixed_rate      : fixed leg rate in % (e.g. 4.50)
    overnight_rate  : SOFR / O/N rate in % (e.g. 5.30)
    tenor_years     : swap tenor (unused here but kept for consistency)
    dv01_per_bp     : optional DV01 scaling to normalise to a fixed risk notional
    holding_months  : holding period in months (default 1)

    Returns carry in bps over the holding period.
    """
    carry_pct = fixed_rate - overnight_rate
    carry_bps = carry_pct * 100 * (holding_months / 12)
    return carry_bps * dv01_per_bp


def swap_rolldown(
    curve_tenors: List[float],
    curve_rates: List[float],
    tenor_years: float,
    holding_months: float = 1.0,
) -> float:
    """
    Rolldown on a par swap: rate change as the swap shortens by <holding_months>.

    rolldown = rate(T) - rate(T - holding_months/12)  (in bps)

    A positive rolldown on a receiver means the shorter-maturity rate is lower,
    so the position becomes more valuable (you locked in a higher rate).

    Parameters
    ----------
    curve_tenors    : list of benchmark tenor years
    curve_rates     : corresponding swap rates / yields in %
    tenor_years     : current tenor of the instrument
    holding_months  : holding period in months
    """
    rate_now = interpolate_rate(curve_tenors, curve_rates, tenor_years)
    rate_after = interpolate_rate(
        curve_tenors, curve_rates, tenor_years - holding_months / 12
    )
    return (rate_after - rate_now) * 100  # bps — positive = favourable for receiver


def total_return(carry_bps: float, rolldown_bps: float) -> float:
    """Total expected return = carry + rolldown in bps/period."""
    return carry_bps + rolldown_bps


# ---------------------------------------------------------------------------
# Bond carry
# ---------------------------------------------------------------------------

def bond_carry(
    coupon: float,
    repo_rate: float,
    dirty_price: float = 100.0,
    holding_months: float = 1.0,
) -> float:
    """
    Carry on a cash bond position (carry-to-repo).

    carry = (coupon_income - repo_cost) * (holding_months / 12)
          = (coupon - repo_rate * dirty_price / 100) * (holding_months / 12) * 100

    Returns bps over the holding period.

    Parameters
    ----------
    coupon          : annual coupon rate in %
    repo_rate       : repo / financing rate in %
    dirty_price     : bond dirty price (default 100)
    holding_months  : holding period in months
    """
    coupon_income = coupon * (holding_months / 12)      # % over period
    funding_cost = repo_rate * (dirty_price / 100) * (holding_months / 12)
    carry_pct = coupon_income - funding_cost
    return carry_pct * 100  # convert to bps


def bond_rolldown(
    yield_curve_tenors: List[float],
    yield_curve_rates: List[float],
    maturity_years: float,
    holding_months: float = 1.0,
) -> float:
    """
    Rolldown on a bond: yield change as bond shortens with time.

    Same logic as swap_rolldown — interpolate yield at (maturity - dt).
    """
    return swap_rolldown(
        yield_curve_tenors, yield_curve_rates, maturity_years, holding_months
    )


# ---------------------------------------------------------------------------
# Carry/Rolldown for a DataFrame of rates (multi-tenor)
# ---------------------------------------------------------------------------

def carry_rolldown_table(
    curve_df: pd.DataFrame,
    overnight_col: str,
    tenor_years_map: Dict[str, float],
    holding_months: float = 1.0,
) -> pd.DataFrame:
    """
    Build a carry+rolldown table for all tenors in a yield-curve DataFrame.

    Parameters
    ----------
    curve_df         : DataFrame with columns = tenor labels (e.g. '2Y','5Y','10Y')
                       and DatetimeIndex; rates in %.
    overnight_col    : column name for the overnight / policy rate (e.g. 'SOFR')
    tenor_years_map  : dict mapping column name → tenor in years
                       e.g. {'2Y': 2.0, '5Y': 5.0, '10Y': 10.0}
    holding_months   : 1 (monthly) or 3 (quarterly)

    Returns
    -------
    DataFrame with one row per date containing columns:
        {tenor}_carry, {tenor}_rolldown, {tenor}_total
    """
    results = []

    for date, row in curve_df.iterrows():
        # Build curve for this date
        tenors = []
        rates = []
        for col, tenor in sorted(tenor_years_map.items(), key=lambda x: x[1]):
            if not pd.isna(row.get(col)):
                tenors.append(tenor)
                rates.append(row[col])

        on_rate = row.get(overnight_col, np.nan)
        if len(tenors) < 2 or pd.isna(on_rate):
            continue

        rec = {"date": date}
        for col, tenor in tenor_years_map.items():
            fixed = row.get(col, np.nan)
            if pd.isna(fixed):
                rec[f"{col}_carry"] = np.nan
                rec[f"{col}_rolldown"] = np.nan
                rec[f"{col}_total"] = np.nan
                continue

            c = swap_carry(fixed, on_rate, tenor, holding_months=holding_months)
            rd = swap_rolldown(tenors, rates, tenor, holding_months=holding_months)
            rec[f"{col}_carry"] = round(c, 2)
            rec[f"{col}_rolldown"] = round(rd, 2)
            rec[f"{col}_total"] = round(c + rd, 2)

        results.append(rec)

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results).set_index("date")
    out.index = pd.to_datetime(out.index)
    return out


# ---------------------------------------------------------------------------
# Spread carry/rolldown (curve trades: 2s10s, 5s30s, etc.)
# ---------------------------------------------------------------------------

def spread_carry(
    long_rate: float,
    short_rate: float,
    overnight_rate: float,
    long_dv01: float = 1.0,
    short_dv01: float = 1.0,
    holding_months: float = 1.0,
) -> float:
    """
    Net carry on a curve trade (receive long / pay short, DV01-neutral).

    carry = (long_rate - on_rate) * long_dv01
          - (short_rate - on_rate) * short_dv01
    normalised per unit of risk.
    """
    long_carry = swap_carry(long_rate, overnight_rate, 0, long_dv01, holding_months)
    short_carry = swap_carry(short_rate, overnight_rate, 0, short_dv01, holding_months)
    return long_carry - short_carry


def spread_rolldown(
    curve_tenors: List[float],
    curve_rates: List[float],
    long_tenor: float,
    short_tenor: float,
    holding_months: float = 1.0,
) -> float:
    """Rolldown on a spread / curve trade."""
    long_rd = swap_rolldown(curve_tenors, curve_rates, long_tenor, holding_months)
    short_rd = swap_rolldown(curve_tenors, curve_rates, short_tenor, holding_months)
    return long_rd - short_rd


# ---------------------------------------------------------------------------
# Butterfly carry/rolldown
# ---------------------------------------------------------------------------

def fly_carry(
    wing1_rate: float,
    belly_rate: float,
    wing2_rate: float,
    overnight_rate: float,
    w1_dv01: float = 0.5,
    belly_dv01: float = 1.0,
    w2_dv01: float = 0.5,
    holding_months: float = 1.0,
) -> float:
    """
    Net carry on a butterfly (pay wings / receive belly, DV01-neutral).
    Weights: -w1 × wing1 + belly × belly_dv01 - w2 × wing2
    """
    c1 = swap_carry(wing1_rate, overnight_rate, 0, w1_dv01, holding_months)
    cb = swap_carry(belly_rate, overnight_rate, 0, belly_dv01, holding_months)
    c2 = swap_carry(wing2_rate, overnight_rate, 0, w2_dv01, holding_months)
    return cb - c1 - c2


def fly_rolldown(
    curve_tenors: List[float],
    curve_rates: List[float],
    wing1_tenor: float,
    belly_tenor: float,
    wing2_tenor: float,
    holding_months: float = 1.0,
) -> float:
    """Rolldown on a butterfly trade."""
    rd1 = swap_rolldown(curve_tenors, curve_rates, wing1_tenor, holding_months)
    rdb = swap_rolldown(curve_tenors, curve_rates, belly_tenor, holding_months)
    rd2 = swap_rolldown(curve_tenors, curve_rates, wing2_tenor, holding_months)
    return rdb - rd1 - rd2


# ---------------------------------------------------------------------------
# Convenience: compute carry+rolldown for standard trade structures from a
# snapshot (single-date) yield curve dict
# ---------------------------------------------------------------------------

def snapshot_carry_rolldown(
    curve: Dict[str, float],
    overnight_rate: float,
    trade_type: str = "outright",
    tenor1: str = "10Y",
    tenor2: Optional[str] = None,
    tenor3: Optional[str] = None,
    holding_months: float = 1.0,
) -> Dict[str, float]:
    """
    Compute carry and rolldown for a single trade from a curve snapshot.

    Parameters
    ----------
    curve         : dict of {tenor_label: rate_%}, e.g. {"2Y": 4.5, "10Y": 4.8}
    overnight_rate: SOFR / O/N rate in %
    trade_type    : 'outright' | 'spread' | 'fly'
    tenor1        : main / long leg label
    tenor2        : second leg (for spread/fly)
    tenor3        : third leg (for fly belly)
    holding_months: 1 or 3

    Returns dict with keys 'carry', 'rolldown', 'total' in bps.
    """
    TENOR_MAP = {
        "6M": 0.5, "1Y": 1.0, "2Y": 2.0, "3Y": 3.0, "4Y": 4.0,
        "5Y": 5.0, "7Y": 7.0, "10Y": 10.0, "15Y": 15.0, "20Y": 20.0,
        "30Y": 30.0,
    }

    tenors = sorted(
        [(TENOR_MAP[k], v) for k, v in curve.items() if k in TENOR_MAP],
        key=lambda x: x[0]
    )
    t_list = [t[0] for t in tenors]
    r_list = [t[1] for t in tenors]

    if trade_type == "outright":
        rate = curve[tenor1]
        c = swap_carry(rate, overnight_rate, TENOR_MAP[tenor1], 1.0, holding_months)
        rd = swap_rolldown(t_list, r_list, TENOR_MAP[tenor1], holding_months)

    elif trade_type == "spread":
        assert tenor2 is not None, "tenor2 required for spread"
        r1, r2 = curve[tenor1], curve[tenor2]
        c = spread_carry(r1, r2, overnight_rate, 1.0, 1.0, holding_months)
        rd = spread_rolldown(t_list, r_list, TENOR_MAP[tenor1], TENOR_MAP[tenor2], holding_months)

    elif trade_type == "fly":
        assert tenor2 is not None and tenor3 is not None, "tenor2+tenor3 required for fly"
        r1, r2, r3 = curve[tenor1], curve[tenor2], curve[tenor3]
        c = fly_carry(r1, r2, r3, overnight_rate, 0.5, 1.0, 0.5, holding_months)
        rd = fly_rolldown(t_list, r_list, TENOR_MAP[tenor1], TENOR_MAP[tenor2], TENOR_MAP[tenor3], holding_months)

    else:
        raise ValueError(f"Unknown trade_type: {trade_type}")

    return {"carry": round(c, 2), "rolldown": round(rd, 2), "total": round(c + rd, 2)}


# ---------------------------------------------------------------------------
# Forward-rate based carry + rolldown  (cleaner: total = spot − forward)
# ---------------------------------------------------------------------------

def forward_rate(
    curve_tenors: List[float],
    curve_rates: List[float],
    hold_years: float,
    target_tenor: float,
) -> float:
    """
    Compute the forward rate f(h, T-h): the rate for a (T-h) year swap
    starting in h years, derived from the spot curve.

    Using semi-annual compounding:
    (1+r_T/2)^(2T) = (1+r_h/2)^(2h) * (1+f/2)^(2*(T-h))

    Parameters
    ----------
    curve_tenors : list of benchmark tenor years
    curve_rates  : corresponding spot rates in %
    hold_years   : forward start (e.g. 1/12 for 1M, 1.0 for 1Y)
    target_tenor : current tenor T (e.g. 30.0 for 30Y)

    Returns forward rate in %.
    """
    r_T = interpolate_rate(curve_tenors, curve_rates, target_tenor) / 100.0
    r_h = interpolate_rate(curve_tenors, curve_rates, hold_years) / 100.0
    T = target_tenor
    h = hold_years
    remaining = T - h
    if remaining <= 0:
        return interpolate_rate(curve_tenors, curve_rates, target_tenor)

    # (1+r_T/2)^(2T) / (1+r_h/2)^(2h) = (1+f/2)^(2*remaining)
    numerator = (1 + r_T / 2) ** (2 * T)
    denominator = (1 + r_h / 2) ** (2 * h)
    ratio = numerator / denominator
    if ratio <= 0:
        return interpolate_rate(curve_tenors, curve_rates, target_tenor)

    f_semi = ratio ** (1.0 / (2 * remaining)) - 1
    return f_semi * 2 * 100  # back to % annual


def forward_swap_rate(
    curve_tenors: List[float],
    curve_rates: List[float],
    hold_years: float,
    swap_tenor_years: float,
) -> float:
    """
    Compute the h-forward T-year swap rate: the rate for a T-year swap
    starting in h years, using the spot curve.

    E.g. forward_swap_rate(..., 1.0, 30.0) = 1y30y forward rate.

    Uses semi-annual compounding:
    (1+s_{h+T}/2)^(2*(h+T)) = (1+s_h/2)^(2h) * (1+f/2)^(2T)
    """
    return forward_rate(curve_tenors, curve_rates, hold_years,
                        hold_years + swap_tenor_years)


def forward_carry_rolldown(
    curve: Dict[str, float],
    overnight_rate: float,
    trade_type: str = "outright",
    tenor1: str = "10Y",
    tenor2: Optional[str] = None,
    tenor3: Optional[str] = None,
    holding_months: float = 1.0,
) -> Dict[str, float]:
    """
    Carry + rolldown via forward swap rates.

    For an outright T-year receiver held for h months:
      fwd_rate = h-forward T-year swap rate  (e.g. 1m30y for 30Y held 1M)
      carry+roll = (fwd_rate - spot(T)) * 100   in bps

    This is the break-even: if spot(T) stays at fwd_rate, you break even.
    If spot(T) < fwd_rate (rates lower than forward implies), receiver profits.

    For spreads/flies: net across legs.

    Returns dict with 'carry' (funding), 'rolldown' (curve), 'total' in bps.
    """
    TENOR_MAP = {
        "6M": 0.5, "1Y": 1.0, "2Y": 2.0, "3Y": 3.0, "4Y": 4.0,
        "5Y": 5.0, "7Y": 7.0, "10Y": 10.0, "15Y": 15.0, "20Y": 20.0,
        "30Y": 30.0,
    }

    tenors = sorted(
        [(TENOR_MAP[k], v) for k, v in curve.items() if k in TENOR_MAP],
        key=lambda x: x[0]
    )
    t_list = [t[0] for t in tenors]
    r_list = [t[1] for t in tenors]
    hold_yrs = holding_months / 12.0

    def _spot(label):
        return curve[label]

    def _fwd_swap(label):
        """h-forward T-year rate (e.g. 1m30y for 30Y held 1M)."""
        return forward_swap_rate(t_list, r_list, hold_yrs, TENOR_MAP[label])

    def _cr_one(label):
        """Total carry+roll for one leg: fwd - spot, in bps."""
        return (_fwd_swap(label) - _spot(label)) * 100

    if trade_type == "outright":
        total_bps = _cr_one(tenor1)

    elif trade_type == "spread":
        assert tenor2 is not None
        # Spread = long - short (tenor1=long, tenor2=short)
        total_bps = _cr_one(tenor1) - _cr_one(tenor2)

    elif trade_type == "fly":
        assert tenor2 is not None and tenor3 is not None
        # Fly = 2*belly - wing1 - wing2
        total_bps = 2 * _cr_one(tenor2) - _cr_one(tenor1) - _cr_one(tenor3)

    else:
        raise ValueError(f"Unknown trade_type: {trade_type}")

    return {"carry": 0.0, "rolldown": 0.0, "total": round(total_bps, 2)}
