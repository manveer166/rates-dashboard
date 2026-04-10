"""
tutorial.py — Interactive multi-page guided tour using intro.js.

Injects intro.js into the parent Streamlit frame so it can highlight
real DOM elements (sidebar, KPI cards, charts) with circles + tooltips.

The tour can run in two modes:
  • single-page: just runs the steps for the current page
  • chained:    runs each page's tour, then auto-navigates to the next
                page in PAGE_CHAIN until the chain is complete.
"""

import json

import streamlit as st
import streamlit.components.v1 as components


# ── Chain config ─────────────────────────────────────────────────────────

PAGE_CHAIN = [
    "home",
    "yield_curve",
    "spreads",
    "regression",
    "pca",
    "analysis",
    "vol_surface",
    "trade_tracker",
]

PAGE_URLS = {
    "home":          "/",
    "yield_curve":   "/Yield_Curve",
    "spreads":       "/Spreads",
    "regression":    "/Regression",
    "pca":           "/PCA",
    "analysis":      "/Analysis",
    "vol_surface":   "/Vol_Surface",
    "trade_tracker": "/Trade_Tracker",
}


# ── Step definitions ─────────────────────────────────────────────────────

HOME_STEPS = [
    {
        "title": "📈 Welcome to the Rates Dashboard",
        "intro": (
            "This tour will walk you through every page of the dashboard.<br><br>"
            "After each page, you'll be taken to the next one automatically. "
            "Click <b>✕</b> at any time to exit."
        ),
    },
    {
        "selector": '[data-testid="stSidebar"]',
        "title": "🎛️ Sidebar Controls",
        "intro": (
            "Your control centre.<br><br>"
            "<b>Quick Select:</b> Lookback period (3M – 5Y)<br>"
            "<b>Date Range:</b> Custom dates<br>"
            "<b>Refresh:</b> Force reload from sources"
        ),
        "position": "right",
    },
    {
        "selector": '[data-testid="stMetric"]',
        "title": "📋 KPI Metrics",
        "intro": (
            "Current yields and their change vs the lookback period.<br><br>"
            "🟢 Green = rates fell (good for receivers)<br>"
            "🔴 Red = rates rose"
        ),
        "position": "bottom",
    },
    {
        "selector": ".js-plotly-plot",
        "title": "📉 Yield Curve Chart",
        "intro": (
            "Today's curve vs the curve N months ago.<br><br>"
            "<b>Hover</b> for exact values · <b>Zoom</b> by drag · "
            "<b>Reset</b> by double-click"
        ),
        "position": "top",
    },
    {
        "selector": '[data-testid="stSidebarNav"]',
        "title": "🗂️ Page Navigation",
        "intro": (
            "Every page in the app is listed here. Up next: "
            "<b>Yield Curve</b> for shape & evolution analysis."
        ),
        "position": "right",
    },
]

YIELD_CURVE_STEPS = [
    {
        "title": "📉 Yield Curve Page",
        "intro": (
            "This page shows the <b>full US Treasury curve</b> for any historical "
            "date, fits a <b>Nelson-Siegel</b> model, and tracks how the curve "
            "has evolved over time."
        ),
    },
    {
        "selector": '[data-testid="stSelectbox"]',
        "title": "📅 Date Pickers",
        "intro": "Pick any date to snapshot the curve, plus a comparison date.",
        "position": "bottom",
    },
    {
        "selector": ".js-plotly-plot",
        "title": "📈 Curve Snapshot",
        "intro": (
            "The fitted curve with all maturities. The <b>Nelson-Siegel</b> "
            "model decomposes the curve into Level, Slope and Curvature."
        ),
        "position": "top",
    },
]

SPREADS_STEPS = [
    {
        "title": "📊 Spreads Page",
        "intro": (
            "Track <b>2s10s</b>, <b>5s30s</b>, and any custom spread "
            "with z-score bands and percentile rankings."
        ),
    },
    {
        "selector": ".js-plotly-plot",
        "title": "📉 Spread History",
        "intro": (
            "Spreads over time with mean ± 1σ bands. Z-scores tell you "
            "if a spread is rich or cheap relative to its history."
        ),
        "position": "top",
    },
]

REGRESSION_STEPS = [
    {
        "title": "📐 Regression Page",
        "intro": (
            "Run <b>rolling OLS</b> to find which bonds are rich or cheap "
            "relative to their fair value implied by the rest of the curve."
        ),
    },
    {
        "selector": ".js-plotly-plot",
        "title": "📈 Residuals Chart",
        "intro": (
            "The residual line shows mispricing. Above zero = rich (sell), "
            "below zero = cheap (buy)."
        ),
        "position": "top",
    },
]

PCA_STEPS = [
    {
        "title": "🧮 PCA Page",
        "intro": (
            "Decompose the yield curve into its <b>3 principal components</b>:<br><br>"
            "• <b>PC1 = Level</b> (parallel shifts)<br>"
            "• <b>PC2 = Slope</b> (steepening / flattening)<br>"
            "• <b>PC3 = Curvature</b> (butterflies)"
        ),
    },
    {
        "selector": ".js-plotly-plot",
        "title": "📊 PCA Charts",
        "intro": "Visualises the loading and history of each component.",
        "position": "top",
    },
]

ANALYSIS_STEPS = [
    {
        "title": "🔍 Trade Scanner — The Star",
        "intro": (
            "The most powerful page. Scans <b>100+ trades</b> "
            "(outrights, curves, butterflies) and ranks them by:<br><br>"
            "• Sharpe ratio<br>"
            "• Z-score<br>"
            "• Carry & rolldown<br>"
            "• Convexity"
        ),
    },
    {
        "selector": '[data-testid="stDataFrame"]',
        "title": "📋 Ranked Trade Table",
        "intro": (
            "Click any row to drill into a trade — see history, "
            "z-score, regression fit, and recommended sizing."
        ),
        "position": "top",
    },
]

VOL_SURFACE_STEPS = [
    {
        "title": "🌊 Vol Surface Page",
        "intro": (
            "<b>Swaption implied volatility</b> across strike and expiry.<br><br>"
            "3D surface, heatmap and SABR-fitted smile."
        ),
    },
    {
        "selector": ".js-plotly-plot",
        "title": "🌐 3D Vol Surface",
        "intro": "Drag to rotate. The smile shape tells you about skew and kurtosis pricing.",
        "position": "top",
    },
]

TRADE_TRACKER_STEPS = [
    {
        "title": "📒 Trade Tracker — Final Stop",
        "intro": (
            "Log your trade ideas with entry levels, then track live P&L "
            "as the market moves.<br><br>"
            "<b>You've completed the full tour!</b> Click <b>Finish ✓</b> to exit."
        ),
    },
    {
        "selector": '[data-testid="stForm"]',
        "title": "✍️ Log a Trade",
        "intro": "Fill in the trade details to add an idea to your tracker.",
        "position": "top",
    },
]

STEPS = {
    "home":          HOME_STEPS,
    "yield_curve":   YIELD_CURVE_STEPS,
    "spreads":       SPREADS_STEPS,
    "regression":    REGRESSION_STEPS,
    "pca":           PCA_STEPS,
    "analysis":      ANALYSIS_STEPS,
    "vol_surface":   VOL_SURFACE_STEPS,
    "trade_tracker": TRADE_TRACKER_STEPS,
}


# ── Public API ───────────────────────────────────────────────────────────

def render_tutorial_button(key_suffix: str = "", chain: bool = False, unlock: bool = False, label: str = "🚀 Start Tutorial"):
    """Render a 'Start Tutorial' button.

    Args:
        key_suffix: makes the Streamlit key unique per location.
        chain:      if True, runs the full multi-page tour.
        unlock:     if True, also temporarily unlocks the password gate
                    (used on the login screen so users can preview the app).
    """
    key = f"start_tut_btn_{key_suffix}" if key_suffix else "start_tut_btn"
    if st.button(label, key=key, use_container_width=True, type="primary"):
        st.session_state["tut_active"] = True
        if chain:
            st.session_state["tut_chain"] = True
            st.session_state.pop("tut_chain_target", None)
        if unlock:
            st.session_state["site_authenticated"] = True
        st.rerun()


def render_tutorial(page: str = "home"):
    """Inject intro.js into the parent frame and run the tour for `page`.

    Call AFTER all page content has rendered so the DOM elements exist.
    Handles both single-page and chained multi-page modes.
    """
    # Auto-activate when chained tour reaches the expected next page
    chain_active = st.session_state.get("tut_chain", False)
    chain_target = st.session_state.get("tut_chain_target")

    if chain_active:
        if chain_target is None:
            # First page of a fresh chain — keep whatever tut_active was set
            pass
        elif chain_target == page:
            st.session_state["tut_active"] = True
        else:
            # User exited the chain and navigated elsewhere — clear it
            st.session_state["tut_chain"] = False
            st.session_state.pop("tut_chain_target", None)
            chain_active = False

    if not st.session_state.get("tut_active"):
        return

    # Clear flag immediately so it doesn't re-fire on next rerun
    st.session_state["tut_active"] = False

    # Compute next page in the chain (if any)
    next_url = None
    finish_url = None  # used on the LAST page of the chain
    if chain_active:
        try:
            idx = PAGE_CHAIN.index(page)
            if idx + 1 < len(PAGE_CHAIN):
                next_page = PAGE_CHAIN[idx + 1]
                next_url = PAGE_URLS[next_page]
                st.session_state["tut_chain_target"] = next_page
            else:
                # Chain complete — return to Home when user clicks Finish
                finish_url = PAGE_URLS["home"]
                st.session_state["tut_chain"] = False
                st.session_state.pop("tut_chain_target", None)
        except ValueError:
            pass

    steps = STEPS.get(page, HOME_STEPS)
    steps_json = json.dumps(steps)
    next_url_js = json.dumps(next_url) if next_url else "null"
    finish_url_js = json.dumps(finish_url) if finish_url else "null"

    components.html(
        f"""
<script>
(function() {{
    const stepsData = {steps_json};
    const nextUrl = {next_url_js};
    const finishUrl = {finish_url_js};

    function runTour() {{
        try {{
            const parentDoc = window.parent.document;
            const parentWin = window.parent;

            if (!parentWin.introJs) {{
                console.warn('intro.js not loaded yet, retrying...');
                setTimeout(runTour, 300);
                return;
            }}

            // Resolve selectors to real elements
            const resolved = stepsData.map(s => {{
                const out = {{ title: s.title, intro: s.intro }};
                if (s.position) out.position = s.position;
                if (s.selector) {{
                    const el = parentDoc.querySelector(s.selector);
                    if (el) {{
                        out.element = el;
                    }} else {{
                        console.warn('Selector not found:', s.selector);
                    }}
                }}
                return out;
            }});

            const intro = parentWin.introJs();
            intro.setOptions({{
                steps: resolved,
                showProgress: true,
                showBullets: false,
                exitOnOverlayClick: false,
                showStepNumbers: true,
                doneLabel: nextUrl ? 'Next page →' : (finishUrl ? 'Finish & go Home 🏠' : 'Finish ✓'),
                nextLabel: 'Next →',
                prevLabel: '← Back',
                skipLabel: '✕',
                tooltipPosition: 'auto',
                scrollToElement: true,
                scrollPadding: 80,
                disableInteraction: false,
            }});

            // Chain navigation: when the user finishes the last step,
            // jump to the next page in the chain — or back to Home if
            // this is the final page of the chain.
            intro.oncomplete(function() {{
                const target = nextUrl || finishUrl;
                if (target) {{
                    setTimeout(() => {{
                        try {{ parentWin.location.href = target; }}
                        catch (e) {{ console.error('Navigation failed:', e); }}
                    }}, 250);
                }}
            }});

            intro.start();
        }} catch (err) {{
            console.error('Tutorial error:', err);
        }}
    }}

    function injectAndRun() {{
        const parentDoc = window.parent.document;
        const parentWin = window.parent;

        // Already loaded?
        if (parentWin.introJs) {{
            runTour();
            return;
        }}

        // Inject CSS
        if (!parentDoc.getElementById('introjs-css')) {{
            const css = parentDoc.createElement('link');
            css.id = 'introjs-css';
            css.rel = 'stylesheet';
            css.href = 'https://cdn.jsdelivr.net/npm/intro.js@7.2.0/minified/introjs.min.css';
            parentDoc.head.appendChild(css);
        }}

        // Inject custom dark-theme styles
        if (!parentDoc.getElementById('introjs-custom-css')) {{
            const customCss = parentDoc.createElement('style');
            customCss.id = 'introjs-custom-css';
            customCss.textContent = `
                .introjs-tooltip {{
                    background: #1a1a2e !important;
                    color: #e0e0e0 !important;
                    border: 1px solid #4fc3f7 !important;
                    border-radius: 12px !important;
                    max-width: 440px !important;
                    min-width: 320px !important;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.6) !important;
                }}
                .introjs-tooltip-title {{
                    color: #4fc3f7 !important;
                    font-size: 17px !important;
                    font-weight: 600 !important;
                }}
                .introjs-tooltiptext {{
                    font-size: 14px !important;
                    line-height: 1.6 !important;
                    color: #ddd !important;
                }}
                .introjs-tooltipbuttons {{
                    border-top: 1px solid #333 !important;
                }}
                .introjs-button {{
                    background: #283593 !important;
                    color: white !important;
                    border: none !important;
                    border-radius: 6px !important;
                    padding: 8px 18px !important;
                    font-size: 13px !important;
                    text-shadow: none !important;
                    font-weight: 500 !important;
                }}
                .introjs-button:hover {{
                    background: #3949ab !important;
                    color: white !important;
                }}
                .introjs-button:focus {{
                    box-shadow: 0 0 0 2px #4fc3f7 !important;
                }}
                .introjs-disabled {{
                    background: #444 !important;
                    color: #888 !important;
                }}
                .introjs-skipbutton {{
                    color: #888 !important;
                    background: transparent !important;
                    font-size: 18px !important;
                }}
                .introjs-skipbutton:hover {{
                    color: #fff !important;
                }}
                .introjs-helperLayer {{
                    border-radius: 8px !important;
                    box-shadow:
                        0 0 0 5000px rgba(0,0,0,0.7),
                        0 0 0 4px #4fc3f7,
                        0 0 30px rgba(79, 195, 247, 0.6) !important;
                    transition: all 0.3s ease !important;
                }}
                .introjs-helperNumberLayer {{
                    background: #4fc3f7 !important;
                    color: #1a1a2e !important;
                    font-weight: 700 !important;
                    border: 2px solid #1a1a2e !important;
                    text-shadow: none !important;
                }}
                .introjs-progress {{
                    background: #333 !important;
                    height: 4px !important;
                }}
                .introjs-progressbar {{
                    background: #4fc3f7 !important;
                }}
                .introjs-arrow.top {{ border-bottom-color: #1a1a2e !important; }}
                .introjs-arrow.bottom {{ border-top-color: #1a1a2e !important; }}
                .introjs-arrow.left {{ border-right-color: #1a1a2e !important; }}
                .introjs-arrow.right {{ border-left-color: #1a1a2e !important; }}
                .introjs-floating {{
                    border: 2px solid #4fc3f7 !important;
                }}
            `;
            parentDoc.head.appendChild(customCss);
        }}

        // Inject script
        const existing = parentDoc.getElementById('introjs-script');
        if (existing) {{
            existing.remove();
        }}
        const script = parentDoc.createElement('script');
        script.id = 'introjs-script';
        script.src = 'https://cdn.jsdelivr.net/npm/intro.js@7.2.0/intro.min.js';
        script.onload = function() {{
            setTimeout(runTour, 300);
        }};
        script.onerror = function() {{
            console.error('Failed to load intro.js');
        }};
        parentDoc.head.appendChild(script);
    }}

    // Wait briefly for parent DOM to settle, then inject
    setTimeout(injectAndRun, 200);
}})();
</script>
        """,
        height=1,
    )


# Backwards-compat alias
render_tutorial_overlay = render_tutorial
