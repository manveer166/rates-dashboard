"""Reusable tier-aware page gate.

Drop into any page that should be tier-gated:

    from dashboard.components.premium_gate import premium_gate
    if not premium_gate("Vol Scorecard"):
        st.stop()

Tiers (low → high): free < substack < pro = founding < admin.

Tier config lives in `data/premium_pages.json`:
    {
      "Regression": {"required": "substack", "preview_text": "..."},
      "Backtester": {"required": "premium",  "preview_text": "..."}
    }

`required` accepts: free, substack, premium (= pro/founding).
Subscriber tiers stored in `data/subscriber_tiers.json` (email → tier).
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import streamlit as st

from dashboard.state import is_admin
# Imported at top (not lazily inside premium_gate) — the previous lazy
# import desynced sys.modules on Streamlit hot-reloads, producing a
# spurious `KeyError: 'dashboard.components.tiers'` on the Analysis page.
from dashboard.components.tiers import tier_at_or_above, current_user_tier

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


def _utm(campaign: str, target_tier: str = "pro") -> str:
    return SUBSCRIBE_URL + "?" + urlencode({
        "utm_source":   "macromanv_dashboard",
        "utm_medium":   "premium_gate",
        "utm_campaign": f"{campaign}_{target_tier}",
    })


def premium_gate(page_label: str, *, allow_viewer: bool = False) -> bool:
    """Return True if the current user can view this page; render a paywall
    otherwise.

    The page's required tier is read from data/premium_pages.json
    ('substack' or 'premium'). User tier is resolved from
    data/subscriber_tiers.json via the email in session_state, or admin
    via password.
    """
    cfg = _load_config().get(page_label, {})
    required = cfg.get("required", "premium")
    if required == "free":
        return True

    # Page-locked subscribers (email-allowlist mechanism) always pass
    if st.session_state.get("page_lock"):
        return True
    # Admin always passes
    if is_admin():
        return True
    # Legacy: viewer-password users get through if explicitly allowed
    if allow_viewer and st.session_state.get("site_authenticated"):
        return True
    # Tier check
    if tier_at_or_above(required):
        return True

    # ── Render the paywall (different copy per required tier) ────────────
    user_t = current_user_tier()
    teaser = cfg.get("preview_text",
                      "This page is part of the Macro Manv paid dashboard.")

    if required == "substack":
        badge = "📨 SUBSTACK TIER"
        badge_color = "#fbbf24"
        bg = "linear-gradient(135deg,#1a1106 0%,#3a1e0a 100%)"
        cta_label = "📨 Subscribe — $15 / mo"
        cta_campaign = "gate"
        target_tier = "substack"
        also = ("Already a Pro / Founding subscriber? You also have access. "
                "Email-allowlist refresh may be needed if you just signed up.")
    else:  # premium (pro/founding)
        badge = "💎 PRO TIER"
        badge_color = "#4fc3f7"
        bg = "linear-gradient(135deg,#0f1f3a 0%,#1a3056 100%)"
        cta_label = "💎 Upgrade to Pro — $49 / mo"
        cta_campaign = "gate"
        target_tier = "pro"
        # If user is on Substack tier, tell them what's missing
        if user_t == "substack":
            also = ("You're on the Substack tier — this page is part of the "
                    "Pro analytical stack ($49/mo or $29 Founding rate while available).")
        else:
            also = ("Pro includes the paid Substack subscription — one "
                    "checkout, one login.")

    st.markdown(
        f"""
        <div style="background:{bg};border:1px solid {badge_color};
                    border-radius:10px;padding:32px 28px;margin:20px 0;
                    text-align:center">
            <h2 style="color:{badge_color};margin:0 0 8px;font-size:14px;
                       letter-spacing:2px;font-weight:700">🔒 {badge}</h2>
            <h1 style="color:#e8eef9;margin:0 0 12px;font-size:28px;
                       font-weight:700">{page_label}</h1>
            <p style="color:#94a8c9;margin:0 auto 18px;max-width:520px;
                      line-height:1.55;font-size:15px">{teaser}</p>
            <a href="{_utm(cta_campaign, target_tier)}" target="_blank"
               style="display:inline-block;background:{badge_color};color:#0a1628;
                      padding:11px 24px;border-radius:6px;text-decoration:none;
                      font-weight:700;font-size:14px">
                {cta_label}
            </a>
            <p style="color:#6a7e9e;font-size:11px;margin:14px 0 0;
                      max-width:520px;margin-left:auto;margin-right:auto">
                {also}
            </p>
            <p style="margin-top:14px">
                <a href="/Pricing" target="_self"
                   style="color:{badge_color};font-size:12px;
                          text-decoration:none">
                    See full tier comparison →
                </a>
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
                options=["free", "substack", "premium"], required=True),
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
