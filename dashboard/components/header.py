"""Shared page header — Home button on the left + section links across the top.

Call ``render_page_header(current="Yield Curve")`` at the very top of every
page (after ``set_page_config`` and ``password_gate``) to render a uniform
navigation strip. The current page is highlighted.
"""

import streamlit as st


# Section links shown on every page header. (Label, URL, emoji)
# URLs match Streamlit's auto-generated routes from the filenames in
# dashboard/pages — Streamlit strips the numeric prefix and replaces
# underscores with spaces but keeps the underscore in the URL.
SECTIONS = [
    ("Home",          "/",               "🏠"),
    ("Yield Curve",   "/Yield_Curve",    "📉"),
    ("Spreads",       "/Spreads",        "📊"),
    ("Regression",    "/Regression",     "📐"),
    ("PCA",           "/PCA",            "🧮"),
    ("Correlation",   "/Correlation",    "🔗"),
    ("Analysis",      "/Analysis",       "🔍"),
    ("Vol Surface",   "/Vol_Surface",    "🌊"),
    ("Trade Tracker", "/Trade_Tracker",  "📒"),
    ("CTA Positioning", "/CTA_Positioning", "📊"),
    ("Alerts",        "/Alerts",         "🔔"),
    ("Sources",       "/Data_Sources",   "📡"),
    ("Glossary",      "/Glossary",       "📖"),
    ("Guide",         "/User_Guide",     "📘"),
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


def render_page_header(current: str = "Home") -> None:
    """Render the navigation header.

    Args:
        current: name of the current page (must match a label in SECTIONS).
    """
    _inject_global_css()
    _inject_header_css()

    # Append ?auth=<token> to every link so that if the browser does a full
    # page reload (instead of an in-app Streamlit navigation), the new page
    # can restore auth from the query params instead of bouncing the user
    # back to the login screen.
    from dashboard.state import auth_query_string
    qs = auth_query_string()

    parts = ['<div class="mm-header">']
    parts.append(f'<a class="mm-home" href="/{qs}" target="_self">🏠 Home</a>')
    parts.append('<div class="mm-divider"></div>')

    for label, url, emoji in SECTIONS:
        if label == "Home":
            continue  # already rendered as the prominent button
        cls = "mm-link mm-current" if label == current else "mm-link"
        parts.append(
            f'<a class="{cls}" href="{url}{qs}" target="_self">{emoji} {label}</a>'
        )

    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)
