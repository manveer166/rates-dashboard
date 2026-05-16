"""
RSS feed widgets — Substack (Macro Manv), Bloomberg Markets, FT Markets.

Used by:
  Home.py        → render_substack_tile()  (latest 3 Macro Manv posts)
  10_Alerts.py   → render_news_panel()     (3-col market news next to composer)

Feeds are cached for 15 min (st.cache_data) so we don't pound upstream on
every Streamlit rerun.  All Macro Manv links carry UTM params so click-throughs
from the dashboard show up cleanly in your analytics.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List
from urllib.parse import urlencode

import streamlit as st

logger = logging.getLogger(__name__)

SUBSTACK_FEED  = "https://manveersahota.substack.com/feed"
BLOOMBERG_FEED = "https://feeds.bloomberg.com/markets/news.rss"
FT_FEED        = "https://www.ft.com/markets?format=rss"

# Central bank press releases (free, no key)
FED_FEED       = "https://www.federalreserve.gov/feeds/press_monetary.xml"
ECB_FEED       = "https://www.ecb.europa.eu/rss/press.html"
BOE_FEED       = "https://www.bankofengland.co.uk/rss/news"

_BASE_UTM = {"utm_source": "macromanv_dashboard", "utm_medium": "rss_widget"}


# ── Fetch + parse ─────────────────────────────────────────────────────────

_RSS_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 macromanv-dashboard/1.0")


def _fetch_raw(url: str, limit: int = 10) -> List[Dict]:
    """Direct RSS pull — no caching. Some sites (ECB, BoE) 403 the default
    feedparser user-agent, so we pass a browser-like UA."""
    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed — `pip install feedparser`")
        return []
    try:
        feed = feedparser.parse(url, agent=_RSS_USER_AGENT)
        out = []
        for e in feed.entries[:limit]:
            out.append({
                "title":     str(e.get("title", "(untitled)")).strip(),
                "link":      str(e.get("link", "#")),
                "published": str(e.get("published", e.get("updated", ""))),
                "summary":   str(e.get("summary", ""))[:300],
            })
        return out
    except Exception as ex:
        logger.warning("RSS fetch failed for %s: %s", url, ex)
        return []


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_cached(url: str, limit: int = 10) -> List[Dict]:
    """Cached wrapper. Only the non-empty path is worth caching — an empty
    result usually means a transient network blip and we'd rather retry
    on the next render than show 'Feed unavailable' for 15 minutes."""
    return _fetch_raw(url, limit)


def _fetch(url: str, limit: int = 10) -> List[Dict]:
    """Return [{title, link, published, summary}, …]. Auto-retries when
    the cache layer has an empty result — fixes the 'cached transient
    failure' pattern that made ECB show 'Feed unavailable' for 15min."""
    items = _fetch_cached(url, limit)
    if items:
        return items
    # Cache had an empty entry; try fresh (bypassing cache) and, if that
    # succeeds, clear the bad cached entry so subsequent renders pick up
    # the fresh data immediately.
    fresh = _fetch_raw(url, limit)
    if fresh:
        try: _fetch_cached.clear()
        except Exception: pass
    return fresh


def _utm(link: str, campaign: str) -> str:
    """Append UTM params (only used for Macro Manv links)."""
    sep = "&" if "?" in link else "?"
    return f"{link}{sep}{urlencode({**_BASE_UTM, 'utm_campaign': campaign})}"


def _is_macromanv(link: str) -> bool:
    return "manveersahota" in link or "macromanv" in link


def _fmt_date(raw: str) -> str:
    """RSS pubDate (RFC-822 or ISO) → 'dd Mon YYYY'."""
    if not raw:
        return ""
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            return datetime.strptime(raw, fmt).strftime("%d %b %Y")
        except Exception:
            pass
    return raw[:11]


# ── Renderers ─────────────────────────────────────────────────────────────

def render_substack_tile(limit: int = 3, campaign: str = "home_tile") -> None:
    """Bordered 'Latest from Macro Manv' card — for the top of Home.py."""
    items = _fetch(SUBSTACK_FEED, limit=limit)

    parts = [
        '<div style="background:#122340;border-left:4px solid #4fc3f7;'
        'padding:14px 18px;border-radius:6px;margin:8px 0 16px;">',
        '<h3 style="color:#4fc3f7;margin:0 0 8px;font-size:13px;'
        'letter-spacing:.6px;font-weight:700;">📨 LATEST FROM MACRO MANV</h3>',
    ]

    if not items:
        parts.append(
            '<p style="color:#94a8c9;font-size:12px;margin:6px 0 8px">'
            'Feed unavailable — try again in a few minutes.</p>'
        )
    else:
        for it in items:
            date_str = _fmt_date(it["published"])
            link     = _utm(it["link"], campaign)
            parts.append(
                f'<div style="margin:8px 0">'
                f'<a href="{link}" target="_blank" '
                f'style="color:#e8eef9;text-decoration:none;font-weight:600;font-size:14px;line-height:1.35">'
                f'{it["title"]}</a>'
                f'<div style="color:#6a7e9e;font-size:11px;margin-top:2px">{date_str}</div>'
                f'</div>'
            )

    sub_link = _utm("https://manveersahota.substack.com/subscribe", campaign)
    parts.append(
        f'<a href="{sub_link}" target="_blank" '
        f'style="display:inline-block;margin-top:8px;background:#4fc3f7;'
        f'color:#0a1628;padding:6px 14px;border-radius:6px;text-decoration:none;'
        f'font-weight:700;font-size:12px;">📬 Subscribe to Macro Manv</a></div>'
    )
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_news_panel(limit_per_source: int = 5, campaign: str = "alerts_panel") -> None:
    """3-column market news panel for the Alerts page composer."""
    sub = _fetch(SUBSTACK_FEED,  limit=limit_per_source)
    bbg = _fetch(BLOOMBERG_FEED, limit=limit_per_source)
    ft  = _fetch(FT_FEED,        limit=limit_per_source)

    c1, c2, c3 = st.columns(3)

    def _column(col, items, label, color, source_link, source_label):
        with col:
            html = [
                f'<div style="border-left:3px solid {color};padding-left:10px;margin-bottom:6px">'
                f'<h4 style="color:{color};margin:0;font-size:12px;'
                f'letter-spacing:.6px;font-weight:700">{label}</h4></div>',
            ]
            if not items:
                html.append('<p style="color:#94a8c9;font-size:11px;margin:6px 0">Feed unavailable.</p>')
            else:
                for it in items:
                    date_str = _fmt_date(it["published"])
                    link = _utm(it["link"], campaign) if _is_macromanv(it["link"]) else it["link"]
                    html.append(
                        f'<div style="margin:6px 0;font-size:13px;line-height:1.35">'
                        f'<a href="{link}" target="_blank" '
                        f'style="color:#e8eef9;text-decoration:none">{it["title"]}</a>'
                        f'<div style="color:#6a7e9e;font-size:10px;margin-top:1px">{date_str}</div>'
                        f'</div>'
                    )
            html.append(
                f'<a href="{source_link}" target="_blank" '
                f'style="color:{color};font-size:11px;text-decoration:none">'
                f'→ {source_label}</a>'
            )
            st.markdown("".join(html), unsafe_allow_html=True)

    _column(c1, sub, "MACRO MANV", "#4ade80",
            _utm("https://manveersahota.substack.com", campaign), "All posts")
    _column(c2, bbg, "BLOOMBERG MARKETS", "#fb923c",
            "https://www.bloomberg.com/markets/", "Bloomberg.com")
    _column(c3, ft,  "FT MARKETS", "#fbbf24",
            "https://www.ft.com/markets", "FT.com")


# ── Central-bank press release panel ─────────────────────────────────────

def render_central_banks_panel(limit_per_source: int = 5) -> None:
    """3-column Fed / ECB / BoE press-release panel.

    Use under the markets news panel on the Alerts page to give context for
    weekly notes (rate decisions, speeches, monetary policy statements)."""
    fed = _fetch(FED_FEED, limit=limit_per_source)
    ecb = _fetch(ECB_FEED, limit=limit_per_source)
    boe = _fetch(BOE_FEED, limit=limit_per_source)

    c1, c2, c3 = st.columns(3)

    def _column(col, items, label, color, source_link, source_label):
        with col:
            html = [
                f'<div style="border-left:3px solid {color};padding-left:10px;margin-bottom:6px">'
                f'<h4 style="color:{color};margin:0;font-size:12px;'
                f'letter-spacing:.6px;font-weight:700">{label}</h4></div>',
            ]
            if not items:
                html.append('<p style="color:#94a8c9;font-size:11px;margin:6px 0">Feed unavailable.</p>')
            else:
                for it in items:
                    date_str = _fmt_date(it["published"])
                    html.append(
                        f'<div style="margin:6px 0;font-size:13px;line-height:1.35">'
                        f'<a href="{it["link"]}" target="_blank" '
                        f'style="color:#e8eef9;text-decoration:none">{it["title"]}</a>'
                        f'<div style="color:#6a7e9e;font-size:10px;margin-top:1px">{date_str}</div>'
                        f'</div>'
                    )
            html.append(
                f'<a href="{source_link}" target="_blank" '
                f'style="color:{color};font-size:11px;text-decoration:none">'
                f'→ {source_label}</a>'
            )
            st.markdown("".join(html), unsafe_allow_html=True)

    _column(c1, fed, "FEDERAL RESERVE", "#22d3ee",
            "https://www.federalreserve.gov/newsevents/pressreleases.htm", "fed.gov")
    _column(c2, ecb, "ECB",             "#a78bfa",
            "https://www.ecb.europa.eu/press/html/index.en.html", "ecb.europa.eu")
    _column(c3, boe, "BANK OF ENGLAND", "#f472b6",
            "https://www.bankofengland.co.uk/news", "bankofengland.co.uk")


# ── Headlines export for PDF embedding ───────────────────────────────────

def fetch_headlines_for_pdf(limit_per_source: int = 4) -> list[dict]:
    """Return a flat list of recent headlines for the weekly PDF.

    Each item is {source, title, link, published}.  Used by analysis/weekly_pdf.py
    to embed a 'WEEK IN REVIEW' headline strip beneath the Friday recap.
    """
    out: list[dict] = []
    for src, url in (("Macro Manv", SUBSTACK_FEED),
                     ("Bloomberg", BLOOMBERG_FEED),
                     ("FT",        FT_FEED),
                     ("Fed",       FED_FEED),
                     ("ECB",       ECB_FEED),
                     ("BoE",       BOE_FEED)):
        for it in _fetch(url, limit=limit_per_source):
            out.append({"source": src, **it})
    return out
