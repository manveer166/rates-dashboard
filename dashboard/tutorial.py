"""
tutorial.py — Interactive guided tour overlay using intro.js.

Injects intro.js from CDN and highlights actual page elements with
circles, tooltips, and step-by-step navigation.
"""

import streamlit as st
import streamlit.components.v1 as components


def render_tutorial_button():
    """Render the 'Start Tutorial' button. Call on the home page."""
    if st.button("Start Tutorial", key="start_tut_btn", use_container_width=False):
        st.session_state["run_tutorial"] = True
        st.rerun()


def render_tutorial_overlay(page: str = "home"):
    """If tutorial was triggered, inject intro.js and run the guided tour.
    Call AFTER all page content has rendered."""
    if not st.session_state.get("run_tutorial"):
        return

    # Clear the flag so it doesn't re-run on every rerender
    st.session_state["run_tutorial"] = False

    steps = _get_steps(page)
    if not steps:
        return

    steps_js = ",\n".join(steps)

    components.html(f"""
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/intro.js@7.2.0/minified/introjs.min.css">
    <style>
        /* Custom intro.js styling for dark theme */
        .introjs-tooltip {{
            background: #1a1a2e !important;
            color: #e0e0e0 !important;
            border: 1px solid #333 !important;
            border-radius: 12px !important;
            max-width: 400px !important;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif !important;
        }}
        .introjs-tooltip-title {{
            color: #4fc3f7 !important;
            font-size: 16px !important;
        }}
        .introjs-tooltiptext {{
            font-size: 14px !important;
            line-height: 1.6 !important;
            color: #ccc !important;
        }}
        .introjs-button {{
            background: #283593 !important;
            color: white !important;
            border: none !important;
            border-radius: 6px !important;
            padding: 6px 16px !important;
            font-size: 13px !important;
            text-shadow: none !important;
        }}
        .introjs-button:hover {{
            background: #3949ab !important;
        }}
        .introjs-skipbutton {{
            color: #888 !important;
        }}
        .introjs-helperLayer {{
            border-radius: 8px !important;
            box-shadow: 0 0 0 5000px rgba(0,0,0,0.6),
                        0 0 0 3px #4fc3f7 !important;
        }}
        .introjs-helperNumberLayer {{
            background: #4fc3f7 !important;
            color: #1a1a2e !important;
            font-weight: 700 !important;
        }}
        /* Floating tooltip when no element is targeted */
        .introjs-floating {{
            border: 2px solid #4fc3f7 !important;
        }}
        .introjs-arrow {{
            border-bottom-color: #1a1a2e !important;
        }}
        .introjs-arrow.top {{
            border-bottom-color: #1a1a2e !important;
        }}
        .introjs-arrow.bottom {{
            border-top-color: #1a1a2e !important;
        }}
        .introjs-progress {{
            background: #333 !important;
        }}
        .introjs-progressbar {{
            background: #4fc3f7 !important;
        }}
        .introjs-bullets ul li a.active {{
            background: #4fc3f7 !important;
        }}
    </style>
    <script src="https://cdn.jsdelivr.net/npm/intro.js@7.2.0/intro.min.js"></script>
    <script>
    // Wait for Streamlit to finish rendering
    function waitForElements(callback, maxWait) {{
        let waited = 0;
        const interval = setInterval(() => {{
            waited += 200;
            // Check if main content has loaded
            const main = window.parent.document.querySelector('[data-testid="stAppViewContainer"]');
            if (main || waited > maxWait) {{
                clearInterval(interval);
                setTimeout(callback, 500);
            }}
        }}, 200);
    }}

    waitForElements(function() {{
        const doc = window.parent.document;
        const intro = window.parent.introJs ? window.parent.introJs() : null;
        if (!intro) {{
            // Load intro.js into parent frame
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = 'https://cdn.jsdelivr.net/npm/intro.js@7.2.0/minified/introjs.min.css';
            doc.head.appendChild(link);

            const style = document.createElement('style');
            style.textContent = `
                .introjs-tooltip {{ background: #1a1a2e !important; color: #e0e0e0 !important; border: 1px solid #333 !important; border-radius: 12px !important; max-width: 420px !important; font-family: -apple-system, BlinkMacSystemFont, sans-serif !important; }}
                .introjs-tooltip-title {{ color: #4fc3f7 !important; font-size: 16px !important; }}
                .introjs-tooltiptext {{ font-size: 14px !important; line-height: 1.6 !important; color: #ccc !important; }}
                .introjs-button {{ background: #283593 !important; color: white !important; border: none !important; border-radius: 6px !important; padding: 6px 16px !important; font-size: 13px !important; text-shadow: none !important; }}
                .introjs-button:hover {{ background: #3949ab !important; }}
                .introjs-skipbutton {{ color: #888 !important; }}
                .introjs-helperLayer {{ border-radius: 8px !important; box-shadow: 0 0 0 5000px rgba(0,0,0,0.6), 0 0 0 3px #4fc3f7 !important; }}
                .introjs-helperNumberLayer {{ background: #4fc3f7 !important; color: #1a1a2e !important; font-weight: 700 !important; }}
                .introjs-progress {{ background: #333 !important; }}
                .introjs-progressbar {{ background: #4fc3f7 !important; }}
                .introjs-arrow.top {{ border-bottom-color: #1a1a2e !important; }}
                .introjs-arrow.bottom {{ border-top-color: #1a1a2e !important; }}
            `;
            doc.head.appendChild(style);

            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/intro.js@7.2.0/intro.min.js';
            script.onload = function() {{ startTour(); }};
            doc.head.appendChild(script);
        }} else {{
            startTour();
        }}

        function startTour() {{
            const introObj = window.parent.introJs();
            const steps = [{steps_js}];

            // Resolve element selectors to actual elements
            const resolvedSteps = steps.map(s => {{
                const resolved = {{ ...s }};
                if (s.elementSelector) {{
                    const el = doc.querySelector(s.elementSelector);
                    if (el) resolved.element = el;
                    delete resolved.elementSelector;
                }}
                return resolved;
            }});

            introObj.setOptions({{
                steps: resolvedSteps,
                showProgress: true,
                showBullets: true,
                exitOnOverlayClick: true,
                showStepNumbers: true,
                doneLabel: 'Finish',
                nextLabel: 'Next &rarr;',
                prevLabel: '&larr; Back',
                skipLabel: '&times;',
                tooltipPosition: 'auto',
                scrollToElement: true,
                scrollPadding: 80,
            }});
            introObj.start();
        }}
    }}, 5000);
    </script>
    """, height=0)


def _get_steps(page: str):
    """Return intro.js step definitions for a given page."""

    if page == "home":
        return [
            """{
                title: 'Welcome to the Rates Dashboard',
                intro: 'This tutorial will walk you through the key features of the dashboard. Each step highlights a different element on the page.<br><br>Click <b>Next</b> to begin.'
            }""",
            """{
                elementSelector: '[data-testid="stSidebar"]',
                title: 'Sidebar Controls',
                intro: 'The sidebar is your control panel.<br><br><b>Quick Select:</b> Set lookback period (3M to 5Y)<br><b>Date Range:</b> Custom start/end dates<br><b>Refresh Data:</b> Force reload from all sources<br><b>Cache:</b> Shows how fresh your data is',
                position: 'right'
            }""",
            """{
                elementSelector: '[data-testid="stMetric"]:first-of-type',
                title: 'KPI Metrics',
                intro: 'These metric cards show <b>current yields</b> and their <b>change</b> vs the lookback period.<br><br>Green arrow = rates fell (good for receivers)<br>Red arrow = rates rose',
                position: 'bottom'
            }""",
            """{
                elementSelector: '.stPlotlyChart',
                title: 'Yield Curve Snapshot',
                intro: 'This chart compares <b>today\\'s yield curve</b> vs the curve N months ago.<br><br><b>Hover</b> for exact values. <b>Click+drag</b> to zoom. <b>Double-click</b> to reset.',
                position: 'top'
            }""",
            """{
                elementSelector: '[data-testid="stSelectSlider"]',
                title: 'Lookback Slider',
                intro: 'Drag this to change the comparison period. The KPI deltas and chart comparisons update instantly.<br><br>Try switching between 3 Months and 2 Years to see how the curve evolved.',
                position: 'bottom'
            }""",
            """{
                elementSelector: 'a[href*="Substack"], [data-testid="stLinkButton"]',
                title: 'Substack & Links',
                intro: 'Quick links to the <b>Macro Manv Substack</b>, subscription page, and contact email.',
                position: 'top'
            }""",
            """{
                title: 'Explore the Pages',
                intro: 'Use the <b>sidebar navigation</b> to explore:<br><br>' +
                    '<b>Yield Curve</b> — curve shapes & evolution<br>' +
                    '<b>Spreads</b> — 2s10s, 5s30s with z-scores<br>' +
                    '<b>Regression</b> — rich/cheap analysis<br>' +
                    '<b>PCA</b> — level, slope, curvature factors<br>' +
                    '<b>Analysis</b> — the Trade Scanner (most important!)<br>' +
                    '<b>Vol Surface</b> — swaption vol visualisation<br>' +
                    '<b>Trade Tracker</b> — log & track your ideas<br><br>' +
                    'The <b>Trade Scanner</b> on the Analysis page is where trade ideas come from. Start there!'
            }""",
        ]

    elif page == "welcome":
        # Pre-login tour — no page elements to highlight, so all floating tooltips
        return [
            """{
                title: 'Welcome to the Rates Dashboard',
                intro: 'This is an interactive tutorial that walks you through the full dashboard.<br><br>Enter the password to unlock the dashboard, then explore each page.<br><br>Click <b>Next</b> to preview what\'s inside.'
            }""",
            """{
                title: 'Home — Market Overview',
                intro: 'The <b>Home page</b> shows live KPI metrics for:<br><br>' +
                    '• <b>US Treasury yields</b> (1Y–30Y)<br>' +
                    '• <b>International yields</b> (DE, UK, CH, JP)<br>' +
                    '• <b>SOFR swaps & credit spreads</b> (IG, HY, BBB)<br>' +
                    '• <b>Yield curve snapshot</b> — today vs N months ago<br><br>' +
                    'Every metric shows the change vs your chosen lookback period.'
            }""",
            """{
                title: 'Yield Curve & Spreads',
                intro: '<b>Yield Curve page:</b> Animated curve evolution, butterfly analysis, and curve shape metrics.<br><br>' +
                    '<b>Spreads page:</b> 2s10s, 5s30s, and custom spreads with z-score bands and percentile rankings.'
            }""",
            """{
                title: 'Regression & PCA',
                intro: '<b>Regression:</b> Run rolling OLS on any two series — find rich/cheap vs fair value, with residual z-scores.<br><br>' +
                    '<b>PCA:</b> Decompose the curve into Level, Slope, and Curvature factors. See how much each explains.'
            }""",
            """{
                title: 'Trade Scanner (Analysis)',
                intro: 'The most powerful page — scans <b>100+ outright, curve, and fly trades</b> and ranks them by:<br><br>' +
                    '• <b>Sharpe ratio</b> — risk-adjusted expected return<br>' +
                    '• <b>Z-score</b> — how cheap/rich vs history<br>' +
                    '• <b>Carry + Rolldown</b> — income from holding<br>' +
                    '• <b>Net Convexity</b> — DV01-weighted convexity pickup<br><br>' +
                    'Click any trade for a deep-dive detail panel with charts.'
            }""",
            """{
                title: 'Vol Surface & Trade Tracker',
                intro: '<b>Vol Surface:</b> 3D swaption vol surface, heatmap, and SABR smile estimator.<br><br>' +
                    '<b>Trade Tracker:</b> Log trade ideas with live entry levels, track P&L in real-time, and see your win rate and cumulative performance.'
            }""",
            """{
                title: 'Alerts, Glossary & More',
                intro: '<b>Alerts:</b> Set up email notifications for top scanner movers.<br>' +
                    '<b>Glossary:</b> Definitions for every metric and column.<br>' +
                    '<b>Feature Request:</b> Submit ideas directly.<br><br>' +
                    'Enter the password <b>"rates"</b> to get started!'
            }""",
        ]

    elif page == "analysis":
        return [
            """{
                title: 'Trade Scanner',
                intro: 'The scanner evaluates <b>100+ trades</b> — every outright, curve, and fly — and ranks them by Sharpe ratio.'
            }""",
            """{
                elementSelector: '[data-testid="stSelectbox"]:first-of-type',
                title: 'Direction Control',
                intro: '<b>Receive:</b> profit when rates fall<br><b>Pay:</b> profit when rates rise<br><br>This flips the sign on carry, rolldown, and convexity.',
                position: 'bottom'
            }""",
            """{
                elementSelector: '[data-testid="stDataFrame"]',
                title: 'Scanner Table',
                intro: 'Each row is a trade idea.<br><br><b>Key columns:</b><br>' +
                    '• <b>Sharpe</b> — risk-adjusted return (sort by this!)<br>' +
                    '• <b>Z</b> — low = cheap for receivers<br>' +
                    '• <b>Carry/Roll</b> — income from holding<br>' +
                    '• <b>Conv</b> — net convexity pickup<br>' +
                    '• <b>E[Ret]</b> — expected annualised return<br><br>' +
                    '<b>Colours:</b> Green = attractive, Red = unattractive',
                position: 'top'
            }""",
            """{
                elementSelector: '[data-testid="stMultiSelect"]',
                title: 'Type Filter',
                intro: 'Filter by trade type:<br><b>Outright</b> — single tenor<br><b>Curve</b> — DV01-neutral spread<br><b>Fly</b> — DV01-neutral butterfly<br><b>*</b> variants — beta-weighted',
                position: 'bottom'
            }""",
            """{
                elementSelector: '[data-testid="stDownloadButton"]',
                title: 'Export',
                intro: '<b>Download CSV</b> for raw data or <b>Download Report</b> for a styled HTML report you can print to PDF.',
                position: 'bottom'
            }""",
            """{
                elementSelector: '.stPlotlyChart',
                title: 'Bubble Charts',
                intro: 'Two charts below the table:<br><br><b>Sharpe vs Z-score:</b> Best trades in the top-left (high Sharpe, cheap)<br><b>E[Ret] vs Risk:</b> Above zero line = positive expected return<br><br>Bubble colour = type, size = weekly change. Hover for details.',
                position: 'top'
            }""",
            """{
                title: 'Detail Panel',
                intro: 'Scroll down for the <b>Trade Detail</b> section. Select any trade type and tenor to see:<br><br>' +
                    '• Level time series<br>• Rolling z-score with bands<br>• Expected return line<br>• Rolling Sharpe evolution<br><br>' +
                    'This is where you do your deep dive before putting on a trade.'
            }""",
        ]

    elif page == "vol_surface":
        return [
            """{
                title: 'Swaption Vol Surface',
                intro: 'This page visualises the swaption volatility surface — how implied vol varies by expiry and tenor.'
            }""",
            """{
                elementSelector: '[data-testid="stSelectbox"]',
                title: 'View Controls',
                intro: '<b>3D Surface</b> — rotatable 3D view<br><b>Heatmap</b> — colour-coded 2D grid<br><b>Term Structure</b> — vol curves by tenor<br><br>Switch between Normal (bps) and Lognormal (%) vol.',
                position: 'bottom'
            }""",
            """{
                elementSelector: '.stPlotlyChart',
                title: 'Vol Surface Chart',
                intro: 'The surface shows vol across all expiry/tenor combinations.<br><br>In 3D mode, <b>click+drag</b> to rotate, <b>scroll</b> to zoom.',
                position: 'top'
            }""",
            """{
                title: 'SABR Smile',
                intro: 'Scroll down for the <b>SABR smile estimator</b>. Adjust the <b>Rho</b> slider to see how skew affects the vol smile.<br><br>Negative Rho = receiver skew (typical in rates).'
            }""",
        ]

    return []
