"""Shared page header — Home button on the left + section links across the top.

Call ``render_page_header(current="Yield Curve")`` at the very top of every
page (after ``set_page_config`` and ``password_gate``) to render a uniform
navigation strip. The current page is highlighted.
"""

import streamlit as st


# Section links shown on every page header. (Label, URL, emoji)
# Grouped navigation. Top-level shows 7 pills + Home; each pill opens a
# dropdown panel listing the pages in that category. Single source of
# truth — to add a page, drop it into the right category and you're done.
CATEGORIES: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    ("Markets", "📈", [
        ("Yield Curve",     "/Yield_Curve",         "📉"),
        ("Global Curves",   "/Global_Curves",       "🌍"),
        ("Spreads",         "/Spreads",             "📊"),
        ("FX Overlay",      "/FX_Overlay",          "💱"),
        ("Real Rates",      "/Real_Rates",          "📉"),
        ("Cross-Asset",     "/Cross_Asset",         "🌐"),
        ("Vol Scorecard",   "/Vol_Scorecard",       "🌊"),
        ("Global Inflation","/Global_Inflation",    "🔥"),
        ("Global Macro",    "/Global_Macro",        "🌐"),
    ]),
    ("Analytics", "🔬", [
        ("Analysis",            "/Analysis",            "🔍"),
        ("Regression",          "/Regression",          "📐"),
        ("PCA",                 "/PCA",                 "🧮"),
        ("Correlation",         "/Correlation",         "🔗"),
        ("Vol Surface",         "/Vol_Surface",         "🌊"),
        ("Regime",              "/Regime",              "🧭"),
        ("Trade Decomposition", "/Trade_Decomposition", "🧩"),
    ]),
    ("Trade", "🎯", [
        ("Trade Builder",     "/Trade_Builder",       "🧰"),
        ("Backtester",        "/Backtester",          "🧪"),
        ("Trade Tracker",     "/Trade_Tracker",       "📒"),
        ("Trade of the Week", "/Trade_of_the_Week",   "🎯"),
        ("Performance",       "/Performance",         "🏆"),
        ("Journal",           "/Trade_Journal",       "📓"),
    ]),
    ("Events", "📅", [
        ("Auctions",        "/Auction_Tracker",     "🏛️"),
        ("Rates Calendar",  "/Rates_Calendar",      "📅"),
        ("CTA Positioning", "/CTA_Positioning",     "📊"),
    ]),
    ("Publish", "📨", [
        ("Alerts",         "/Alerts",            "🔔"),
        ("AI Drafter",     "/AI_Post_Drafter",   "✍️"),
        ("Social Cards",   "/Social_Cards",      "🖼️"),
    ]),
    ("Admin", "⚙️", [
        ("A/B Tests",          "/AB_Tests",          "🧪"),
        ("CTA Audit",          "/CTA_Audit",         "🔗"),
        ("Subscriber Growth",  "/Subscriber_Growth", "📈"),
        ("Reader Polls",       "/Reader_Polls",      "🗳️"),
        ("Admin",              "/Admin",             "🛠️"),
        ("Feature Request",    "/Feature_Request",   "💡"),
    ]),
    ("Help", "📚", [
        ("Data Sources", "/Data_Sources", "📡"),
        ("Glossary",     "/Glossary",     "📖"),
        ("User Guide",   "/User_Guide",   "📘"),
    ]),
]

# Backwards-compatible flat list (for code that does `current in SECTIONS`)
SECTIONS = [("Home", "/", "🏠")] + [
    (label, url, emoji)
    for _cat_label, _cat_emoji, pages in CATEGORIES
    for label, url, emoji in pages
]


def _inject_global_css() -> None:
    """Inject the design-system CSS tokens + Inter font on every page.

    This mirrors the block in dashboard/Home.py so that every page picks
    up the same blue palette, typography, and component styling — not
    just the Home page. Streamlit reruns each page in its own process,
    so each page must inject the styles itself.
    """
    if st.session_state.get("_global_css_injected"):
        return
    st.session_state["_global_css_injected"] = True
    st.markdown(
        """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
    :root {
        --c-bg-0:   #0a1628;
        --c-bg-1:   #122340;
        --c-bg-2:   #1a3056;
        --c-bg-3:   #233e6e;
        --c-accent: #4fc3f7;
        --c-accent-soft: rgba(79, 195, 247, 0.14);
        --c-text-1: #e8eef9;
        --c-text-2: #94a8c9;
        --c-text-3: #6a7e9e;
        --c-success: #4ade80;
        --c-danger:  #f87171;
        --c-warning: #fbbf24;
        --shadow-1: 0 1px 2px rgba(0,0,0,0.10);
        --shadow-2: 0 4px 14px rgba(0,0,0,0.18);
        --shadow-3: 0 12px 32px rgba(0,0,0,0.28);
        --r-sm: 4px;
        --r-md: 6px;
        --r-lg: 10px;
    }
    html, body, [class*="css"], .stApp, .stMarkdown, .stTextInput, .stSelectbox,
    .stButton, button, input, textarea, select {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        font-feature-settings: 'cv11', 'ss01';
        -webkit-font-smoothing: antialiased;
    }
    h1 {
        color: var(--c-text-1) !important;
        font-weight: 700 !important;
        font-size: 32px !important;
        letter-spacing: -0.02em !important;
        line-height: 1.15 !important;
        margin-bottom: 4px !important;
    }
    h2 {
        color: var(--c-text-1) !important;
        font-weight: 600 !important;
        font-size: 22px !important;
        letter-spacing: -0.015em !important;
        line-height: 1.2 !important;
    }
    h3, .stSubheader {
        color: var(--c-text-1) !important;
        font-weight: 600 !important;
        font-size: 17px !important;
        letter-spacing: -0.01em !important;
        line-height: 1.3 !important;
    }
    p, .stMarkdown { color: var(--c-text-1); line-height: 1.55; }
    .stCaption, [data-testid="stCaptionContainer"] { color: var(--c-text-3) !important; font-size: 12px !important; }

    .stApp { background: var(--c-bg-0); }
    [data-testid="stHeader"] { background: rgba(10, 22, 40, 0.80); backdrop-filter: blur(8px); }
    [data-testid="stAppViewContainer"] > .main { background: var(--c-bg-0); }
    [data-testid="block-container"] { padding-top: 24px !important; padding-bottom: 32px !important; }

    [data-testid="stSidebar"] {
        background: var(--c-bg-1);
        border-right: none;
        box-shadow: var(--shadow-2);
    }
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] p { color: var(--c-text-2) !important; }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 { color: var(--c-text-1) !important; font-size: 15px !important; }

    [data-testid="stMetric"] {
        background: var(--c-bg-1);
        border: none;
        border-radius: var(--r-lg);
        padding: 16px 18px;
        box-shadow: var(--shadow-1);
        transition: background 0.18s ease, box-shadow 0.18s ease;
    }
    [data-testid="stMetric"]:hover {
        background: var(--c-bg-2);
        box-shadow: var(--shadow-2);
    }
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: var(--c-text-1) !important;
        font-weight: 600 !important;
        font-size: 26px !important;
        letter-spacing: -0.015em !important;
    }
    [data-testid="stMetric"] [data-testid="stMetricLabel"] {
        color: var(--c-text-2) !important;
        font-size: 11px !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    .section-header {
        font-size: 11px; font-weight: 700; color: var(--c-accent);
        text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 12px;
    }

    .stTabs [data-baseweb="tab-list"] {
        background: var(--c-bg-1);
        border-radius: var(--r-md);
        padding: 4px;
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        color: var(--c-text-2);
        border-radius: var(--r-sm);
        padding: 8px 16px;
        transition: all 0.15s ease;
    }
    .stTabs [data-baseweb="tab"]:hover { color: var(--c-text-1); background: var(--c-bg-2); }
    .stTabs [aria-selected="true"] {
        background: var(--c-bg-3) !important;
        color: var(--c-text-1) !important;
    }

    .stDataFrame, [data-testid="stDataFrame"] {
        background: var(--c-bg-1);
        border-radius: var(--r-md);
        border: none;
    }

    div[data-baseweb="select"] > div,
    .stTextInput > div > div > input,
    .stNumberInput > div > div > input,
    .stTextArea textarea,
    .stDateInput > div > div > input {
        background: var(--c-bg-1) !important;
        border: 1px solid transparent !important;
        border-radius: var(--r-md) !important;
        color: var(--c-text-1) !important;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    div[data-baseweb="select"] > div:hover,
    .stTextInput > div > div > input:hover { background: var(--c-bg-2) !important; }
    .stTextInput > div > div > input:focus,
    .stNumberInput > div > div > input:focus,
    .stTextArea textarea:focus,
    .stDateInput > div > div > input:focus {
        border-color: var(--c-accent) !important;
        box-shadow: 0 0 0 3px var(--c-accent-soft) !important;
        outline: none;
    }

    .stButton > button,
    .stDownloadButton > button,
    .stFormSubmitButton > button {
        background: transparent;
        color: var(--c-text-1);
        border: 1px solid var(--c-bg-3);
        border-radius: var(--r-md);
        padding: 9px 18px;
        font-weight: 500;
        transition: all 0.15s ease;
    }
    .stButton > button:hover,
    .stDownloadButton > button:hover,
    .stFormSubmitButton > button:hover {
        background: var(--c-bg-2);
        border-color: var(--c-accent);
        color: #ffffff;
    }
    .stButton > button:active,
    .stDownloadButton > button:active,
    .stFormSubmitButton > button:active {
        background: var(--c-bg-3);
        transform: translateY(1px);
    }
    .stButton > button:disabled,
    .stDownloadButton > button:disabled,
    .stFormSubmitButton > button:disabled {
        background: transparent !important;
        border-color: var(--c-bg-1) !important;
        color: var(--c-text-3) !important;
        cursor: not-allowed;
    }
    .stButton > button[kind="primary"],
    .stFormSubmitButton > button[kind="primary"] {
        background: var(--c-accent);
        color: var(--c-bg-0);
        border: 1px solid var(--c-accent);
        font-weight: 600;
        box-shadow: var(--shadow-1);
    }
    .stButton > button[kind="primary"]:hover,
    .stFormSubmitButton > button[kind="primary"]:hover {
        background: #81d4fa;
        border-color: #81d4fa;
        color: var(--c-bg-0);
        box-shadow: var(--shadow-2);
    }
    .stButton > button[kind="primary"]:active,
    .stFormSubmitButton > button[kind="primary"]:active { transform: translateY(1px); }

    hr, [data-testid="stDivider"] { border-color: var(--c-bg-1) !important; opacity: 0.6; }
    [data-testid="stAlert"] { border-radius: var(--r-md); border: none; }
    .js-plotly-plot, .plot-container { background: transparent !important; }

    @keyframes mm-fade-in {
        from { opacity: 0; transform: translateY(4px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    [data-testid="stMetric"], [data-testid="stDataFrame"] { animation: mm-fade-in 0.35s ease-out; }
</style>
        """,
        unsafe_allow_html=True,
    )


def _inject_header_css() -> None:
    """Inject the CSS for the header bar once per session."""
    if st.session_state.get("_header_css_injected"):
        return
    st.session_state["_header_css_injected"] = True
    st.markdown(
        """
        <style>
        .mm-header {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            padding: 12px 16px;
            margin: 0 0 24px 0;
            background: var(--c-bg-1, #122340);
            border-radius: 10px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.10), 0 4px 14px rgba(0,0,0,0.18);
            font-family: 'Inter', -apple-system, sans-serif;
            animation: mm-header-in 0.4s ease-out;
        }
        @keyframes mm-header-in {
            from { opacity: 0; transform: translateY(-4px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        .mm-header a.mm-home {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: var(--c-accent, #4fc3f7);
            color: var(--c-bg-0, #0a1628) !important;
            font-weight: 600;
            text-decoration: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            line-height: 1;
            transition: all 0.15s ease;
            box-shadow: 0 1px 2px rgba(0,0,0,0.10);
        }
        .mm-header a.mm-home:hover {
            background: #81d4fa;
            box-shadow: 0 4px 14px rgba(0,0,0,0.18);
            transform: translateY(-1px);
        }
        .mm-header a.mm-home:active {
            transform: translateY(0);
        }
        .mm-header .mm-divider {
            width: 1px;
            height: 24px;
            background: var(--c-bg-3, #233e6e);
            margin: 0 6px;
            opacity: 0.6;
        }
        .mm-header a.mm-link {
            color: var(--c-text-2, #94a8c9) !important;
            text-decoration: none;
            font-size: 13px;
            font-weight: 500;
            padding: 7px 12px;
            border-radius: 5px;
            line-height: 1;
            transition: all 0.15s ease;
        }
        .mm-header a.mm-link:hover {
            color: var(--c-text-1, #e8eef9) !important;
            background: var(--c-bg-2, #1a3056);
        }
        .mm-header a.mm-link:active {
            transform: translateY(1px);
        }
        .mm-header a.mm-link.mm-current {
            color: #ffffff !important;
            background: var(--c-bg-3, #233e6e);
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _inject_mobile_css() -> None:
    """Responsive tweaks for narrow viewports (phones, narrow embeds).

    Streamlit's defaults are loosely responsive but tend to render the
    multi-column layouts and chart cards too cramped on phones.  This pass:
      • collapses the navigation strip into a wrap-able row
      • shrinks page paddings + heading sizes <768px
      • forces st.columns to stack <600px (Streamlit's [data-testid='stColumn']
        sets each column to flex:1 — we override to flex:1 1 100%)
      • reduces metric/dataframe paddings on phones
    """
    st.markdown(
        """
        <style>
        /* === Tablet & smaller (<= 1024px) ===================================== */
        @media (max-width: 1024px) {
            section.main .block-container { padding: 1rem 1rem 4rem !important; }
            .mm-header { gap: 6px !important; padding: 6px 8px !important; }
            .mm-link { padding: 4px 8px !important; font-size: 11.5px !important; }
        }

        /* === Mobile (<= 768px) =============================================== */
        @media (max-width: 768px) {
            section.main .block-container { padding: 0.75rem 0.75rem 4rem !important; }
            h1 { font-size: 1.5rem !important; }
            h2 { font-size: 1.2rem !important; }
            h3 { font-size: 1.05rem !important; }
            .mm-header {
                flex-wrap: wrap !important;
                row-gap: 4px !important;
                padding: 6px !important;
            }
            .mm-home, .mm-link { font-size: 11px !important; padding: 4px 7px !important; }
            .mm-divider { display: none !important; }

            /* Stack columns instead of squeezing them */
            div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
                flex: 1 1 100% !important;
                min-width: 100% !important;
            }

            /* Tighter metric padding */
            div[data-testid="stMetric"] { padding: 4px 6px !important; }
            div[data-testid="stMetricValue"] { font-size: 1.3rem !important; }

            /* Sidebar: keep collapsed by default on mobile */
            section[data-testid="stSidebar"] { width: 220px !important; }

            /* Plotly: shrink margins so charts use the narrow width */
            .js-plotly-plot .plotly { font-size: 10px !important; }
        }

        /* === Narrow phones (<= 480px) ======================================== */
        @media (max-width: 480px) {
            section.main .block-container { padding: 0.5rem 0.5rem 3rem !important; }
            h1 { font-size: 1.25rem !important; }
            .mm-link, .mm-home { font-size: 10.5px !important; }
            /* Hide emoji-only labels to save horizontal space */
            div[data-testid="stDataFrame"] { font-size: 11px !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _inject_grouped_nav_css() -> None:
    """CSS for the category-grouped dropdown nav."""
    st.markdown(
        """
        <style>
        /* Hide Streamlit's auto-generated sidebar page nav — we use our own. */
        section[data-testid="stSidebar"] div[data-testid="stSidebarNav"],
        section[data-testid="stSidebar"] ul[data-testid="stSidebarNavItems"] {
            display: none !important;
        }

        .mm-nav {
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            padding: 8px 12px;
            margin: 0 0 14px;
            background: #0e1f3a;
            border-radius: 8px;
            position: relative;
            z-index: 1000;
        }
        .mm-nav .mm-home {
            color: #ffffff !important;
            background: #4fc3f7;
            font-weight: 700;
            font-size: 12.5px;
            padding: 7px 14px;
            border-radius: 5px;
            text-decoration: none;
            transition: background 0.15s ease;
        }
        .mm-nav .mm-home:hover { background: #22d3ee; }

        /* Category pill (the <summary>) */
        .mm-cat { position: relative; }
        .mm-cat > summary {
            list-style: none;
            cursor: pointer;
            color: #cbd5e1 !important;
            font-size: 12.5px;
            font-weight: 500;
            padding: 7px 12px;
            border-radius: 5px;
            line-height: 1;
            transition: all 0.15s ease;
            user-select: none;
        }
        .mm-cat > summary::-webkit-details-marker { display: none; }
        .mm-cat > summary::marker { content: ""; }
        .mm-cat > summary:hover {
            color: #e8eef9 !important;
            background: #1a3056;
        }
        .mm-cat[open] > summary {
            color: #ffffff !important;
            background: #233e6e;
        }
        .mm-cat.mm-cat-active > summary {
            color: #ffffff !important;
            background: #1a3056;
            border-bottom: 2px solid #4fc3f7;
            border-bottom-left-radius: 0;
            border-bottom-right-radius: 0;
        }

        /* The dropdown panel */
        .mm-cat .mm-panel {
            position: absolute;
            top: calc(100% + 4px);
            left: 0;
            min-width: 220px;
            background: #122340;
            border: 1px solid #233e6e;
            border-radius: 8px;
            padding: 6px;
            box-shadow: 0 10px 24px rgba(0,0,0,0.4);
            z-index: 1001;
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .mm-cat .mm-panel a {
            display: flex;
            align-items: center;
            gap: 8px;
            color: #cbd5e1 !important;
            font-size: 12.5px;
            padding: 7px 10px;
            border-radius: 4px;
            text-decoration: none;
            transition: all 0.12s ease;
            white-space: nowrap;
        }
        .mm-cat .mm-panel a:hover {
            background: #1a3056;
            color: #ffffff !important;
        }
        .mm-cat .mm-panel a.mm-current {
            background: #233e6e;
            color: #ffffff !important;
            font-weight: 600;
        }

        /* Hover-to-open in addition to click — feels more responsive */
        @media (hover: hover) {
            .mm-cat:hover > .mm-panel { display: flex; }
            .mm-cat:not([open]):not(:hover) > .mm-panel { display: none; }
        }

        /* Tablet & smaller */
        @media (max-width: 1024px) {
            .mm-nav { gap: 3px; padding: 6px 8px; }
            .mm-cat > summary, .mm-nav .mm-home { font-size: 11.5px; padding: 5px 9px; }
        }
        @media (max-width: 600px) {
            .mm-nav { flex-wrap: wrap; row-gap: 4px; }
            .mm-cat .mm-panel { left: 0; right: auto; min-width: 200px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _category_for(label: str) -> str | None:
    """Which category does `label` belong to? None if not found."""
    for cat_name, _emoji, pages in CATEGORIES:
        if any(p[0] == label for p in pages):
            return cat_name
    return None


def render_page_header(current: str = "Home") -> None:
    """Render the grouped category navigation header.

    Args:
        current: name of the current page (must match a label in any category).
    """
    _inject_global_css()
    _inject_header_css()
    _inject_mobile_css()
    _inject_grouped_nav_css()

    from dashboard.state import auth_query_string
    qs = auth_query_string()
    active_cat = _category_for(current)

    parts = ['<nav class="mm-nav">']
    parts.append(f'<a class="mm-home" href="/{qs}" target="_self">🏠 Home</a>')

    for cat_name, cat_emoji, pages in CATEGORIES:
        cat_cls = "mm-cat mm-cat-active" if cat_name == active_cat else "mm-cat"
        parts.append(f'<details class="{cat_cls}">')
        parts.append(f'  <summary>{cat_emoji} {cat_name} ▾</summary>')
        parts.append('  <div class="mm-panel">')
        for label, url, emoji in pages:
            link_cls = "mm-current" if label == current else ""
            parts.append(
                f'    <a class="{link_cls}" href="{url}{qs}" target="_self">'
                f'{emoji} {label}</a>'
            )
        parts.append('  </div>')
        parts.append('</details>')

    parts.append("</nav>")
    st.markdown("\n".join(parts), unsafe_allow_html=True)
