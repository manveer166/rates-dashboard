"""
tutorial.py — Interactive guided tour using intro.js.

Injects intro.js into the parent Streamlit frame so it can highlight
real DOM elements (sidebar, KPI cards, charts) with circles + tooltips.
"""

import json

import streamlit as st
import streamlit.components.v1 as components


# ── Step definitions (Python dicts → serialised to JSON for JS) ─────────

WELCOME_STEPS = [
    {
        "title": "📈 Welcome to the Rates Dashboard",
        "intro": (
            "This tour walks you through every feature of the dashboard.<br><br>"
            "Click <b>Next</b> to begin."
        ),
    },
    {
        "selector": '[data-testid="stTextInput"]',
        "title": "🔐 Login",
        "intro": (
            "Enter the password <b>rates</b> here to unlock the dashboard."
        ),
        "position": "bottom",
    },
    {
        "title": "🏠 Home — Market Overview",
        "intro": (
            "Inside, the <b>Home page</b> shows live KPIs for:<br><br>"
            "• US Treasury yields (1Y – 30Y)<br>"
            "• International yields (DE, UK, CH, JP)<br>"
            "• SOFR swaps & credit spreads<br>"
            "• Yield curve snapshot"
        ),
    },
    {
        "title": "📊 Yield Curve & Spreads",
        "intro": (
            "<b>Yield Curve page:</b> Curve evolution, butterflies, shape metrics.<br><br>"
            "<b>Spreads page:</b> 2s10s, 5s30s, custom spreads with z-score bands."
        ),
    },
    {
        "title": "📐 Regression & PCA",
        "intro": (
            "<b>Regression:</b> Rolling OLS — find rich/cheap vs fair value.<br><br>"
            "<b>PCA:</b> Decompose the curve into Level, Slope, Curvature."
        ),
    },
    {
        "title": "🔍 Trade Scanner",
        "intro": (
            "The most powerful page — scans <b>100+ trades</b> "
            "(outrights, curves, flies) and ranks by Sharpe, z-score, "
            "carry/rolldown, and convexity.<br><br>"
            "Click any trade for a deep-dive."
        ),
    },
    {
        "title": "🌊 Vol Surface & Trade Tracker",
        "intro": (
            "<b>Vol Surface:</b> 3D swaption vol, heatmap, SABR smile.<br><br>"
            "<b>Trade Tracker:</b> Log ideas with live levels, track P&L."
        ),
    },
    {
        "title": "🚀 Get Started",
        "intro": (
            "Enter the password <b>rates</b> and explore!<br><br>"
            "Each page has its own <b>Start Tutorial</b> button for a deep dive."
        ),
    },
]

HOME_STEPS = [
    {
        "title": "📈 Welcome",
        "intro": "This tour highlights the key parts of the Home page. Click <b>Next</b>.",
    },
    {
        "selector": '[data-testid="stSidebar"]',
        "title": "🎛️ Sidebar Controls",
        "intro": (
            "The sidebar is your control centre.<br><br>"
            "<b>Quick Select:</b> Lookback period (3M – 5Y)<br>"
            "<b>Date Range:</b> Custom dates<br>"
            "<b>Refresh:</b> Force reload from sources<br>"
            "<b>Cache:</b> Data freshness"
        ),
        "position": "right",
    },
    {
        "selector": '[data-testid="stSelectSlider"]',
        "title": "📅 Lookback Slider",
        "intro": (
            "Drag this to change the comparison period. KPI deltas and "
            "charts update instantly. Try switching between 3M and 2Y."
        ),
        "position": "bottom",
    },
    {
        "selector": '[data-testid="stMetric"]',
        "title": "📋 KPI Metrics",
        "intro": (
            "These cards show <b>current yields</b> and their <b>change</b> "
            "vs the lookback period.<br><br>"
            "🟢 Green = rates fell (good for receivers)<br>"
            "🔴 Red = rates rose"
        ),
        "position": "bottom",
    },
    {
        "selector": ".js-plotly-plot",
        "title": "📉 Yield Curve Chart",
        "intro": (
            "Compares <b>today's curve</b> vs the curve N months ago.<br><br>"
            "<b>Hover</b> for exact values · <b>Click+drag</b> to zoom · "
            "<b>Double-click</b> to reset"
        ),
        "position": "top",
    },
    {
        "selector": '[data-testid="stSidebarNav"]',
        "title": "🗂️ Page Navigation",
        "intro": (
            "Use the sidebar nav to explore:<br><br>"
            "• <b>Yield Curve</b> — shapes & evolution<br>"
            "• <b>Spreads</b> — 2s10s, 5s30s + z-scores<br>"
            "• <b>Regression</b> — rich/cheap analysis<br>"
            "• <b>PCA</b> — level, slope, curvature<br>"
            "• <b>Analysis</b> — Trade Scanner ⭐<br>"
            "• <b>Vol Surface</b> — swaption vol<br>"
            "• <b>Trade Tracker</b> — log & track ideas"
        ),
        "position": "right",
    },
    {
        "title": "🔍 Start with the Trade Scanner",
        "intro": (
            "The <b>Analysis</b> page (Trade Scanner) is where actionable "
            "ideas come from. It scans every outright, curve, and fly and "
            "ranks them by Sharpe ratio.<br><br>"
            "Open it from the sidebar to see for yourself!"
        ),
    },
]

STEPS = {
    "welcome": WELCOME_STEPS,
    "home": HOME_STEPS,
}


# ── Public API ───────────────────────────────────────────────────────────

def render_tutorial_button(key_suffix: str = ""):
    """Render the 'Start Tutorial' button. Sets session state to launch the tour."""
    key = f"start_tut_btn_{key_suffix}" if key_suffix else "start_tut_btn"
    if st.button("🚀 Start Tutorial", key=key, use_container_width=True, type="primary"):
        st.session_state["tut_active"] = True
        st.rerun()


def render_tutorial(page: str = "welcome"):
    """Inject intro.js into the parent frame and run the tour. Call AFTER all
    page content has rendered so the DOM elements exist."""
    if not st.session_state.get("tut_active"):
        return

    # Clear flag immediately so it doesn't re-fire on next rerun
    st.session_state["tut_active"] = False

    steps = STEPS.get(page, WELCOME_STEPS)
    steps_json = json.dumps(steps)

    components.html(
        f"""
<script>
(function() {{
    const stepsData = {steps_json};

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
                exitOnOverlayClick: true,
                showStepNumbers: true,
                doneLabel: 'Finish ✓',
                nextLabel: 'Next →',
                prevLabel: '← Back',
                skipLabel: '✕',
                tooltipPosition: 'auto',
                scrollToElement: true,
                scrollPadding: 80,
                disableInteraction: false,
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
