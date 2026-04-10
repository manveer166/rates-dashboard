"""
08_Glossary.py — Glossary of fixed-income and rates trading terms.

Provides clear definitions for every metric and concept used in the dashboard.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
from dashboard.state import password_gate
from dashboard.components.header import render_page_header

st.set_page_config(page_title="Glossary", page_icon="📖", layout="wide")
password_gate()
render_page_header(current="Glossary")

st.title("📖 Glossary & Index")
st.caption("Definitions for every metric, column, and concept used across the dashboard.")

st.divider()

# ── Yield Curve & Rates ──────────────────────────────────────────────────
st.subheader("Yield Curve & Rates")

st.markdown("""
| Term | Definition |
|------|-----------|
| **Yield** | The annualised return earned by holding a bond to maturity, expressed as a percentage. |
| **Par Rate** | The coupon rate at which a bond prices at par (100). Equivalent to the swap rate for interest rate swaps. |
| **SOFR** | Secured Overnight Financing Rate — the benchmark overnight rate for USD, replacing LIBOR. |
| **Tenor** | The time remaining until a bond or swap matures (e.g. 2Y, 10Y, 30Y). |
| **Yield Curve** | A plot of yields (y-axis) against tenors (x-axis). Normally upward-sloping: longer maturities pay higher yields. |
| **Curve Steepener** | A trade that profits when the spread between a long-tenor and short-tenor rate widens. |
| **Curve Flattener** | A trade that profits when the spread between a long-tenor and short-tenor rate narrows. |
| **Forward Rate** | The interest rate implied today for a period starting in the future. E.g. the 1y-forward 10Y rate is the 10Y rate starting one year from now. |
""")

st.divider()

# ── DV01 & Duration ──────────────────────────────────────────────────────
st.subheader("DV01 & Duration")

st.markdown("""
| Term | Definition |
|------|-----------|
| **DV01 (Dollar Value of 01)** | The change in price (per 100 notional) for a 1 basis point parallel shift in yield. Shown in bps on the scanner. |
| **Modified Duration** | The percentage price change for a 1% change in yield. Related to DV01: `DV01 ≈ Duration × Price × 0.0001`. |
| **DV01-Neutral** | A curve or fly trade sized so the net DV01 across all legs is zero — i.e. no exposure to a parallel shift. |
| **Beta-Weighted** | A trade weighted by regression beta (vs 10Y) instead of DV01, targeting zero exposure to 10Y moves. Marked with \\* in the scanner. |
""")

st.divider()

# ── Convexity ─────────────────────────────────────────────────────────────
st.subheader("Convexity")

st.markdown("""
| Term | Definition |
|------|-----------|
| **Convexity** | The second derivative of bond price with respect to yield. Measures curvature in the price-yield relationship. |
| **Convexity Pickup** | The expected P&L from convexity over one year: `0.5 × Convexity × σ² × 10000` (bps/yr), where σ is the annualised yield volatility in decimal. |
| **Net Convexity (Curves/Flies)** | DV01-weighted sum of per-leg convexity pickups. For a curve: `per_leg(long) − ratio × per_leg(short)`. For a fly: `per_leg(w1) + w₂ × per_leg(w2) − w_b × per_leg(belly)`. |
| **Positive Convexity** | A position that benefits from higher volatility — gains accelerate and losses decelerate as yields move. |
""")

st.divider()

# ── Carry & Rolldown ──────────────────────────────────────────────────────
st.subheader("Carry & Rolldown")

st.markdown("""
| Term | Definition |
|------|-----------|
| **Carry** | The P&L earned by holding a position assuming rates stay unchanged. For a receiver: `fixed rate − overnight rate`. |
| **Rolldown** | The P&L earned as time passes and the instrument "rolls down" the yield curve — e.g. a 10Y becomes a 9Y11M after one month. |
| **Forward Carry+Roll** | Total carry and rolldown estimated via forward swap rates: `forward_swap_rate(hold, T) − spot(T)` per leg, in bps. This is the break-even: if spot stays below the forward, the receiver profits. |
| **Total Return** | Carry + Rolldown + Convexity pickup. The expected annualised P&L of a trade assuming no rate moves. |
""")

st.divider()

# ── Trade Types ───────────────────────────────────────────────────────────
st.subheader("Trade Types")

st.markdown("""
| Term | Definition |
|------|-----------|
| **Outright** | A single-tenor position. E.g. receive 10Y = long the 10Y rate. |
| **Curve (Spread)** | A two-leg trade: long one tenor, short another, DV01-neutral. E.g. 2s10s = receive 10Y, pay 2Y. |
| **Butterfly (Fly)** | A three-leg trade: buy the wings, sell the belly (or vice versa), DV01-neutral. E.g. 2s5s10s. |
| **Receive** | Enter a position that profits when rates fall (or the spread/fly level falls). Equivalent to "buy the bond". |
| **Pay** | Enter a position that profits when rates rise. Equivalent to "sell the bond" or "short duration". |
""")

st.divider()

# ── Scanner Columns ───────────────────────────────────────────────────────
st.subheader("Scanner Column Definitions")

st.markdown("""
| Column | Unit | Definition |
|--------|------|-----------|
| **Level** | % or bps | Current rate (outrights in %) or spread/fly level (in bps). |
| **DV01** | bps | Dollar value of one basis point per 100 notional. Outrights only. |
| **Carry** | bps | Carry component for the holding period, direction-adjusted. |
| **Roll** | bps | Rolldown component for the holding period, direction-adjusted. |
| **Conv** | bps/yr | Annualised convexity pickup (net across legs for curves/flies). |
| **E[Ret]** | bps/yr | Expected annualised return = (Carry + Roll) annualised + Conv. |
| **Risk** | bps/yr | Realised volatility of daily changes, annualised (√252). |
| **Sharpe** | — | E[Ret] / Risk. Risk-adjusted expected return. |
| **Z** | — | Z-score of the current level vs the rolling window. Low Z = cheap (for receivers). |
| **Δ1D / Δ1W / Δ1M / Δ3M** | bps | Change in level over 1 day / 1 week / 1 month / 3 months. |
""")

st.divider()

# ── Statistical Measures ──────────────────────────────────────────────────
st.subheader("Statistical Measures")

st.markdown("""
| Term | Definition |
|------|-----------|
| **Z-Score** | `(current − mean) / std` over a rolling window. Measures how far the current value is from its recent average in standard deviations. |
| **Percentile Rank** | Where the current value sits in the historical distribution (0–100%). |
| **Realised Volatility** | Standard deviation of daily changes × √252 to annualise. Expressed in bps/yr. |
| **Sharpe Ratio** | Expected return divided by risk. Values above 1.0 are considered attractive. |
| **Beta (β)** | Regression sensitivity of one rate to another (typically vs 10Y). β = Cov(x,y) / Var(y). |
| **Correlation** | Pearson correlation between daily changes of two series. Ranges from −1 to +1. |
""")

st.divider()

# ── Bond Analytics ────────────────────────────────────────────────────────
st.subheader("Bond Analytics")

st.markdown("""
| Term | Definition |
|------|-----------|
| **Asset Swap Spread (ASW)** | The spread over SOFR that equates a bond's cash flows to its market price. ASW > 0 means the bond yields more than the swap curve (cheap). |
| **Swap Spread** | Treasury yield minus the swap rate at the same tenor. Measures the relative value of bonds vs swaps. |
| **Box Swap** | The difference between two swap spreads at different tenors. Used to trade the slope of the swap-spread curve. |
| **Cross-Currency Basis** | Additional spread in a cross-currency swap. Negative basis = USD funding premium. |
""")

st.divider()

# ── Options / Swaptions ──────────────────────────────────────────────────
st.subheader("Options & Swaptions")

st.markdown("""
| Term | Definition |
|------|-----------|
| **Bachelier Model** | Normal (Gaussian) option pricing model where the underlying can go negative. Standard for rate spread options. |
| **Black Model** | Log-normal option pricing model. Used for swaptions when rates are positive. |
| **SABR** | Stochastic Alpha Beta Rho — a volatility smile model that captures skew in swaption markets. |
| **Implied Volatility** | The volatility input that makes a model price match the market price. |
| **Swaption** | An option to enter an interest rate swap. E.g. a 1Y×10Y receiver swaption gives the right to receive 10Y fixed in one year. |
""")

st.divider()

st.caption("Built for [Macro Manv](https://manveersahota.substack.com) subscribers.")
