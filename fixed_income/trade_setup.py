"""
trade_setup.py — Trade construction and analysis for interest rate strategies.

Covers three main trade structures:
  1. Outrights  — single tenor positions (e.g. receive 10Y swap)
  2. Spreads    — two-leg curve trades (e.g. 2s10s: pay 2Y, receive 10Y)
  3. Butterflies / Flies — three-leg trades (e.g. 2s5s10s: pay wings, receive belly)

For each structure the module computes:
  • Current level & z-score
  • Carry + rolldown
  • DV01-weighted notionals (so 1bp = $10k P&L per $100M notional)
  • Expected return (carry + rolldown over a horizon)
  • Sharpe ratio (expected return / annualised vol)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from .utils import zscore, zscore_current, percentile_rank, summary_stats
from .carry_rolldown import (
    snapshot_carry_rolldown,
    swap_carry, swap_rolldown,
    spread_carry, spread_rolldown,
    fly_carry, fly_rolldown,
    interpolate_rate,
)


# ---------------------------------------------------------------------------
# Tenor → years mapping
# ---------------------------------------------------------------------------

TENOR_YEARS: Dict[str, float] = {
    "3M": 0.25, "6M": 0.5, "1Y": 1.0, "2Y": 2.0, "3Y": 3.0,
    "4Y": 4.0,  "5Y": 5.0, "7Y": 7.0, "10Y": 10.0,
    "15Y": 15.0, "20Y": 20.0, "30Y": 30.0,
}


# ---------------------------------------------------------------------------
# DV01 utilities
# ---------------------------------------------------------------------------

def approx_dv01(tenor_years: float, rate_pct: float = 4.0) -> float:
    """
    Approximate DV01 of a par interest rate swap (per $1M notional, per bp).

    DV01 ≈ tenor / (1 + rate/2)^(2*tenor)  * 0.0001 * notional
    Simplified formula valid for coupon-bearing swaps near par.

    Returns DV01 in $ per $1M notional per 1bp move.
    """
    r = rate_pct / 100.0
    # Modified duration of a par bond ≈ (1 - (1+r/2)^(-2T)) / r
    # DV01 = duration * price * notional * 0.0001
    if r == 0:
        return tenor_years * 10.0
    n = 2 * tenor_years          # semi-annual periods
    md = (1 - (1 + r / 2) ** (-n)) / r
    dv01 = md * 1_000_000 * 0.0001  # per $1M per bp
    return round(dv01, 2)


def dv01_neutral_ratio(
    tenor1_years: float,
    tenor2_years: float,
    rate1: float = 4.0,
    rate2: float = 4.0,
) -> float:
    """
    Notional ratio to make a two-leg trade DV01-neutral.
    Long notional on leg1 = 1; short notional on leg2 = ratio.
    """
    d1 = approx_dv01(tenor1_years, rate1)
    d2 = approx_dv01(tenor2_years, rate2)
    return d1 / d2 if d2 != 0 else 1.0


# ---------------------------------------------------------------------------
# Outright trade
# ---------------------------------------------------------------------------

class Outright:
    """
    A single-tenor receive-fixed swap (or bond long).

    Usage
    -----
    trade = Outright("10Y", rate_series, overnight_series)
    print(trade.summary())
    """

    def __init__(
        self,
        tenor: str,
        rate_series: pd.Series,
        overnight_series: pd.Series,
        zscore_window: int = 252,
        holding_months: float = 1.0,
    ):
        self.tenor = tenor
        self.tenor_years = TENOR_YEARS[tenor]
        self.rates = rate_series.dropna()
        self.overnight = overnight_series.dropna()
        self.zscore_window = zscore_window
        self.holding_months = holding_months

    @property
    def current_rate(self) -> float:
        return float(self.rates.iloc[-1])

    @property
    def current_on(self) -> float:
        return float(self.overnight.reindex(self.rates.index, method="ffill").iloc[-1])

    @property
    def zscore_1y(self) -> float:
        return zscore_current(self.rates, self.zscore_window)

    @property
    def percentile_1y(self) -> float:
        return float(percentile_rank(self.rates, self.zscore_window).iloc[-1])

    def carry_rolldown(self, curve: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """Compute carry and rolldown. Pass curve dict for rolldown interpolation."""
        if curve is None:
            # fallback: rolldown ≈ 0 if no curve provided
            c = swap_carry(self.current_rate, self.current_on, self.tenor_years,
                           holding_months=self.holding_months)
            return {"carry": round(c, 2), "rolldown": 0.0, "total": round(c, 2)}
        return snapshot_carry_rolldown(
            curve, self.current_on, "outright", self.tenor,
            holding_months=self.holding_months
        )

    def expected_return_ann(self, carry_rolldown_bps: float) -> float:
        """Annualise the per-period carry+rolldown."""
        return carry_rolldown_bps * (12 / self.holding_months)

    def sharpe(self, carry_rolldown_bps: float) -> float:
        """Sharpe = annualised E[return] / annualised vol (bps)."""
        ann_ret = self.expected_return_ann(carry_rolldown_bps)
        daily_changes = self.rates.diff().dropna() * 100  # bps
        ann_vol = float(daily_changes.std() * np.sqrt(252))
        return ann_ret / ann_vol if ann_vol > 0 else np.nan

    def summary(self, curve: Optional[Dict[str, float]] = None) -> pd.DataFrame:
        """One-row summary DataFrame."""
        cr = self.carry_rolldown(curve)
        s = self.sharpe(cr["total"])
        return pd.DataFrame([{
            "Tenor": self.tenor,
            "Rate (%)": round(self.current_rate, 3),
            "Z-score (1Y)": round(self.zscore_1y, 2),
            "Pctile (1Y)": round(self.percentile_1y, 1),
            "Carry (bps)": cr["carry"],
            "Rolldown (bps)": cr["rolldown"],
            "Total (bps)": cr["total"],
            "Sharpe": round(s, 2) if not np.isnan(s) else np.nan,
        }])


# ---------------------------------------------------------------------------
# Spread (curve) trade
# ---------------------------------------------------------------------------

class Spread:
    """
    A two-leg DV01-neutral curve trade.
    Convention: receive long tenor (tenor2), pay short tenor (tenor1).
    Spread = rate(tenor2) - rate(tenor1)

    E.g. 2s10s: tenor1='2Y', tenor2='10Y'
    """

    def __init__(
        self,
        tenor1: str,
        tenor2: str,
        rate_df: pd.DataFrame,
        overnight_series: pd.Series,
        zscore_window: int = 252,
        holding_months: float = 1.0,
    ):
        self.tenor1 = tenor1
        self.tenor2 = tenor2
        self.t1y = TENOR_YEARS[tenor1]
        self.t2y = TENOR_YEARS[tenor2]
        self.rates = rate_df[[tenor1, tenor2]].dropna()
        self.overnight = overnight_series
        self.zscore_window = zscore_window
        self.holding_months = holding_months
        self.spread_series = self.rates[tenor2] - self.rates[tenor1]

    @property
    def name(self) -> str:
        return f"{self.tenor1}/{self.tenor2}"

    @property
    def current_spread(self) -> float:
        return float(self.spread_series.iloc[-1])

    @property
    def zscore_1y(self) -> float:
        return zscore_current(self.spread_series, self.zscore_window)

    @property
    def percentile_1y(self) -> float:
        return float(percentile_rank(self.spread_series, self.zscore_window).iloc[-1])

    def carry_rolldown(self, curve: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        if curve is None:
            row = self.rates.iloc[-1]
            on = float(self.overnight.reindex(self.rates.index, method="ffill").iloc[-1])
            c = spread_carry(row[self.tenor2], row[self.tenor1], on,
                             holding_months=self.holding_months)
            return {"carry": round(c, 2), "rolldown": 0.0, "total": round(c, 2)}
        return snapshot_carry_rolldown(
            curve, float(self.overnight.reindex(self.rates.index, method="ffill").iloc[-1]),
            "spread", self.tenor2, self.tenor1,
            holding_months=self.holding_months
        )

    def sharpe(self, carry_rolldown_bps: float) -> float:
        ann_ret = carry_rolldown_bps * (12 / self.holding_months)
        changes = self.spread_series.diff().dropna() * 100
        ann_vol = float(changes.std() * np.sqrt(252))
        return ann_ret / ann_vol if ann_vol > 0 else np.nan

    def summary(self, curve: Optional[Dict[str, float]] = None) -> pd.DataFrame:
        cr = self.carry_rolldown(curve)
        s = self.sharpe(cr["total"])
        return pd.DataFrame([{
            "Trade": self.name,
            "Spread (bps)": round(self.current_spread * 100, 1),
            "Z-score (1Y)": round(self.zscore_1y, 2),
            "Pctile (1Y)": round(self.percentile_1y, 1),
            "Carry (bps)": cr["carry"],
            "Rolldown (bps)": cr["rolldown"],
            "Total (bps)": cr["total"],
            "Sharpe": round(s, 2) if not np.isnan(s) else np.nan,
        }])


# ---------------------------------------------------------------------------
# Butterfly trade
# ---------------------------------------------------------------------------

class Butterfly:
    """
    Three-leg butterfly: receive belly, pay wings (DV01-neutral).
    fly = belly - 0.5 * wing1 - 0.5 * wing2

    E.g. 2s5s10s: wing1='2Y', belly='5Y', wing2='10Y'
    """

    def __init__(
        self,
        wing1: str,
        belly: str,
        wing2: str,
        rate_df: pd.DataFrame,
        overnight_series: pd.Series,
        zscore_window: int = 252,
        holding_months: float = 1.0,
    ):
        self.wing1 = wing1
        self.belly = belly
        self.wing2 = wing2
        self.rates = rate_df[[wing1, belly, wing2]].dropna()
        self.overnight = overnight_series
        self.zscore_window = zscore_window
        self.holding_months = holding_months
        self.fly_series = (
            self.rates[belly] - 0.5 * self.rates[wing1] - 0.5 * self.rates[wing2]
        )

    @property
    def name(self) -> str:
        return f"{self.wing1}/{self.belly}/{self.wing2}"

    @property
    def current_fly(self) -> float:
        return float(self.fly_series.iloc[-1])

    @property
    def zscore_1y(self) -> float:
        return zscore_current(self.fly_series, self.zscore_window)

    @property
    def percentile_1y(self) -> float:
        return float(percentile_rank(self.fly_series, self.zscore_window).iloc[-1])

    def carry_rolldown(self, curve: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        if curve is None:
            row = self.rates.iloc[-1]
            on = float(self.overnight.reindex(self.rates.index, method="ffill").iloc[-1])
            c = fly_carry(row[self.wing1], row[self.belly], row[self.wing2], on,
                          holding_months=self.holding_months)
            return {"carry": round(c, 2), "rolldown": 0.0, "total": round(c, 2)}

        on = float(self.overnight.reindex(self.rates.index, method="ffill").iloc[-1])
        return snapshot_carry_rolldown(
            curve, on, "fly",
            self.wing1, self.belly, self.wing2,
            holding_months=self.holding_months
        )

    def sharpe(self, carry_rolldown_bps: float) -> float:
        ann_ret = carry_rolldown_bps * (12 / self.holding_months)
        changes = self.fly_series.diff().dropna() * 100
        ann_vol = float(changes.std() * np.sqrt(252))
        return ann_ret / ann_vol if ann_vol > 0 else np.nan

    def summary(self, curve: Optional[Dict[str, float]] = None) -> pd.DataFrame:
        cr = self.carry_rolldown(curve)
        s = self.sharpe(cr["total"])
        return pd.DataFrame([{
            "Trade": self.name,
            "Fly (bps)": round(self.current_fly * 100, 1),
            "Z-score (1Y)": round(self.zscore_1y, 2),
            "Pctile (1Y)": round(self.percentile_1y, 1),
            "Carry (bps)": cr["carry"],
            "Rolldown (bps)": cr["rolldown"],
            "Total (bps)": cr["total"],
            "Sharpe": round(s, 2) if not np.isnan(s) else np.nan,
        }])


# ---------------------------------------------------------------------------
# Full trade book: combine multiple trades into a summary table
# ---------------------------------------------------------------------------

def build_trade_book(
    rate_df: pd.DataFrame,
    overnight_series: pd.Series,
    outright_tenors: Optional[List[str]] = None,
    spread_pairs: Optional[List[Tuple[str, str]]] = None,
    fly_triplets: Optional[List[Tuple[str, str, str]]] = None,
    curve_snapshot: Optional[Dict[str, float]] = None,
    zscore_window: int = 252,
    holding_months: float = 1.0,
) -> Dict[str, pd.DataFrame]:
    """
    Build a complete trade book with summaries for all trade types.

    Parameters
    ----------
    rate_df          : DataFrame with tenor columns (e.g. '2Y','5Y','10Y')
    overnight_series : overnight rate series (SOFR / EFFR)
    outright_tenors  : list of tenors, e.g. ['2Y','5Y','10Y','30Y']
    spread_pairs     : list of (short,long) tuples, e.g. [('2Y','10Y')]
    fly_triplets     : list of (wing1,belly,wing2) tuples
    curve_snapshot   : current curve dict for carry/rolldown interpolation
    zscore_window    : rolling window in business days
    holding_months   : carry/rolldown holding period

    Returns
    -------
    dict with keys 'outrights', 'spreads', 'flies'
    """
    results = {}

    if outright_tenors:
        rows = []
        for t in outright_tenors:
            if t not in rate_df.columns:
                continue
            trade = Outright(t, rate_df[t], overnight_series,
                             zscore_window, holding_months)
            rows.append(trade.summary(curve_snapshot).iloc[0])
        results["outrights"] = pd.DataFrame(rows).reset_index(drop=True)

    if spread_pairs:
        rows = []
        for t1, t2 in spread_pairs:
            if t1 not in rate_df.columns or t2 not in rate_df.columns:
                continue
            trade = Spread(t1, t2, rate_df, overnight_series,
                           zscore_window, holding_months)
            rows.append(trade.summary(curve_snapshot).iloc[0])
        results["spreads"] = pd.DataFrame(rows).reset_index(drop=True)

    if fly_triplets:
        rows = []
        for w1, b, w2 in fly_triplets:
            if not all(x in rate_df.columns for x in [w1, b, w2]):
                continue
            trade = Butterfly(w1, b, w2, rate_df, overnight_series,
                              zscore_window, holding_months)
            rows.append(trade.summary(curve_snapshot).iloc[0])
        results["flies"] = pd.DataFrame(rows).reset_index(drop=True)

    return results
