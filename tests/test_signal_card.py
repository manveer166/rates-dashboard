"""Tests for the signal_card helpers (formatting only — UI is not tested)."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.components.signal_card import (
    format_trade_plain, trade_direction, _sharpe_color, _z_label,
)


def test_format_trade_plain_outright():
    assert format_trade_plain("Rcv 10Y", "Outright") == "10Y"
    assert format_trade_plain("Pay 5Y", "Outright") == "5Y"


def test_format_trade_plain_curve():
    assert format_trade_plain("Rcv 2Y/10Y", "Curve") == "2Y/10Y curve"
    assert format_trade_plain("Pay 5Y/30Y", "Curve") == "5Y/30Y curve"


def test_format_trade_plain_fly():
    assert format_trade_plain("Rcv 2Y/5Y/10Y", "Fly") == "2Y5Y10Y fly"
    assert format_trade_plain("Pay 5Y/10Y/30Y", "Fly") == "5Y10Y30Y fly"


def test_trade_direction():
    assert trade_direction("Rcv 10Y") == "receive"
    assert trade_direction("Pay 10Y") == "pay"
    assert trade_direction("rcv 5Y/30Y") == "receive"   # case-insensitive
    assert trade_direction("PAY 2Y") == "pay"


def test_sharpe_color_signs():
    """Strong Sharpe gets green; strong negative gets red."""
    assert _sharpe_color(+1.0)[0] == "#4ade80"   # green
    assert _sharpe_color(-1.0)[0] == "#f87171"   # red
    assert _sharpe_color(0.0)[0]  == "#94a8c9"   # grey


def test_z_label_buckets():
    assert _z_label(-2.5)[0] == "deeply cheap"
    assert _z_label(-1.5)[0] == "cheap"
    assert _z_label(0.0)[0]  == "fair to history"
    assert _z_label(+1.5)[0] == "rich"
    assert _z_label(+2.5)[0] == "stretched rich"
