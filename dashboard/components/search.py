"""Sidebar search box — fuzzy-match across pages by name, topic, and keywords.

Streamlit doesn't index pages for search, so we maintain a curated index
keyed by URL path with a list of search terms.  Match is case-insensitive
substring matching across label + keywords.

Add a new entry to PAGE_INDEX whenever you add a new page.
"""

from __future__ import annotations

import streamlit as st


# (label, url_path, emoji, keywords) — keywords help match queries like
# "tips" → Real Rates, "carry" → Analysis, "hy oas" → Cross-Asset
PAGE_INDEX: list[tuple[str, str, str, list[str]]] = [
    ("Home",            "/",                  "🏠", ["dashboard", "overview", "summary"]),
    ("Yield Curve",     "/Yield_Curve",       "📉", ["nelson", "siegel", "ns", "snapshot", "curve", "tenors"]),
    ("Spreads",         "/Spreads",           "📊", ["2s10s", "5s30s", "swap spread", "credit spread", "oas"]),
    ("Regression",      "/Regression",        "📐", ["beta", "fit", "macro", "ols", "residual"]),
    ("PCA",             "/PCA",               "🧮", ["principal component", "level", "slope", "curvature", "pc1", "pc2", "pc3"]),
    ("Correlation",     "/Correlation",       "🔗", ["corr", "matrix", "rolling", "heatmap"]),
    ("Analysis",        "/Analysis",          "🔍", ["scanner", "trade", "carry", "rolldown", "fly", "z-score", "sharpe"]),
    ("Vol Surface",     "/Vol_Surface",       "🌊", ["volatility", "swaption", "implied vol", "atm", "vol cube"]),
    ("Trade Tracker",   "/Trade_Tracker",     "📒", ["pnl", "position", "log", "blotter"]),
    ("CTA Positioning", "/CTA_Positioning",   "📊", ["cta", "futures", "speculator", "managed money", "cot"]),
    ("Alerts",          "/Alerts",            "🔔", ["email", "weekly", "monday", "friday", "subscribers", "pdf", "send"]),
    ("Data Sources",    "/Data_Sources",      "📡", ["sources", "fred", "treasury", "ecb", "boe", "hkma", "where"]),
    ("Glossary",        "/Glossary",          "📖", ["definitions", "terms", "lookup", "what is"]),
    ("User Guide",      "/User_Guide",        "📘", ["help", "how to", "tutorial", "guide"]),
    ("Admin",           "/Admin",             "🛠️", ["admin", "settings", "config", "users"]),
    ("Substack Models", "/Substack_Models",   "📨", ["substack", "model", "subscribers"]),
    ("Real Rates",      "/Real_Rates",        "📉", ["tips", "real yield", "breakeven", "5y5y", "inflation", "real rate"]),
    ("Cross-Asset",     "/Cross_Asset",       "🌐", ["credit", "vix", "ig oas", "hy oas", "regime", "cross asset", "cross-asset"]),
    ("Trade of the Week", "/Trade_of_the_Week", "🎯", ["pick", "weekly trade", "trade of week", "totw", "thesis"]),
    ("Global Curves",   "/Global_Curves",     "🌍", ["eu", "uk", "ecb", "boe", "bund", "gilt", "global", "cross market", "us-eu", "us-uk"]),
    ("AI Post Drafter", "/AI_Post_Drafter",   "✍️", ["ai", "claude", "anthropic", "draft", "post", "substack", "writer", "llm"]),
    ("Subscriber Growth", "/Subscriber_Growth", "📈", ["subs", "subscribers", "growth", "audience", "list size"]),
    ("Reader Polls",    "/Reader_Polls",      "🗳️", ["poll", "vote", "survey", "reader poll"]),
    ("Backtester",      "/Backtester",        "🧪", ["backtest", "pnl", "sharpe", "drawdown", "history", "performance"]),
    ("Trade Builder",   "/Trade_Builder",     "🧰", ["wizard", "construction", "fly", "weights", "dv01", "ticket", "design"]),
    ("Social Cards",    "/Social_Cards",      "🖼️", ["instagram", "twitter", "social", "card", "image", "1080", "post"]),
    ("Regime",          "/Regime",            "🧭", ["regime", "cluster", "k-means", "kmeans", "high vol", "low vol", "conditional"]),
    ("FX Overlay",      "/FX_Overlay",        "💱", ["fx", "currency", "eurusd", "usdjpy", "dxy", "dollar", "trade weighted"]),
    ("Vol Scorecard",   "/Vol_Scorecard",     "🌊", ["realised", "realized", "vol", "volatility", "rates vol", "term structure"]),
    ("A/B Tests",       "/AB_Tests",          "🧪", ["ab", "a/b", "variant", "subject", "split test", "experiment"]),
    ("CTA Audit",       "/CTA_Audit",         "🔗", ["cta", "utm", "links", "attribution", "audit", "campaign", "tracking"]),
    ("Rates Calendar",  "/Rates_Calendar",    "📅", ["calendar", "fomc", "nfp", "cpi", "auction", "events", "schedule", "data release"]),
    ("Auctions",        "/Auction_Tracker",   "🏛️", ["auction", "treasury", "bid to cover", "indirect", "tail", "primary dealer", "ust"]),
    ("Trade Decomposition", "/Trade_Decomposition", "🧩",
        ["decompose", "decomposition", "carry", "rolldown", "roll", "mean reversion", "waterfall", "expected return"]),
    ("Morning Briefing","/Morning",           "🌅",
        ["morning", "briefing", "daily", "today", "start of day", "summary", "overview"]),
    ("What Changed",    "/What_Changed",      "🆕",
        ["what changed", "delta", "yesterday", "moves", "biggest move", "digest"]),
    ("Watchlist",       "/Watchlist",         "📌",
        ["watchlist", "pin", "pinned", "track", "saved"]),
    ("Bond Futures",    "/Bond_Futures",      "📈",
        ["futures", "cme", "zn", "zb", "zf", "zt", "tn", "ub", "nob", "fyt", "bond future"]),
    ("Subscriber Sync", "/Subscriber_Sync",   "🔄",
        ["sync", "subscriber", "substack", "csv", "import", "export", "merge", "allowlist"]),
    ("Performance",     "/Performance",       "🏆",
        ["performance", "track record", "pnl", "attribution", "totw", "trade of week", "winners"]),
    ("Trade Journal",   "/Trade_Journal",     "📓",
        ["journal", "notes", "log", "diary", "annotations", "thesis", "post-mortem"]),
    ("Global Macro",    "/Global_Macro",      "🌐",
        ["macro", "oecd", "cli", "leading", "jolts", "bls", "openbb", "global", "recession"]),
    ("Global Inflation","/Global_Inflation",  "🔥",
        ["inflation", "cpi", "headline", "core", "breakeven", "country", "deflation", "unemployment"]),
]


def _match(query: str, label: str, keywords: list[str]) -> int:
    """Return a score: 0=no match, higher=better match."""
    q = query.strip().lower()
    if not q:
        return 0
    label_l = label.lower()
    if q == label_l:
        return 100
    if label_l.startswith(q):
        return 80
    if q in label_l:
        return 60
    for kw in keywords:
        kw_l = kw.lower()
        if q == kw_l:
            return 50
        if kw_l.startswith(q):
            return 40
        if q in kw_l:
            return 20
    return 0


def render_search_box() -> None:
    """Render the sidebar search box.  Shows up to 6 best matches as page_links."""
    from dashboard.state import auth_query_string

    st.sidebar.divider()
    q = st.sidebar.text_input(
        "🔎 Search pages",
        placeholder="e.g. 'carry', 'tips', 'pca'…",
        key="_global_search_q",
        label_visibility="visible",
    )
    if not q.strip():
        return

    qs = auth_query_string()  # preserve auth token across navigation
    scored = []
    for label, url, emoji, kw in PAGE_INDEX:
        score = _match(q, label, kw)
        if score:
            scored.append((score, label, url, emoji))
    scored.sort(reverse=True)

    if not scored:
        st.sidebar.caption("_No pages matched._")
        return

    st.sidebar.caption(f"**{len(scored)} match{'es' if len(scored) != 1 else ''}**")
    for _score, label, url, emoji in scored[:6]:
        # Use a styled markdown link rather than st.page_link so we can
        # append the auth query string and survive a hard reload.
        st.sidebar.markdown(
            f'<a href="{url}{qs}" target="_self" '
            f'style="display:block;padding:6px 10px;margin:3px 0;'
            f'background:#122340;border-left:3px solid #4fc3f7;'
            f'border-radius:4px;color:#e8eef9;text-decoration:none;'
            f'font-size:13px">{emoji} {label}</a>',
            unsafe_allow_html=True,
        )
