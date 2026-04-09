"""
table_generator.py — Generates the OneNote-style weekly update tables.

Recreates the "Strat Charts & Tables - Weekly Update" output from the
Tables PDF, producing three main tables for each currency (USD, EUR, GBP):

1. Expected Return table   — carry+rolldown in bps/month and annualised
2. Sharpe Ratio table      — expected return / vol for each instrument
3. DV01 Fr (outright) grid — forward DV01-adjusted return grid

Each table covers:
  Rows    : instrument types (outrights, spreads, flies)
  Columns : tenor buckets (2Y, 3Y, 5Y, 7Y, 10Y, 15Y, 20Y, 30Y)

Also produces the "Wedges" and "Milkboxes" tables visible in the Tables PDF.

Output: pandas DataFrames with colour-coded values (positive=green, negative=red)
        suitable for display in Streamlit or Jupyter.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from .utils import zscore_table, zscore_current, percentile_rank, summary_stats
from .carry_rolldown import (
    snapshot_carry_rolldown,
    swap_carry, swap_rolldown,
    spread_carry, spread_rolldown,
    fly_carry, fly_rolldown,
)
from .trade_setup import build_trade_book, TENOR_YEARS
from .wedges import wedge_grid, wedge_sharpe_grid


# ---------------------------------------------------------------------------
# Standard instrument definitions
# ---------------------------------------------------------------------------

OUTRIGHT_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y"]

SPREAD_PAIRS = [
    ("2Y", "5Y"),   # 2s5s
    ("2Y", "10Y"),  # 2s10s
    ("2Y", "30Y"),  # 2s30s
    ("5Y", "10Y"),  # 5s10s
    ("5Y", "30Y"),  # 5s30s
    ("10Y", "30Y"), # 10s30s
]

FLY_TRIPLETS = [
    ("2Y", "5Y", "10Y"),   # 2s5s10s
    ("2Y", "5Y", "30Y"),   # 2s5s30s
    ("5Y", "10Y", "30Y"),  # 5s10s30s
    ("2Y", "10Y", "30Y"),  # 2s10s30s
]


# ---------------------------------------------------------------------------
# Core table builder
# ---------------------------------------------------------------------------

def _build_metric_row(
    label: str,
    tenors: List[str],
    rates: Dict[str, float],
    overnight_rate: float,
    metric: str,  # 'carry', 'rolldown', 'total', 'sharpe'
    holding_months: float = 1.0,
    annualise: bool = False,
    rate_series_dict: Optional[Dict[str, pd.Series]] = None,
    trade_type: str = "outright",
    tenor2: Optional[str] = None,
    tenor3: Optional[str] = None,
) -> Dict[str, float]:
    """Build one row of a metric table for a single instrument/tenor."""
    row = {"Instrument": label}
    for t in tenors:
        if t not in rates:
            row[t] = np.nan
            continue
        try:
            if trade_type == "outright":
                cr = snapshot_carry_rolldown(rates, overnight_rate, "outright", t,
                                             holding_months=holding_months)
            elif trade_type == "spread":
                cr = snapshot_carry_rolldown(rates, overnight_rate, "spread", t, tenor2,
                                             holding_months=holding_months)
            elif trade_type == "fly":
                cr = snapshot_carry_rolldown(rates, overnight_rate, "fly", t, tenor2, tenor3,
                                             holding_months=holding_months)
            else:
                row[t] = np.nan
                continue

            val = cr.get(metric, np.nan)
            if annualise:
                val = val * (12 / holding_months)

            if metric == "sharpe" and rate_series_dict:
                # Compute Sharpe from expected return / vol
                total_ret_ann = cr["total"] * (12 / holding_months)
                series_key = t
                if series_key in rate_series_dict:
                    s = rate_series_dict[series_key]
                    changes = s.diff().dropna() * 100
                    ann_vol = float(changes.tail(252).std() * np.sqrt(252))
                    val = total_ret_ann / ann_vol if ann_vol > 0 else np.nan
                else:
                    val = np.nan

            row[t] = round(val, 2) if not np.isnan(val) else np.nan
        except Exception:
            row[t] = np.nan
    return row


def expected_return_table(
    rates: Dict[str, float],
    overnight_rate: float,
    holding_months: float = 1.0,
    annualise: bool = True,
    include_outrights: bool = True,
    include_spreads: bool = True,
    include_flies: bool = True,
) -> pd.DataFrame:
    """
    Generate an Expected Return table (carry + rolldown).

    Parameters
    ----------
    rates           : current curve dict {tenor: rate_%}
    overnight_rate  : O/N rate in %
    holding_months  : 1 = monthly, 3 = quarterly
    annualise       : if True, express as annualised bps

    Returns DataFrame: rows = instruments, cols = tenors.
    """
    rows = []

    if include_outrights:
        for t in OUTRIGHT_TENORS:
            if t not in rates:
                continue
            cr = snapshot_carry_rolldown(rates, overnight_rate, "outright", t,
                                         holding_months=holding_months)
            val = cr["total"] * (12 / holding_months) if annualise else cr["total"]
            rows.append({"Instrument": f"Outright {t}", "Tenor": t,
                         "Carry": cr["carry"], "Rolldown": cr["rolldown"],
                         "Total": round(val, 2)})

    if include_spreads:
        for t1, t2 in SPREAD_PAIRS:
            if t1 not in rates or t2 not in rates:
                continue
            cr = snapshot_carry_rolldown(rates, overnight_rate, "spread", t2, t1,
                                         holding_months=holding_months)
            val = cr["total"] * (12 / holding_months) if annualise else cr["total"]
            rows.append({"Instrument": f"{t1}/{t2}", "Tenor": f"{t1}s{t2}s",
                         "Carry": cr["carry"], "Rolldown": cr["rolldown"],
                         "Total": round(val, 2)})

    if include_flies:
        for w1, b, w2 in FLY_TRIPLETS:
            if not all(x in rates for x in [w1, b, w2]):
                continue
            cr = snapshot_carry_rolldown(rates, overnight_rate, "fly", w1, b, w2,
                                         holding_months=holding_months)
            val = cr["total"] * (12 / holding_months) if annualise else cr["total"]
            rows.append({"Instrument": f"{w1}/{b}/{w2}", "Tenor": f"fly",
                         "Carry": cr["carry"], "Rolldown": cr["rolldown"],
                         "Total": round(val, 2)})

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).set_index("Instrument")


def sharpe_table_from_rates(
    rates: Dict[str, float],
    overnight_rate: float,
    rate_series_dict: Dict[str, pd.Series],
    holding_months: float = 1.0,
    zscore_window: int = 252,
) -> pd.DataFrame:
    """
    Generate a Sharpe Ratio table.

    Sharpe = (annualised carry+rolldown) / (annualised vol of the instrument).

    Parameters
    ----------
    rates            : current curve snapshot {tenor: rate_%}
    overnight_rate   : O/N rate
    rate_series_dict : dict {tenor → historical rate pd.Series} for vol calculation

    Returns DataFrame with Sharpe ratios per instrument.
    """
    rows = []

    for t in OUTRIGHT_TENORS:
        if t not in rates or t not in rate_series_dict:
            continue
        cr = snapshot_carry_rolldown(rates, overnight_rate, "outright", t,
                                     holding_months=holding_months)
        ann_ret = cr["total"] * (12 / holding_months)
        s = rate_series_dict[t].dropna()
        changes = s.diff().dropna() * 100
        ann_vol = float(changes.tail(252).std() * np.sqrt(252))
        sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
        z = zscore_current(s, zscore_window)
        rows.append({
            "Instrument": f"Outright {t}",
            "Sharpe": round(sharpe, 2) if not np.isnan(sharpe) else np.nan,
            "E[Ret] (ann bps)": round(ann_ret, 1),
            "Vol (ann bps)": round(ann_vol, 1),
            "Z-score": round(z, 2),
        })

    for t1, t2 in SPREAD_PAIRS:
        if t1 not in rates or t2 not in rates:
            continue
        cr = snapshot_carry_rolldown(rates, overnight_rate, "spread", t2, t1,
                                     holding_months=holding_months)
        ann_ret = cr["total"] * (12 / holding_months)
        key = f"{t1}/{t2}"
        # Use spread series if available, else build from components
        if key in rate_series_dict:
            s = rate_series_dict[key].dropna()
        elif t1 in rate_series_dict and t2 in rate_series_dict:
            s = (rate_series_dict[t2] - rate_series_dict[t1]).dropna()
        else:
            continue
        changes = s.diff().dropna() * 100
        ann_vol = float(changes.tail(252).std() * np.sqrt(252))
        sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
        z = zscore_current(s, zscore_window)
        rows.append({
            "Instrument": f"{t1}/{t2}",
            "Sharpe": round(sharpe, 2) if not np.isnan(sharpe) else np.nan,
            "E[Ret] (ann bps)": round(ann_ret, 1),
            "Vol (ann bps)": round(ann_vol, 1),
            "Z-score": round(z, 2),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).set_index("Instrument")
    return df.sort_values("Sharpe", ascending=False)


# ---------------------------------------------------------------------------
# The "weekly update" multi-tenor grid (as seen in Tables PDF)
# ---------------------------------------------------------------------------

def weekly_update_grid(
    rates: Dict[str, float],
    overnight_rate: float,
    rate_series_dict: Dict[str, pd.Series],
    currency: str = "USD",
    holding_months: float = 1.0,
) -> Dict[str, pd.DataFrame]:
    """
    Produce all tables for the weekly update for a single currency.

    Replicates the Tables PDF layout:
      - Exp. Ret. (3m, ann)  — expected carry+rolldown, annualised
      - Sharpe Ratio          — expected return / vol
      - DV01 Fr (outright)    — forward carry in DV01 terms

    Parameters
    ----------
    rates            : current par swap curve {tenor: rate_%}
    overnight_rate   : SOFR / O/N rate
    rate_series_dict : historical rate series for vol + z-score
    currency         : label for the output tables (e.g. 'USD', 'EUR')
    holding_months   : 1 or 3

    Returns dict of DataFrames: 'exp_return', 'sharpe', 'zscore'.
    """
    # 1. Expected return table
    exp_ret = expected_return_table(
        rates, overnight_rate, holding_months=holding_months, annualise=True
    )

    # 2. Sharpe ratio table
    sharpe = sharpe_table_from_rates(
        rates, overnight_rate, rate_series_dict, holding_months=holding_months
    )

    # 3. Z-score summary table
    available_cols = [t for t in OUTRIGHT_TENORS if t in rate_series_dict]
    if available_cols:
        hist_df = pd.concat(
            {t: rate_series_dict[t] for t in available_cols}, axis=1
        ).dropna()
        zscores = zscore_table(hist_df, window=252, cols=available_cols)
    else:
        zscores = pd.DataFrame()

    return {
        f"{currency} Exp Return (ann bps)": exp_ret,
        f"{currency} Sharpe Ratio": sharpe,
        f"{currency} Z-scores": zscores,
    }


# ---------------------------------------------------------------------------
# Milkboxes table (from Tables PDF — box trades across currencies)
# ---------------------------------------------------------------------------

def milkboxes_table(
    rate_dict: Dict[str, Dict[str, float]],
    overnight_dict: Dict[str, float],
    rate_series_dict: Dict[str, Dict[str, pd.Series]],
    currencies: Optional[List[str]] = None,
    holding_months: float = 1.0,
) -> pd.DataFrame:
    """
    Milkboxes: carry analysis across multiple currencies on the same trade structure.

    E.g. compare 2s10s carry in USD vs EUR vs GBP — find which is cheapest.

    Parameters
    ----------
    rate_dict        : {ccy: {tenor: rate_%}}
    overnight_dict   : {ccy: overnight_rate_%}
    rate_series_dict : {ccy: {tenor: pd.Series}}
    currencies       : list of currency labels to include

    Returns DataFrame with currencies as rows and spread instruments as columns.
    """
    if currencies is None:
        currencies = list(rate_dict.keys())

    rows = []
    instruments = [f"{t1}/{t2}" for t1, t2 in SPREAD_PAIRS]

    for ccy in currencies:
        if ccy not in rate_dict:
            continue
        rates = rate_dict[ccy]
        on_rate = overnight_dict.get(ccy, 0.0)
        row = {"Currency": ccy}

        for t1, t2 in SPREAD_PAIRS:
            key = f"{t1}/{t2}"
            if t1 not in rates or t2 not in rates:
                row[key] = np.nan
                continue
            try:
                cr = snapshot_carry_rolldown(rates, on_rate, "spread", t2, t1,
                                             holding_months=holding_months)
                ann_ret = cr["total"] * (12 / holding_months)
                # Sharpe
                if ccy in rate_series_dict and t1 in rate_series_dict[ccy] and t2 in rate_series_dict[ccy]:
                    spread_s = (rate_series_dict[ccy][t2] - rate_series_dict[ccy][t1]).dropna()
                    changes = spread_s.diff().dropna() * 100
                    ann_vol = float(changes.tail(252).std() * np.sqrt(252))
                    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
                    row[key] = round(sharpe, 2)
                else:
                    row[key] = round(ann_ret, 1)
            except Exception:
                row[key] = np.nan

        rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).set_index("Currency")


# ---------------------------------------------------------------------------
# Spread Options screening table (from SpreadOptions PDF)
# ---------------------------------------------------------------------------

def spread_options_table(
    rate_series_dict: Dict[str, pd.Series],
    spread_pairs: Optional[List[Tuple[str, str]]] = None,
    expiry_months: int = 3,
    vol_window: int = 63,
) -> pd.DataFrame:
    """
    Spread options screening table for the weekly update.

    For each spread, compute:
      - Current spread level + z-score
      - Implied vol (from recent history)
      - ATM call and put prices in bps

    Parameters
    ----------
    rate_series_dict : {tenor: historical rate pd.Series}
    spread_pairs     : list of (short, long) tenor tuples
    """
    from .spread_options import spread_option_setup

    if spread_pairs is None:
        spread_pairs = SPREAD_PAIRS

    rows = []
    for t1, t2 in spread_pairs:
        if t1 not in rate_series_dict or t2 not in rate_series_dict:
            continue
        try:
            spread_s = (rate_series_dict[t2] - rate_series_dict[t1]).dropna() * 100  # bps
            setup = spread_option_setup(spread_s, expiry_months, "ATM", 0.0, vol_window)
            setup["Trade"] = f"{t1}/{t2}"
            rows.append(setup)
        except Exception:
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.set_index("Trade")
    return df.sort_values("Z-score (1Y)", key=abs, ascending=False)


# ---------------------------------------------------------------------------
# Full weekly report: all tables in one call
# ---------------------------------------------------------------------------

def generate_weekly_report(
    rate_dict: Dict[str, Dict[str, float]],
    overnight_dict: Dict[str, float],
    rate_series_dict: Dict[str, Dict[str, pd.Series]],
    currencies: Optional[List[str]] = None,
    include_wedges: bool = True,
    include_spread_options: bool = True,
    tenor_col_map: Optional[Dict[str, str]] = None,
    holding_months: float = 1.0,
) -> Dict[str, pd.DataFrame]:
    """
    Generate the full weekly fixed income update report.

    Returns a dict of DataFrames, one per table section.

    Parameters
    ----------
    rate_dict            : {ccy: {tenor: current_rate_%}}
    overnight_dict       : {ccy: overnight_rate_%}
    rate_series_dict     : {ccy: {tenor: pd.Series of rate history}}
    currencies           : list of currencies to include
    include_wedges       : include forward wedge grid
    include_spread_options: include spread option pricing
    tenor_col_map        : {tenor_label: column_name} for wedge analysis
    """
    if currencies is None:
        currencies = list(rate_dict.keys())

    output = {}

    # Per-currency tables
    for ccy in currencies:
        if ccy not in rate_dict:
            continue
        tables = weekly_update_grid(
            rates=rate_dict[ccy],
            overnight_rate=overnight_dict.get(ccy, 0.0),
            rate_series_dict=rate_series_dict.get(ccy, {}),
            currency=ccy,
            holding_months=holding_months,
        )
        output.update(tables)

    # Milkboxes (cross-currency comparison)
    output["Milkboxes (Sharpe)"] = milkboxes_table(
        rate_dict, overnight_dict, rate_series_dict, currencies, holding_months
    )

    # Spread options (use first currency's series)
    if include_spread_options and currencies:
        primary_ccy = currencies[0]
        if primary_ccy in rate_series_dict:
            output["Spread Options"] = spread_options_table(
                rate_series_dict[primary_ccy],
                spread_pairs=SPREAD_PAIRS,
            )

    # Wedge grid (use first currency)
    if include_wedges and currencies:
        primary_ccy = currencies[0]
        rates_primary = rate_dict.get(primary_ccy, {})
        if rates_primary and tenor_col_map:
            # Build curve arrays
            tenor_map = {k: v for k, v in TENOR_YEARS.items() if k in rates_primary}
            t_list = sorted([(v, rates_primary[k]) for k, v in tenor_map.items()])
            curve_tenors = [x[0] for x in t_list]
            curve_rates = [x[1] for x in t_list]
            output["Wedge Grid (bps)"] = wedge_grid(curve_tenors, curve_rates)

    return output


# ---------------------------------------------------------------------------
# Pandas Styler helpers (colour coding)
# ---------------------------------------------------------------------------

def style_returns_table(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    """
    Apply traffic-light colour coding to a returns DataFrame.
    Green = positive (good carry), Red = negative.
    """
    def _color(val):
        if pd.isna(val) or not isinstance(val, (int, float)):
            return ""
        if val > 5:
            return "background-color: #2d6a2d; color: white"
        elif val > 0:
            return "background-color: #5a9e5a; color: white"
        elif val > -5:
            return "background-color: #b05050; color: white"
        else:
            return "background-color: #8b0000; color: white"

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    return df.style.applymap(_color, subset=numeric_cols).format(
        {c: "{:.2f}" for c in numeric_cols}, na_rep="—"
    )


def style_zscore_table(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    """
    Colour-code a z-score table: extreme z-scores highlighted.
    Green = cheap (high z), Red = rich (low z).
    """
    def _color(val):
        if pd.isna(val) or not isinstance(val, (int, float)):
            return ""
        if val > 1.5:
            return "background-color: #2d6a2d; color: white"
        elif val > 0.5:
            return "background-color: #5a9e5a"
        elif val < -1.5:
            return "background-color: #8b0000; color: white"
        elif val < -0.5:
            return "background-color: #b05050"
        return ""

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    return df.style.applymap(_color, subset=numeric_cols).format(
        {c: "{:.2f}" for c in numeric_cols}, na_rep="—"
    )
