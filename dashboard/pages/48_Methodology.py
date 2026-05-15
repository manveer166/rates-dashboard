"""Page 48 — Methodology.

The honest documentation. Every assumption, every formula, every
limitation. Free public page — readers should be able to audit every
number on the dashboard against this.

If you're considering subscribing and want to know whether the math
holds up, this is the page that answers that question. If you find a
gap or disagree with a choice, that's a feature-request waiting to be
filed.
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import init_session_state, password_gate

st.set_page_config(page_title="Methodology", page_icon="📐", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Methodology")

st.title("📐 Methodology")
st.markdown(
    '<p style="color:var(--c-text-2);font-size:15px;margin-top:-4px;'
    'margin-bottom:14px;">'
    "Every formula, every assumption, every known limitation. If you want "
    "to audit a number, start here. Last reviewed: 2026-05-15."
    "</p>",
    unsafe_allow_html=True,
)
st.divider()


# ── Curve construction ───────────────────────────────────────────────────
st.subheader("1. Curve construction")
st.markdown(
    """
The dashboard treats the **observed FRED constant-maturity Treasury yields**
(DGS1MO, DGS3MO, …, DGS30) as the yields-to-maturity of hypothetical par
bonds at each tenor. The "curve" is the piecewise-linear interpolation
across those points.

**Conventions used throughout:**

- Coupons: **semi-annual** (USD Treasury / swap convention)
- Day-count: **act/365** for analytical purposes (close enough to the
  act/365.25 conventions for research; not used for settlement math)
- Compounding: **semi-annual** in price/yield math; convertible to
  continuous when needed for forward-rate / discount-factor calcs

**What we don't do** (yet):

- No separate **OIS discount curve** — discounting uses the par yield itself
  rather than risk-free SOFR-derived discount factors. For receive/pay
  spreads on swap curves this is mathematically equivalent at the par
  level; for non-par or far-from-par positions, the approximation
  understates the impact of discount-curve curvature.
- No **collateral substitution** / CSA-aware discounting.
- No **on-the-run vs off-the-run** distinction — all benchmark points are
  treated as on-the-run.
"""
)
st.divider()


# ── DV01 ─────────────────────────────────────────────────────────────────
st.subheader("2. DV01 — Dollar Value of an 01")
st.markdown(
    """
DV01 = the dollar P&L of a $1M par-notional position for a 1bp move in
yield. Computed from the full cash-flow schedule, not a duration shortcut.
"""
)
st.latex(r"""
\text{DV01} \;=\; \text{ModDur} \,\cdot\, \text{Price} \,\cdot\, \text{Notional} \,\cdot\, 10^{-4}
""")
st.latex(r"""
\text{ModDur} \;=\; \frac{1}{P}\sum_{i=1}^{N} t_i \cdot \frac{CF_i}{(1 + y/f)^{t_i f}} \;\cdot\; \frac{1}{1 + y/f}
""")
st.markdown(
    """
Where:

- $CF_i$ = the i-th cash flow ($c/f$ per period, plus face on the last)
- $t_i$ = time to that cash flow, in years
- $y$ = yield-to-maturity (the observed par yield at this tenor)
- $f$ = coupon frequency (2 for USD)
- $P$ = bond price (= 100 for a par bond)

Implementation lives in `fixed_income/risk.py::dv01_par()`. The legacy
shortcut `approx_dv01()` is preserved as an alias and resolves to the same
function — there is now **one DV01 path** across the scanner, the
trade builder, the backtester, and the alert generator.
"""
)
st.info(
    "💡 **DV01 sanity check (USD, 4.00% par yields):**  "
    "2Y ≈ $190 / bp · 5Y ≈ $449 / bp · 10Y ≈ $818 / bp · 30Y ≈ $1,738 / bp "
    "per $1M notional."
)
st.divider()


# ── Convexity ────────────────────────────────────────────────────────────
st.subheader("3. Convexity — and where it gets used")
st.markdown(
    """
The second-order yield sensitivity. Long-bond / receiver positions are
**long convexity** (favourable: the price-yield curve is convex); short
bond / payer positions are **short convexity** (unfavourable).
"""
)
st.latex(r"""
C \;=\; \frac{1}{P f^2}\sum_{i=1}^{N} \frac{CF_i \cdot n_i (n_i + 1)}{(1 + y/f)^{\,n_i + 2}}
""")
st.markdown(
    "where $n_i = t_i f$ (period index). The expected annual P&L "
    "contribution from convexity, given annual yield std $\\sigma$, is:"
)
st.latex(r"""
\mathbb{E}[\text{Conv P\&L}] \;=\; \tfrac{1}{2} \cdot C \cdot \sigma^2 \cdot \text{Notional}
""")
st.markdown(
    """
This is what the **scanner adds to expected return** (the `Conv` column).
For a 30Y receiver with annual yield vol ≈ 60 bps, convexity contributes
roughly **+3 bps/yr** to E[Ret] — not huge, but meaningful at the
ranking margin.

**Where convexity shows up:**

- Scanner: included in the `E[Ret]` column for outrights, curves, and
  flies. Fly receivers typically show **negative** convexity (short the
  wings dominates the belly).
- Trade Builder: shown alongside DV01 in the ticket.
- Backtester: P&L includes a convexity adjustment for large yield moves
  (small for typical backtest windows).
- Risk file: `fixed_income/risk.py::convexity_par()`.

**Multi-leg convexity (curves & flies):**

For DV01-neutral structures, convexity comes from each leg's own
contribution weighted by its notional. A receive-long / pay-short
DV01-neutral curve has:

$$C_{\\text{net}} = C_{\\text{long}} - C_{\\text{short}} \\cdot \\frac{DV01_{\\text{long}}}{DV01_{\\text{short}}}$$

For a DV01-neutral fly (receive belly, pay equal-DV01 wings):

$$C_{\\text{net}} = C_{\\text{belly}} - C_{w_1} \\cdot \\frac{DV01_b}{2 \\cdot DV01_{w_1}} - C_{w_2} \\cdot \\frac{DV01_b}{2 \\cdot DV01_{w_2}}$$
"""
)
st.divider()


# ── Carry & rolldown ─────────────────────────────────────────────────────
st.subheader("4. Carry & rolldown")
st.markdown(
    """
**Carry** is the P&L you earn from holding a position over time, assuming
the curve doesn't move. **Rolldown** is the P&L from your position rolling
down the curve as time passes.

We use a **forward-rate-based carry**: the implied forward rate at the
horizon (1 month default) minus today's spot rate, weighted by the leg's
duration. This is more accurate than a simple slope proxy because it
correctly handles the term structure of forward rates.

Implementation: `fixed_income/carry_rolldown.py::forward_carry_rolldown()`.
"""
)
st.latex(r"""
\text{Forward rate } f(t_1, t_2) \;=\; \frac{(1 + y(t_2)/f)^{f t_2}}{(1 + y(t_1)/f)^{f t_1}}\bigg|^{1/(f(t_2 - t_1))} - 1
""")
st.markdown(
    """
**Rolldown** is computed as the difference between today's par yield at
tenor $T$ and the interpolated par yield at $(T - \\Delta t)$, where
$\\Delta t$ is the holding period. The curve is held **static** during
rolldown — i.e. it's a deterministic "if the curve doesn't move, this
is what you earn from time passing" calculation.

**Known approximations:**

- Funding rate: we use SOFR (or the current overnight reference) for
  all carry calcs. A real desk would use trade-specific repo or
  collateral curves. For broad-market screens, SOFR is close enough.
- Mean reversion: the Trade Decomposition page adds an optional
  mean-reversion term computed as `z × σ × 0.5` (half-reversion over the
  holding period). This is a **heuristic** — not regime-fit and not
  derived from empirical decay rates.
"""
)
st.divider()


# ── Transaction costs ────────────────────────────────────────────────────
st.subheader("5. Transaction costs")
st.markdown(
    """
Round-trip bid/ask widths applied to the backtester and the scanner's
E[Ret]. Values are **practitioner consensus** for USD on-the-run benchmark
trading circa 2024-26. Off-the-run, end-of-day, or stressed liquidity
periods widen materially. Source: composite of dealer indications and
public TRACE data, not a single licensed feed.
"""
)
import pandas as pd
_tcost_df = pd.DataFrame([
    {"Tenor": "1Y",  "Treasury (bps)": 0.5, "Swap (bps)": 0.25},
    {"Tenor": "2Y",  "Treasury (bps)": 0.5, "Swap (bps)": 0.25},
    {"Tenor": "3Y",  "Treasury (bps)": 0.5, "Swap (bps)": 0.25},
    {"Tenor": "5Y",  "Treasury (bps)": 0.5, "Swap (bps)": 0.25},
    {"Tenor": "7Y",  "Treasury (bps)": 0.7, "Swap (bps)": 0.50},
    {"Tenor": "10Y", "Treasury (bps)": 0.5, "Swap (bps)": 0.25},
    {"Tenor": "20Y", "Treasury (bps)": 1.5, "Swap (bps)": 0.75},
    {"Tenor": "30Y", "Treasury (bps)": 1.5, "Swap (bps)": 0.75},
])
st.caption("One-way bid/ask in bps yield. Round-trip = 2×.")
st.dataframe(_tcost_df.set_index("Tenor"), use_container_width=True)
st.markdown(
    """
**Multi-leg structures:** the per-leg bid/ask in bps yield equivalent adds
linearly under DV01-equivalence — the notional ratios that DV01-match the
legs also bp-equivalence the cost. So a 2s10s round-trip = 2 × (0.5 + 0.5) =
**2 bps** in long-leg yield equivalent; a 2/5/10 fly = 2 × (0.5 + 0.5 + 0.5)
= **3 bps**.

Implementation: `fixed_income/risk.py::bid_ask_bps()`,
`tcost_outright_bps()`, `tcost_curve_bps()`, `tcost_fly_bps()`.
"""
)
st.divider()


# ── Scanner E[Ret] composition ───────────────────────────────────────────
st.subheader("6. Scanner — what `E[Ret]` actually contains")
st.markdown(
    """
Each row's expected annualised return (bps/yr) is the sum of three
components, in this order:

$$E[\\text{Ret}] = \\underbrace{(C_{\\text{carry}} + C_{\\text{rolldown}}) \\times 12}_{\\text{annualised carry+roll}}
 \\;+\\; \\underbrace{\\tfrac{1}{2} C \\sigma^2 \\cdot N / \\text{DV01}}_{\\text{convexity pickup}}
 \\;-\\; \\underbrace{\\text{round-trip bid/ask}}_{\\text{transaction cost}}$$

Where $\\sigma$ is the **leg yield rvol** (not the spread vol, for
curve/fly trades — see the convexity section for why).

**Sharpe = E[Ret] / annualised vol of the trade's P&L series.**

The `Conv` and `TCost` columns surface the convexity and tcost components
separately so you can see what's driving the ranking. The `E[Ret]` column
shows the **net** (carry + rolldown + convexity − tcost).
"""
)
st.divider()


# ── Backtester P&L composition ───────────────────────────────────────────
st.subheader("7. Backtester — three-component P&L")
st.markdown(
    """
Total P&L decomposes into:

1. **Directional**: $\\text{sign} \\times (level_t - level_{\\text{entry}}) \\times 100$ bps
2. **Carry**: $(\\text{annual carry at entry} / 252) \\times \\text{days held}$
3. **Transaction**: $-\\text{round-trip bid/ask}$, charged half at entry and the remainder at exit

Each component is shown separately on the page, and exported in the CSV
under columns `directional_bps`, `carry_bps`, `tcost_bps`,
`cumulative_pnl_bps`.

**Limitations:**

- Carry is computed **once at entry** and accrues linearly. It does NOT
  re-mark as the curve moves through the backtest. For a 1-year+ window
  in a moving market, real carry would be path-dependent — the backtester
  understates this for trades held through a major curve regime change.
- No slippage beyond the bid/ask is modelled. Real execution at size
  pays more, especially in the long-end and during stress.
- No convexity adjustment to daily P&L (small for most backtest windows,
  but for big yield moves the directional component over-states the
  loss/under-states the gain for a long-convex position).
"""
)
st.divider()


# ── Regime detector ──────────────────────────────────────────────────────
st.subheader("8. Regime detector — what it is and isn't")
st.markdown(
    """
The Regime page does:

1. Builds a 4-dimensional feature vector at each historical date: curve
   level (10Y), slope (2s10s), curvature (5Y bullet), and VIX z-score.
2. Standardises the features.
3. Runs **K-means with k=4** to partition history into four clusters.
4. For each cluster, computes the **Sharpe of two archetypes** (5Y outright
   receiver carry, 2s5s10s belly fly) on the dates that belong to that
   cluster.

**What this is:**

- A clustering of historical rate states based on observable features.
- A "conditional on this kind of market, here's what's worked" lookup.

**What this isn't:**

- Not a Markov-switching model or HMM — there's no forward-looking
  transition matrix between regimes.
- Not regime *detection* in the statistical sense — it's regime
  *clustering*. The "regime" the model says we're in today is just the
  cluster centroid closest to today's feature vector.
- Conditional Sharpe is unconditional Sharpe **split by dates**, not a
  separate fit per regime.

For research idea-generation this is useful — if "carry > convexity in
regime X" and we're in regime X today, the screen is suggestive. For a
risk system or a desk's regime-conditional sizing, you'd want a real
state-space model.
"""
)
st.divider()


# ── Known limitations summary ────────────────────────────────────────────
st.subheader("9. Known limitations — the honest list")
st.markdown(
    """
| Area | Current implementation | What a top-tier desk would do |
|---|---|---|
| **Discount curve** | Single par curve, semi-annual | Multi-curve OIS, dual-curve discounting |
| **Funding** | SOFR for everything | Trade-specific repo / collateral curves |
| **Carry in backtest** | Static at entry | Re-marked daily as the curve moves |
| **Slippage** | Bid/ask only | Size-impact model, intraday execution slippage |
| **Convexity** | Used in scanner E[Ret], not in backtester daily P&L | Convexity-adjusted P&L on every mark |
| **Regime** | K-means clustering | Markov-switching / HMM with transition matrix |
| **Mean reversion** | Heuristic 50% over horizon | Empirically-fit decay per pair |
| **Cross-currency** | Not modelled | Full xccy basis curves |
| **Bond futures** | Cash treasuries only | Conversion factors, CTD selection, basis |

**Bottom line:** this is **research-grade** analytical infrastructure for
rates RV. It is **not** an institutional risk system or a registered
investment advisor's compliance-audited tool. Use it the way a desk uses
internal screens — to filter ideas, ground intuition, and frame trade
construction; not as the final word on execution or P&L.

If you find a math gap or want a specific limitation closed, the
[Feature Request](/Feature_Request) page is the fastest way in.
"""
)
