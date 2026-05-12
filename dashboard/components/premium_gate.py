"""Reusable premium-tier gate.

Drop into any page that should be premium-only:

    from dashboard.components.premium_gate import premium_gate
    if not premium_gate("Vol Scorecard"):
        st.stop()

Free users see a styled paywall with a teaser + Subscribe CTA (UTM-tagged).
Admin / premium users pass through transparently.

Tier config lives in `data/premium_pages.json`:
    {
      "29_Vol_Scorecard":  {"required": "premium", "preview_text": "..."},
      "24_Backtester":     {"required": "premium"}
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import streamlit as st

from dashboard.state import is_admin

CONFIG_PATH = Path(__file__).parent.parent.parent / "data" / "premium_pages.json"
SUBSCRIBE_URL = "https://manveersahota.substack.com/subscribe"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


def _user_tier() -> str:
    """Resolve the current user's tier.  Admin > premium > free."""
    if is_admin():
        return "admin"
    # Page-locked subscribers get treated as 'premium' on their unlocked page
    # but 'free' elsewhere.  Without that we'd lock them out of pages they
    # have explicit access to.
    if st.session_state.get("page_lock"):
        return "page_unlocked"
    if st.session_state.get("site_authenticated"):
        return "viewer"
    return "free"


def _utm(campaign: str) -> str:
    return SUBSCRIBE_URL + "?" + urlencode({
        "utm_source":   "macromanv_dashboard",
        "utm_medium":   "premium_gate",
        "utm_campaign": campaign,
    })


def premium_gate(page_label: str, *, allow_viewer: bool = False) -> bool:
    """Return True if the current user can view this page; render a paywall and
    return False otherwise.

    page_label   : human-friendly label used in the paywall copy + UTM campaign
    allow_viewer : if True, basic 'viewer' tier (any password) gets through;
                   default False = premium / admin only.
    """
    cfg = _load_config().get(page_label, {})
    required = cfg.get("required", "premium")  # default new pages to premium
    if required == "free":
        return True

    tier = _user_tier()
    if tier in ("admin", "page_unlocked"):
        return True
    if allow_viewer and tier == "viewer":
        return True
    if required == "viewer" and tier == "viewer":
        return True

    # ── Render paywall ───────────────────────────────────────────────────
    teaser = cfg.get(
        "preview_text",
        "This page is part of the Macro Manv premium dashboard. "
        "Subscribers get the full scanner, backtester, vol scorecard, and "
        "weekly PDF — plus the daily morning brief.",
    )
    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,#0f1f3a 0%,#1a3056 100%);
                    border:1px solid #4fc3f7;border-radius:10px;
                    padding:32px 28px;margin:20px 0;text-align:center">
            <h2 style="color:#4fc3f7;margin:0 0 8px;font-size:18px;
                       letter-spacing:2px;font-weight:700">🔒 PREMIUM</h2>
            <h1 style="color:#e8eef9;margin:0 0 12px;font-size:28px;
                       font-weight:700">{page_label}</h1>
            <p style="color:#94a8c9;margin:0 auto 18px;max-width:520px;
                      line-height:1.55;font-size:15px">{teaser}</p>
            <a href="{_utm(page_label)}" target="_blank"
               style="display:inline-block;background:#4fc3f7;color:#0a1628;
                      padding:10px 22px;border-radius:6px;text-decoration:none;
                      font-weight:700;font-size:14px">
                📬 Subscribe to Macro Manv →
            </a>
            <p style="color:#6a7e9e;font-size:11px;margin:14px 0 0">
                Free posts continue on the Substack — premium dashboard access
                is included in the paid plan.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    return False


# ── Admin UI for managing premium pages ──────────────────────────────────

def render_admin_premium_config() -> None:
    """Drop into Admin page to manage which pages are premium-gated."""
    if not is_admin():
        st.warning("Admin only.")
        return
    st.subheader("🔒 Premium page gate config")
    cfg = _load_config()

    # All pages from the search index — same source of truth as the sidebar
    from dashboard.components.search import PAGE_INDEX
    rows = []
    for label, url, _, _ in PAGE_INDEX:
        slug = url.lstrip("/") or "Home"
        rows.append({
            "Page":     label,
            "Slug":     slug,
            "Required": cfg.get(label, {}).get("required", "free"),
            "Preview":  cfg.get(label, {}).get("preview_text", ""),
        })
    edit_df = st.data_editor(
        rows, use_container_width=True, hide_index=True,
        column_config={
            "Required": st.column_config.SelectboxColumn(
                options=["free", "viewer", "premium"], required=True),
            "Preview":  st.column_config.TextColumn(width="large"),
        },
        num_rows="fixed", key="premium_cfg_editor",
    )
    if st.button("💾 Save premium config", use_container_width=True,
                  type="primary"):
        new = {}
        for row in edit_df:
            if row["Required"] != "free" or row["Preview"]:
                new[row["Page"]] = {
                    "required":     row["Required"],
                    "preview_text": row["Preview"],
                }
        _save_config(new)
        st.success(f"Saved — {len(new)} page(s) gated.")
        st.rerun()
