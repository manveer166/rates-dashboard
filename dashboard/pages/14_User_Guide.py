"""
11_User_Guide.py — Interactive tutorial that walks through each dashboard page.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from dashboard.components.header import render_page_header

st.set_page_config(page_title="User Guide", page_icon="📘", layout="wide")
# No password gate — accessible from login page via "How to use" button
render_page_header(current="Guide")

# ══════════════════════════════════════════════════════════════════════════
# MODE: Landing vs Tutorial
# ══════════════════════════════════════════════════════════════════════════

if "tutorial_active" not in st.session_state:
    st.session_state["tutorial_active"] = False
if "tutorial_step" not in st.session_state:
    st.session_state["tutorial_step"] = 0


# ── LANDING PAGE ──────────────────────────────────────────────────────────
if not st.session_state["tutorial_active"]:
    st.markdown(
        "<div style='text-align:center; padding-top:40px;'>"
        "<h1>📘 How to Use the Rates Dashboard</h1>"
        "<p style='color:#8892a4; font-size:18px; margin-bottom:10px;'>"
        "A professional-grade analytics platform for US Treasury yields,<br>"
        "swap rates, credit spreads, and interest rate trade ideas.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.divider()

    # Quick overview cards
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("#### 📊 Market Data")
        st.markdown(
            "Live US Treasury yields, international government bonds, "
            "SOFR swap rates, and credit spreads from FRED and Treasury.gov."
        )
    with col2:
        st.markdown("#### 🔬 Trade Scanner")
        st.markdown(
            "Scans 200+ outrights, curves, and flies. Ranks by Sharpe ratio "
            "with carry, rolldown, convexity, and z-score analytics."
        )
    with col3:
        st.markdown("#### 📋 Track Record")
        st.markdown(
            "Log trade ideas, track P&L, export reports, "
            "and get AI-powered commentary on your best opportunities."
        )

    st.divider()

    # Pages overview
    st.markdown("#### Dashboard Pages")
    pages_info = [
        ("📈", "Home", "KPI metrics, yield curve snapshot, international yields, 2s10s history"),
        ("📉", "Yield Curve", "Curve shapes, change heatmaps, animated evolution, tenor time series"),
        ("📊", "Spreads", "Key spreads (2s10s, 5s30s), z-score overlays, distribution analysis"),
        ("📐", "Regression", "Regress any tenor pair, R-squared, beta, rich/cheap residuals"),
        ("🧮", "PCA", "Principal components: level, slope, curvature factor decomposition"),
        ("🔗", "Correlation", "Rolling correlation heatmap, regime change detection"),
        ("🔬", "Analysis", "Trade Scanner, bubble charts, detail panel, AI commentary, PDF export"),
        ("📁", "Data Sources", "Data provenance, cache status, series availability"),
        ("📖", "Glossary", "Definitions for every metric and concept used in the dashboard"),
        ("💡", "Feature Request", "Submit ideas, bug reports, enhancement requests"),
        ("🔔", "Alerts", "Configure daily/weekly email alerts for top trades and z-score extremes"),
        ("📋", "Trade Tracker", "Log trades, track P&L, build your track record"),
        ("🌊", "Vol Surface", "Swaption vol surface, heatmaps, SABR smile estimator"),
        ("🔒", "Admin", "Subscriber management, feature request review, settings"),
    ]

    for emoji, name, desc in pages_info:
        st.markdown(f"**{emoji} {name}** — {desc}")

    st.divider()

    # Tutorial launch
    _c1, _c2, _c3 = st.columns([1, 2, 1])
    with _c2:
        if st.button("Start Tutorial", use_container_width=True, type="primary"):
            st.session_state["tutorial_active"] = True
            st.session_state["tutorial_step"] = 0
            st.rerun()

    st.stop()


# ══════════════════════════════════════════════════════════════════════════
# TUTORIAL MODE — page-by-page interactive walkthrough
# ══════════════════════════════════════════════════════════════════════════

TUTORIAL = [
    # (title, page_url, content_func)
    {
        "title": "Home Page",
        "page": "/",
        "content": """
**What you'll see:** The main dashboard with live market data.

**KPI Metrics (top section):**
- US Treasury yields: 1Y, 2Y, 5Y, 10Y, 30Y with delta arrows showing change
- Key spreads: 2s10s and 5s30s
- International yields: Germany, UK, Switzerland, Japan
- SOFR swap rates and credit spreads (IG, HY, BBB OAS)

**Charts:**
- **Yield Curve Snapshot** — today's curve vs N months ago
- **International 10Y Bar Chart** — compare global 10Y yields at a glance
- **10Y Yield History** — time series across US, DE, UK, CH, JP
- **2s10s Spread** — curve slope with shaded fill and zero line

**Try this:**
1. Use the **lookback slider** at the top to switch between 3M and 2Y comparisons
2. Hover over any chart point for exact values
3. Click the **Substack** button at the bottom for the latest Macro Manv posts
""",
    },
    {
        "title": "Yield Curve",
        "page": "/Yield_Curve",
        "content": """
**What you'll see:** Deep dive into the shape and evolution of the yield curve.

**Features:**
- **Curve snapshot** — compare today vs any historical date
- **Curve change heatmap** — which tenors moved most over your lookback
- **Animated curve** — watch the curve evolve day-by-day (hit play)
- **Tenor time series** — plot individual tenors over time

**What to look for:**
- **Steepening** — long-end rising faster than short-end (bullish for steepeners)
- **Flattening** — spread between short and long end narrowing
- **Inversion** — 2Y above 10Y (classic recession signal)
- **Parallel shift** — entire curve moving up/down together (PC1 move)

**Try this:**
1. Switch the comparison date to see how the curve looked 6 months ago
2. Look for tenors with the biggest absolute change — these are where the opportunity is
""",
    },
    {
        "title": "Spreads",
        "page": "/Spreads",
        "content": """
**What you'll see:** Key yield spread time series and analysis.

**Spreads tracked:**
- **2s10s** — the classic curve slope indicator
- **5s30s** — long-end steepness
- **Custom** — build any tenor pair you want

**Analysis tools:**
- Time series with configurable lookback period
- **Z-score overlay** — instantly see if a spread is at an extreme
- **Distribution histogram** — where does the current level sit historically?

**Trading insight:**
A z-score below **-2** on 2s10s means the curve is unusually flat relative to recent history — that's a potential **steepener** entry point. Above +2 means unusually steep — potential flattener.

**Try this:**
1. Toggle the z-score overlay on and look for extremes
2. Compare the current z-score with the distribution to gauge how rare this level is
""",
    },
    {
        "title": "Regression",
        "page": "/Regression",
        "content": """
**What you'll see:** Statistical regression between any two rates or spreads.

**How it works:**
- Pick an X variable (e.g. 10Y yield) and a Y variable (e.g. 30Y yield)
- The tool runs OLS regression and shows the scatter plot + regression line
- **R-squared** tells you how much of Y is explained by X
- **Beta** is the slope — how much Y moves per 1bp move in X

**Rich/Cheap signals:**
- The **residual** (actual Y minus predicted Y) tells you if Y is cheap or rich
- Positive residual = Y is **higher than model predicts** = cheap (for receivers)
- Negative residual = Y is **lower than model predicts** = rich

**Try this:**
1. Regress 30Y vs 10Y — the residual shows if 10s30s is rich or cheap vs history
2. Try 2Y vs SOFR — see how the front end tracks the overnight rate
""",
    },
    {
        "title": "PCA",
        "page": "/PCA",
        "content": """
**What you'll see:** Principal Component Analysis of the yield curve.

**The three factors:**
- **PC1 (Level)** — parallel shifts, explains ~90% of all curve moves
- **PC2 (Slope)** — steepening/flattening, explains ~8%
- **PC3 (Curvature)** — butterfly/belly moves, explains ~2%

**What's shown:**
- **Factor loadings** — how each tenor responds to each component
- **Factor scores** — time series of each factor (shows the regime)
- **Variance explained** — pie chart of contribution

**Trading insight:**
If PC2 is at a z-score extreme, the curve slope is unusually steep or flat — that's prime territory for curve trades. PC3 extremes signal butterfly opportunities.

**Try this:**
1. Look at the PC2 factor score — is slope unusually high or low?
2. Check PC3 — if it's extreme, the belly is mispriced relative to the wings
""",
    },
    {
        "title": "Correlation",
        "page": "/Correlation",
        "content": """
**What you'll see:** Rolling correlation matrix between tenors and spreads.

**What to look for:**
- **High correlation (> 0.9)** between tenors means parallel moves dominate — outright risk is the main driver
- **Decorrelation** between 2Y and 30Y means curve trades have more opportunity
- **Negative correlation** between rates and credit = risk-off regime

**Why it matters:**
When correlations break down, relative value trades (curves, flies) become more attractive because legs move independently. When everything is 0.99 correlated, it's an outright market.

**Try this:**
1. Adjust the rolling window — 21d for recent regime, 252d for the structural picture
2. Look for pairs where correlation recently dropped — that's where opportunities emerge
""",
    },
    {
        "title": "Trade Scanner",
        "page": "/Analysis",
        "content": """
**What you'll see:** The core of the dashboard — every possible trade ranked.

**What it scans:**
- **~7 outrights** (Rcv 2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y)
- **~21 DV01 curves** (every pair)
- **~21 beta curves** (zero 10Y exposure, marked with *)
- **~35 DV01 flies** (every triple)
- **~35 beta flies**
- **= 100+ trades** all computed in seconds

**Controls (top of page):**
| Control | What it does |
|---------|-------------|
| **Direction** | Receive (profit from rate falls) or Pay |
| **Z-score Window** | 3M, 6M, or 1Y lookback |
| **Vol Window** | 21d to 126d for realised vol |
| **Holding Period** | 1M or 3M (scales carry/roll) |
| **Type filter** | Show/hide Outright, Curve, Fly, etc. |

**The table columns:**
| Column | What it means |
|--------|-------------|
| **Carry / Roll** | Funding carry + curve rolldown (bps) |
| **Conv** | Net convexity pickup across all legs (bps/yr) |
| **E[Ret]** | Annualised expected return |
| **Sharpe** | E[Ret] / Risk — the key ranking metric |
| **Z** | How cheap/rich vs rolling window |

**How to find trades:**
1. Sort by **Sharpe** descending
2. Look for **low Z + high Sharpe** (cheap with good carry)
3. Check **Δ1W** — avoid trades that already ran

**Export:** Use the **Download CSV** or **Download Report** buttons below the table.

**AI Commentary:** If ANTHROPIC_API_KEY is set, expand "AI Trade Commentary" for Claude's analysis.

**Try this:**
1. Set Direction to "Receive", sort by Sharpe
2. Filter to just "Fly" — which butterflies have the best risk-adjusted carry?
3. Click on the bubble charts below to visualise the trade landscape
""",
    },
    {
        "title": "Trade Scanner — Bubble Charts",
        "page": "/Analysis",
        "content": """
**What you'll see:** Two bubble charts below the scanner table.

**Chart 1: Expected Sharpe vs Z-score**
- X-axis = Z-score (left = cheap, right = rich)
- Y-axis = Expected Sharpe
- **Best quadrant: top-left** (cheap AND high Sharpe)
- Dashed crosshairs at zero on both axes

**Chart 2: Expected Return vs Risk**
- X-axis = Risk (realised vol in bps/yr)
- Y-axis = E[Return] (bps/yr)
- Trades above the zero line have positive expected return
- The steeper the line from origin to a dot, the higher its Sharpe

**Bubble encoding:**
- **Colour** = trade type (blue = outright, orange = curve, green = fly)
- **Size** = absolute 1-week change (bigger = more recent movement)
- **Hover** any bubble for the trade name and exact values

**Type toggle:** Independent of the table filter — you can show only flies on the chart while keeping everything in the table.

**Try this:**
1. Toggle to show only "Fly" — which butterflies sit in the top-left sweet spot?
2. Look for outliers — a bubble far from the pack might be a signal or a data issue
""",
    },
    {
        "title": "Trade Scanner — Detail Panel",
        "page": "/Analysis",
        "content": """
**What you'll see:** Below the bubble charts — a deep dive into any single trade.

**How to use:**
1. Select the **trade type** (Outright, Curve, Curve*, Fly, Fly*)
2. Pick the **tenor(s)** — e.g. for a fly, choose Wing 1, Belly, Wing 2
3. A **4-panel chart** appears:

| Panel | Shows |
|-------|-------|
| **Level** | Time series of the rate/spread/fly level |
| **Z-score** | Rolling z-score with bands at +/-1.5 and +/-2 |
| **E[Return]** | Current expected return as a flat line |
| **Rolling Sharpe** | Sharpe evolution using rolling vol |

**Summary metrics** below the chart:
- Current level, z-score, E[Ret], Sharpe, and 1D/1W/1M changes
- Colour-coded: green = attractive, red = unattractive

**Formulas:**
- Carry+Roll: `forward_swap_rate(hold, T) - spot(T)` per leg
- Convexity: `0.5 * Conv * sigma^2 * 10000` net across legs
- Sharpe: `E[Ret] / Realised_Vol`

**Try this:**
1. Select "Fly" > 2Y / 5Y / 10Y — look at the z-score panel for entry signals
2. Compare the rolling Sharpe over time — is carry consistently positive or cyclical?
""",
    },
    {
        "title": "Alerts",
        "page": "/Alerts",
        "content": """
**What you'll see:** Email alert configuration page.

**How it works:**
1. Set your **email address** and choose **daily or weekly** frequency
2. Configure what to include:
   - **Top N trades by Sharpe** — the best risk-adjusted ideas
   - **Z-score extremes** — trades at historically extreme levels
   - **Big weekly movers** — trades that moved significantly
3. **Preview** the alert body before sending
4. **Send** manually or set up a cron job for automation

**Configuration options:**
- Top N count (3-50 trades)
- Z-score threshold (1.0 to 4.0)
- Big mover threshold (bps per week)
- Trade type filter (Outright, Curve, Fly, etc.)

**Try this:**
1. Click "Preview Alert" to see what the email would look like
2. Save your config — it persists between sessions
""",
    },
    {
        "title": "Trade Tracker",
        "page": "/Trade_Tracker",
        "content": """
**What you'll see:** A trade journal with P&L tracking.

**Logging trades:**
1. Enter the **trade name** (e.g. "Rcv 2Y/10Y"), type, direction
2. Set the **entry level** and date
3. Add **notes** — rationale, target, stop loss

**Managing trades:**
- **Open trades** are shown in a table
- **Close** a trade by entering the exit level — P&L is auto-calculated
- P&L formula: `(entry - exit) * 100 * direction` in bps

**Track record:**
- **Total P&L**, **win rate**, **average P&L**, **best/worst** trade
- **Cumulative P&L chart** — see your equity curve
- **Bar chart** — green/red for each trade's P&L
- **CSV export** — download your full trade log

**Try this:**
1. Log a paper trade from the scanner's top Sharpe idea
2. Check back in a week and close it — did the scanner call it right?
""",
    },
    {
        "title": "Vol Surface",
        "page": "/Vol_Surface",
        "content": """
**What you'll see:** A swaption implied volatility surface.

**Views available:**
- **3D Surface** — interactive rotatable surface (expiry x tenor x vol)
- **Heatmap** — 2D colour map of the vol surface
- **Term Structure** — vol curves for each tenor across expiries

**Controls:**
- **Vol type** — Normal (bps/yr) or Lognormal (%)
- **Surface style** — 3D, Heatmap, or Term Structure
- **RV base window** — which realised vol window to use

**SABR Smile section:**
- Select a **tenor** and **expiry** to see the estimated vol smile
- Adjust **Rho** (skew parameter) to see how the smile tilts
- Negative rho = receiver skew (put-like protection is expensive)

**Note:** The surface currently uses realised vols as a proxy. Connect live swaption data for market-implied surface.

**Try this:**
1. Switch to 3D Surface and rotate it — where is vol highest?
2. Compare the 2Y and 30Y term structures — which has steeper vol decay?
3. Adjust Rho on the SABR smile — how does skew affect OTM pricing?
""",
    },
    {
        "title": "Glossary & Reference",
        "page": "/Glossary",
        "content": """
**What you'll see:** Definitions for every term and column in the dashboard.

**Sections covered:**
- **Yield Curve & Rates** — yield, par rate, SOFR, tenor, forward rate
- **DV01 & Duration** — DV01 (bps), modified duration, DV01-neutral, beta-weighted
- **Convexity** — raw convexity, convexity pickup, net convexity for curves/flies
- **Carry & Rolldown** — carry, rolldown, forward carry, total return
- **Trade Types** — outright, curve, fly, receive, pay
- **Scanner Columns** — every column defined with units
- **Statistics** — z-score, percentile, realised vol, Sharpe, beta, correlation
- **Bond Analytics** — ASW, swap spread, box swap, xccy basis
- **Options** — Bachelier, Black, SABR, implied vol, swaption

**Tip:** Keep this page open in a second tab as a quick reference while using the scanner.
""",
    },
    {
        "title": "Tips & Shortcuts",
        "page": None,
        "content": """
**You've completed the tutorial!** Here are some power-user tips:

**Streamlit shortcuts:**
| Key | Action |
|-----|--------|
| `R` | Rerun the current page |
| `C` | Clear cache |

**Chart interactions (Plotly):**
| Action | How |
|--------|-----|
| **Zoom** | Click + drag a rectangle |
| **Pan** | Hold Shift + drag |
| **Reset zoom** | Double-click |
| **Save image** | Camera icon (top-right of chart) |
| **Toggle series** | Click any legend item |

**Workflow suggestions:**
1. Start each session on **Home** — check the KPIs for any big moves
2. Open the **Trade Scanner** — sort by Sharpe, look for low-Z opportunities
3. Use the **Detail Panel** to drill into your best ideas
4. Log interesting trades in the **Trade Tracker**
5. Set up **Alerts** so you don't miss extremes

**Env vars for full features:**
```
ANTHROPIC_API_KEY    → AI trade commentary
GA_MEASUREMENT_ID   → Google Analytics
ADSENSE_CLIENT      → Google AdSense
SMTP_HOST/USER/PASS → Email alerts
```
""",
    },
]

# ── Tutorial navigation ───────────────────────────────────────────────────
step = st.session_state["tutorial_step"]
total = len(TUTORIAL)
current = TUTORIAL[step]

# Header
st.markdown(
    f"<div style='text-align:center;'>"
    f"<p style='color:#8892a4; margin:0;'>TUTORIAL — Step {step+1} of {total}</p>"
    f"<h2 style='margin-top:4px;'>{current['title']}</h2>"
    f"</div>",
    unsafe_allow_html=True,
)
st.progress((step + 1) / total)

# "Go to this page" button
if current.get("page"):
    go_col1, go_col2, go_col3 = st.columns([2, 1.5, 2])
    with go_col2:
        st.link_button(
            f"Open {current['title']} page",
            current["page"],
            use_container_width=True,
        )

st.divider()

# Content
st.markdown(current["content"])

# Navigation
st.divider()
nav_c1, nav_c2, nav_c3, nav_c4, nav_c5 = st.columns([1, 1, 2, 1, 1])

with nav_c1:
    if step > 0:
        if st.button("< Previous", use_container_width=True):
            st.session_state["tutorial_step"] = step - 1
            st.rerun()

with nav_c2:
    # Step selector dropdown
    jump = st.selectbox(
        "Jump to",
        range(total),
        index=step,
        format_func=lambda i: f"{i+1}. {TUTORIAL[i]['title']}",
        key="tut_jump",
        label_visibility="collapsed",
    )
    if jump != step:
        st.session_state["tutorial_step"] = jump
        st.rerun()

with nav_c4:
    if st.button("Exit Tutorial", use_container_width=True):
        st.session_state["tutorial_active"] = False
        st.rerun()

with nav_c5:
    if step < total - 1:
        if st.button("Next >", use_container_width=True, type="primary"):
            st.session_state["tutorial_step"] = step + 1
            st.rerun()
    else:
        if st.button("Finish", use_container_width=True, type="primary"):
            st.session_state["tutorial_active"] = False
            st.rerun()
