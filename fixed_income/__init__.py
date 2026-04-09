"""
fixed_income — Standalone Python re-implementation of the Barclays eSwaps & Bonds
trading analytics (originally using proprietary qarostpy library).

Modules
-------
utils           Z-scores, rolling stats, date helpers
carry_rolldown  Carry and rolldown for swaps, bonds, spreads, butterflies
trade_setup     Outright / Spread / Butterfly trade construction and Sharpe
bond_analytics  DV01, convexity, asset swaps, box swaps, cross-currency basis
spread_options  Bachelier / Kirk / MC pricing for rate spread options
wedges          Forward wedge analysis and vol-adjusted carry grids
swaptions       Black / Bachelier / SABR swaption pricing and expected returns
portfolio       Beta, correlation, efficient frontier, Sharpe, annual-move indicator
table_generator OneNote-style weekly update tables (exp return, Sharpe, z-scores)
"""

from .utils import (
    zscore,
    zscore_current,
    percentile_rank,
    rolling_mean,
    rolling_std,
    realized_std,
    annualized_vol,
    summary_stats,
    zscore_table,
    correlation_matrix,
    top_correlated_pairs,
)

from .carry_rolldown import (
    interpolate_rate,
    swap_carry,
    swap_rolldown,
    bond_carry,
    bond_rolldown,
    total_return,
    spread_carry,
    spread_rolldown,
    fly_carry,
    fly_rolldown,
    carry_rolldown_table,
    snapshot_carry_rolldown,
    forward_rate,
    forward_carry_rolldown,
)

from .trade_setup import (
    Outright,
    Spread,
    Butterfly,
    build_trade_book,
    approx_dv01,
    dv01_neutral_ratio,
    TENOR_YEARS,
)

from .bond_analytics import (
    bond_cashflows,
    bond_price,
    bond_ytm,
    modified_duration,
    dv01_bond,
    convexity,
    price_change_approx,
    asset_swap_spread,
    swap_spread,
    swap_spread_series,
    box_swap,
    box_swap_series,
    xccy_basis_carry,
    quick_analytics,
)

from .spread_options import (
    bachelier_price,
    bachelier_implied_vol,
    bachelier_greeks,
    kirks_price,
    mc_spread_option,
    spread_option_expected_return,
    spread_option_setup,
    spread_option_screen,
)

from .wedges import (
    forward_swap_rate,
    wedge,
    wedge_grid,
    vol_adjusted_wedge,
    wedge_sharpe_grid,
    wedge_history,
    run_wedge_analysis,
    vol_regime_check,
)

from .swaptions import (
    black_swaption,
    bachelier_swaption,
    bachelier_implied_vol_swaption,
    swaption_greeks,
    sabr_vol,
    sabr_calibrate,
    swaption_expected_return,
    build_vol_surface,
    vol_surface_zscore,
    swaption_screen,
    swap_annuity,
)

from .portfolio import (
    rolling_beta,
    hedge_ratio,
    regression_summary,
    efficient_frontier,
    max_sharpe_portfolio,
    min_variance_portfolio,
    rolling_sharpe,
    sharpe_table,
    annual_move_indicator,
    cross_country_beta,
    multi_country_beta_table,
)

from .table_generator import (
    expected_return_table,
    sharpe_table_from_rates,
    weekly_update_grid,
    milkboxes_table,
    spread_options_table,
    generate_weekly_report,
    style_returns_table,
    style_zscore_table,
    OUTRIGHT_TENORS,
    SPREAD_PAIRS,
    FLY_TRIPLETS,
)

__all__ = [
    # utils
    "zscore", "zscore_current", "percentile_rank", "rolling_mean", "rolling_std",
    "realized_std", "annualized_vol", "summary_stats", "zscore_table",
    "correlation_matrix", "top_correlated_pairs",
    # carry_rolldown
    "swap_carry", "swap_rolldown", "bond_carry", "bond_rolldown", "total_return",
    "spread_carry", "spread_rolldown", "fly_carry", "fly_rolldown",
    "carry_rolldown_table", "snapshot_carry_rolldown",
    # trade_setup
    "Outright", "Spread", "Butterfly", "build_trade_book",
    "approx_dv01", "dv01_neutral_ratio", "TENOR_YEARS",
    # bond_analytics
    "bond_cashflows", "bond_price", "bond_ytm", "modified_duration",
    "dv01_bond", "convexity", "price_change_approx", "asset_swap_spread",
    "swap_spread", "swap_spread_series", "box_swap", "box_swap_series",
    "xccy_basis_carry", "quick_analytics",
    # spread_options
    "bachelier_price", "bachelier_implied_vol", "bachelier_greeks",
    "kirks_price", "mc_spread_option", "spread_option_expected_return",
    "spread_option_setup", "spread_option_screen",
    # wedges
    "forward_swap_rate", "wedge", "wedge_grid", "vol_adjusted_wedge",
    "wedge_sharpe_grid", "wedge_history", "run_wedge_analysis", "vol_regime_check",
    # swaptions
    "black_swaption", "bachelier_swaption", "bachelier_implied_vol_swaption",
    "swaption_greeks", "sabr_vol", "sabr_calibrate", "swaption_expected_return",
    "build_vol_surface", "vol_surface_zscore", "swaption_screen", "swap_annuity",
    # portfolio
    "rolling_beta", "hedge_ratio", "regression_summary", "efficient_frontier",
    "max_sharpe_portfolio", "min_variance_portfolio", "rolling_sharpe", "sharpe_table",
    "annual_move_indicator", "cross_country_beta", "multi_country_beta_table",
    # table_generator
    "expected_return_table", "sharpe_table_from_rates", "weekly_update_grid",
    "milkboxes_table", "spread_options_table", "generate_weekly_report",
    "style_returns_table", "style_zscore_table",
    "OUTRIGHT_TENORS", "SPREAD_PAIRS", "FLY_TRIPLETS",
]
