"""Reusable signal/trade card.

A consistent visual language for showing a trade with all its stats — used
on Scanner, Regime, Backtester, Trade-of-the-Week and anywhere else we
present a "this is a signal" block.

Units are explicit:
  • Sharpe          — dimensionless (annualised)
  • Z-score         — dimensionless (1Y lookback unless noted)
  • E[Ret] / PnL    — bps/yr (annualised) or bps (period)
  • Risk / Vol      — bps/yr (annualised stdev)
  • D1W             — bps (1-week change)
  • Hit rate        — % of positive days
  • Max DD          — bps (from peak)
  • Days held       — days
  • DV01            — $/bp
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

import streamlit as st


# ── Trade formatting helpers ─────────────────────────────────────────────

def format_trade_plain(trade: str, type_: str) -> str:
    """'Rcv 2Y/5Y/30Y' + 'Fly' → '2Y5Y30Y fly'."""
    bare = re.sub(r"^(Rcv|Pay)\s+", "", trade)
    if type_ == "Fly":
        return bare.replace("/", "") + " fly"
    if type_ == "Curve":
        return f"{bare} curve"
    return bare  # outright


def trade_direction(trade: str) -> str:
    """Extract 'receive' or 'pay' from a trade string, default 'receive'."""
    return "pay" if trade.lower().startswith("pay") else "receive"


# ── Colour scheme ────────────────────────────────────────────────────────

def _sharpe_color(sharpe: float) -> tuple[str, str]:
    """Return (border_color, badge_color) based on signed Sharpe."""
    if sharpe >= 0.7:    return ("#4ade80", "#166534")   # strong green
    if sharpe >= 0.3:    return ("#a3e635", "#3f6212")   # mild green
    if sharpe >= -0.3:   return ("#94a8c9", "#1a3056")   # neutral grey
    if sharpe >= -0.7:   return ("#fbbf24", "#78350f")   # mild amber
    return ("#f87171", "#7f1d1d")                          # strong red


def _z_label(z: float) -> tuple[str, str]:
    """Return (text, css color) summarising the Z-score's read."""
    if z <= -2.0:  return ("deeply cheap",        "#4ade80")
    if z <= -1.0:  return ("cheap",                "#84cc16")
    if z <= -0.5:  return ("modestly cheap",       "#a3e635")
    if z <   0.5:  return ("fair to history",      "#94a8c9")
    if z <   1.0:  return ("modestly rich",        "#fbbf24")
    if z <   2.0:  return ("rich",                 "#fb923c")
    return ("stretched rich",                       "#f87171")


# ── Single-card renderer ─────────────────────────────────────────────────

def render_signal_card(
    *,
    trade: str,
    type_: str,
    sharpe: float,
    z: float,
    expected_return_bps_yr: Optional[float] = None,
    risk_bps_yr: Optional[float] = None,
    d1w_bps: Optional[float] = None,
    hit_rate_pct: Optional[float] = None,
    max_dd_bps: Optional[float] = None,
    days: Optional[int] = None,
    direction: Optional[str] = None,
    tags: Optional[Iterable[str]] = None,
    note: Optional[str] = None,
    compact: bool = False,
) -> None:
    """Render a single signal card.

    Pass whatever stats you have; missing ones are simply omitted.
    Direction auto-derives from the sign of Sharpe (Sharpe < 0 → pay) unless
    explicitly provided.
    """
    if direction is None:
        direction = trade_direction(trade) if trade.lower().startswith(("rcv", "pay")) \
                    else ("receive" if sharpe >= 0 else "pay")

    name = format_trade_plain(trade, type_)
    border, badge_bg = _sharpe_color(abs(sharpe) if direction == "pay" and sharpe < 0
                                       else sharpe)
    z_text, z_color = _z_label(z)

    # Header: direction badge + trade name
    dir_color = "#4ade80" if direction == "receive" else "#fb923c"

    # Build stats rows
    stats_html = []
    def _row(label: str, value: str, color: str = "#e8eef9"):
        stats_html.append(
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:4px 0;border-bottom:1px solid #1a3056;font-size:13px">'
            f'<span style="color:#94a8c9">{label}</span>'
            f'<span style="color:{color};font-weight:600">{value}</span></div>'
        )

    _row("Sharpe (annualised)", f"{sharpe:+.2f}", border)
    _row("Z-score (1Y)", f"{z:+.2f} · {z_text}", z_color)
    if expected_return_bps_yr is not None:
        # Signed by direction
        er = expected_return_bps_yr if direction == "receive" else -expected_return_bps_yr
        _row("Expected return", f"{er:+.0f} bps/yr",
             "#4ade80" if er > 0 else "#f87171")
    if risk_bps_yr is not None:
        _row("Risk (annualised vol)", f"{risk_bps_yr:.0f} bps/yr")
    if d1w_bps is not None:
        _row("1-week move", f"{d1w_bps:+.1f} bps",
             "#94a8c9" if abs(d1w_bps) < 5 else
             ("#4ade80" if d1w_bps > 0 else "#f87171"))
    if hit_rate_pct is not None:
        _row("Hit rate", f"{hit_rate_pct:.0f}%",
             "#4ade80" if hit_rate_pct > 55 else
             "#f87171" if hit_rate_pct < 45 else "#94a8c9")
    if max_dd_bps is not None:
        _row("Max drawdown", f"{max_dd_bps:.0f} bps", "#f87171")
    if days is not None:
        _row("Sample", f"{days} days")

    tags_html = ""
    if tags:
        tags_html = '<div style="margin-top:10px">' + "".join(
            f'<span style="background:#1a3056;color:#4fc3f7;padding:3px 9px;'
            f'border-radius:11px;font-size:10.5px;margin-right:5px;'
            f'letter-spacing:0.3px;font-weight:600">{t}</span>'
            for t in tags
        ) + "</div>"

    note_html = ""
    if note:
        note_html = (
            f'<div style="color:#cbd5e1;font-size:12px;line-height:1.5;'
            f'margin-top:10px;padding-top:10px;border-top:1px solid #1a3056">'
            f'{note}</div>'
        )

    padding = "10px 14px" if compact else "14px 18px"
    name_size = "16px" if compact else "20px"
    direction_size = "10px" if compact else "11px"

    st.markdown(
        f"""
        <div style='background:#122340;border-left:4px solid {border};
                    border-radius:8px;padding:{padding};margin:6px 0;
                    box-shadow:0 1px 3px rgba(0,0,0,0.2)'>
          <div style='display:flex;justify-content:space-between;
                      align-items:baseline;margin-bottom:8px'>
            <div>
              <div style='color:{dir_color};font-size:{direction_size};
                          letter-spacing:1.5px;font-weight:700;'>
                {direction.upper()}
              </div>
              <div style='color:#e8eef9;font-size:{name_size};font-weight:700;
                          margin-top:2px'>{name}</div>
            </div>
            <div style='background:{badge_bg};color:white;padding:3px 10px;
                        border-radius:5px;font-size:11.5px;font-weight:700'>
              {type_.upper()}
            </div>
          </div>
          {''.join(stats_html)}
          {tags_html}
          {note_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Multi-card grid ──────────────────────────────────────────────────────

def render_signal_grid(cards: list[dict], n_cols: int = 3,
                       compact: bool = True) -> None:
    """Render a grid of signal cards. Each `cards[i]` is the kwargs dict
    for `render_signal_card`."""
    if not cards:
        return
    rows = [cards[i:i + n_cols] for i in range(0, len(cards), n_cols)]
    for row in rows:
        cols = st.columns(n_cols)
        for col, card in zip(cols, row):
            with col:
                render_signal_card(compact=compact, **card)


# ── Branded market KPI cards (data pages, not trade ideas) ──────────────

def render_market_kpi_row(items: list[dict]) -> None:
    """Render a row of branded mini-cards for market metrics (yields, FX,
    credit, vol, etc.). Same visual language as signal cards but without
    trade-specific fields.

    Each item:
        {
            "label":   "10Y UST",
            "value":   "4.31%",
            "unit":    "% (annualised)",   # explicit units string
            "delta":   "+3 bps (1w)",      # optional, shown smaller
            "color":   "#4fc3f7",          # optional border / accent
            "hint":    "Cash 10Y",         # optional tooltip-style caption
        }
    """
    if not items:
        return
    cols = st.columns(len(items))
    for col, it in zip(cols, items):
        color = it.get("color", "#4fc3f7")
        delta_html = ""
        if it.get("delta"):
            delta_color = "#4ade80" if it["delta"].startswith("+") else \
                           "#f87171" if it["delta"].startswith("-") else "#94a8c9"
            delta_html = (f'<div style="color:{delta_color};font-size:11.5px;'
                           f'margin-top:4px;font-weight:600">{it["delta"]}</div>')
        hint_html = (f'<div style="color:#6a7e9e;font-size:10.5px;'
                      f'margin-top:6px">{it["hint"]}</div>' if it.get("hint") else "")
        unit_html = (f'<span style="color:#94a8c9;font-size:10.5px;'
                      f'letter-spacing:0.5px;font-weight:500;'
                      f'margin-left:4px">{it["unit"]}</span>'
                      if it.get("unit") else "")
        with col:
            st.markdown(
                f"""
                <div style='background:#122340;border-left:3px solid {color};
                            border-radius:6px;padding:10px 14px;
                            margin:4px 0;height:100%;'>
                  <div style='color:#94a8c9;font-size:10.5px;letter-spacing:1px;
                              font-weight:700;text-transform:uppercase'>
                      {it["label"]}{unit_html}
                  </div>
                  <div style='color:#e8eef9;font-size:22px;font-weight:700;
                              margin-top:6px;line-height:1.1'>{it["value"]}</div>
                  {delta_html}
                  {hint_html}
                </div>
                """,
                unsafe_allow_html=True,
            )


# ── Legend (drop somewhere on a page that uses cards) ────────────────────

def render_units_legend() -> None:
    """Explains every unit shown on cards. Useful inside an expander."""
    st.caption(
        "**Units key.** *Sharpe* = annualised, dimensionless. "
        "*Z-score* = 1-year lookback, dimensionless. "
        "*E[Ret]* in bps per year (annualised). "
        "*Risk* in bps per year (annualised stdev). "
        "*1w move* in bps. "
        "*Hit rate* = % of positive trading days. "
        "*Max DD* in bps from peak. "
        "*DV01* = $ per basis point."
    )
