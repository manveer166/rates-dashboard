"""Stripe checkout integration + Substack comp queue.

End-to-end flow:

  1. User clicks Subscribe on /Subscribe page
       → create_checkout_session(email, tier) returns a Stripe-hosted URL
  2. User pays on Stripe Checkout
       → Stripe redirects to https://app/?stripe_session=cs_xxx
  3. Streamlit picks up the query param on next page load
       → process_completion(session_id) verifies + flips tier
  4. data/subscriber_tiers.json gets updated (auto-grants dashboard Pro access)
  5. data/substack_comp_queue.json gets the new email appended
       → admin downloads CSV from /Subscription_Admin and bulk-uploads to
         Substack's complimentary-subscribers UI once a day/week.

Substack has no public gift API. Step 5 is the one manual step in an
otherwise fully-automated funnel. Takes ~30 seconds per batch.

All operations are idempotent — calling process_completion on the same
session_id twice doesn't double-credit.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

# Stripe SDK is loaded lazily so the module import never fails if the
# library or the API key is missing in the environment.

_ROOT = Path(__file__).parent.parent.parent
TIERS_PATH        = _ROOT / "data" / "subscriber_tiers.json"
COMP_QUEUE_PATH   = _ROOT / "data" / "substack_comp_queue.json"
SESSIONS_PATH     = _ROOT / "data" / "stripe_sessions.json"


# ── Configuration ────────────────────────────────────────────────────────
def _secret(key: str, default: str = "") -> str:
    """Read a secret from Streamlit secrets, then env, then default."""
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


def _stripe():
    """Lazy-init Stripe SDK with the secret key. Returns the module."""
    import stripe
    stripe.api_key = _secret("STRIPE_SECRET_KEY", "")
    if not stripe.api_key:
        raise RuntimeError(
            "STRIPE_SECRET_KEY is not configured. Set it in "
            ".streamlit/secrets.toml or as an env var."
        )
    return stripe


# Tier → Stripe Price ID + monthly price (for display)
TIER_CONFIG = {
    "founding": {
        "display_name": "Founding Seat",
        "price_usd":    29,
        "lock_years":   10,
        "limit":        100,
        "price_id_key": "STRIPE_FOUNDING_PRICE_ID",
    },
    "pro": {
        "display_name": "Pro",
        "price_usd":    49,
        "lock_years":   None,
        "limit":        None,
        "price_id_key": "STRIPE_PRO_PRICE_ID",
    },
    "substack_tier": {
        "display_name": "Substack tier",
        "price_usd":    15,
        "lock_years":   None,
        "limit":        None,
        "price_id_key": "STRIPE_SUBSTACK_PRICE_ID",
    },
}


def stripe_price_id_for(tier: str) -> Optional[str]:
    cfg = TIER_CONFIG.get(tier)
    if not cfg:
        return None
    pid = _secret(cfg["price_id_key"], "")
    return pid or None


def stripe_configured() -> bool:
    """True iff STRIPE_SECRET_KEY + the founding/pro price IDs are set."""
    if not _secret("STRIPE_SECRET_KEY"):
        return False
    if not (_secret("STRIPE_FOUNDING_PRICE_ID") or _secret("STRIPE_PRO_PRICE_ID")):
        return False
    return True


# ── Checkout session creation ────────────────────────────────────────────
def create_checkout_session(email: str, tier: str,
                              success_url_base: str = None) -> str:
    """Create a Stripe Checkout Session for an email + tier.

    Returns the hosted checkout URL. The user gets redirected to this URL,
    completes payment on Stripe-hosted page, then Stripe redirects them
    back to {success_url_base}/?stripe_session=cs_xxx.

    Records the session locally so we can verify it later even if the
    callback arrives out-of-band.
    """
    price_id = stripe_price_id_for(tier)
    if not price_id:
        raise ValueError(
            f"No Stripe Price ID configured for tier='{tier}'. Set "
            f"{TIER_CONFIG[tier]['price_id_key']} in secrets."
        )

    stripe = _stripe()
    if not success_url_base:
        success_url_base = _secret(
            "DASHBOARD_URL",
            "https://rates-dashboard-6gmz8swptjxoapenjwptgm.streamlit.app",
        )

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        customer_email=email.strip().lower(),
        client_reference_id=email.strip().lower(),
        metadata={"tier": tier, "email": email.strip().lower()},
        success_url=f"{success_url_base}/?stripe_session={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{success_url_base}/Pricing",
        allow_promotion_codes=True,
        billing_address_collection="auto",
    )
    _record_session(session.id, email, tier, "created")
    return session.url


# ── Session-completion handling ──────────────────────────────────────────
def process_completion(session_id: str) -> dict:
    """Verify a checkout session with Stripe + flip the user's tier.

    Returns a result dict with keys: ok (bool), email, tier, message.
    Idempotent: calling twice on the same session_id is safe — only the
    first call actually flips the tier and queues the Substack comp.
    """
    # Idempotency guard — have we already processed this session?
    sessions = _load_sessions()
    rec = sessions.get(session_id)
    if rec and rec.get("status") == "processed":
        return {
            "ok":      True,
            "email":   rec.get("email"),
            "tier":    rec.get("tier"),
            "message": "Already processed — no double-credit.",
        }

    try:
        stripe = _stripe()
        s = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        return {"ok": False, "email": None, "tier": None,
                "message": f"Could not verify session: {e}"}

    if s.payment_status != "paid":
        return {"ok": False,
                "email":   s.customer_email or s.customer_details.email if s.customer_details else None,
                "tier":    s.metadata.get("tier") if s.metadata else None,
                "message": f"Payment status is '{s.payment_status}' — not yet paid."}

    email = (s.metadata.get("email") if s.metadata else None) \
            or s.customer_email \
            or (s.customer_details.email if s.customer_details else None)
    tier  = (s.metadata.get("tier")  if s.metadata else None) or "pro"

    if not email:
        return {"ok": False, "email": None, "tier": tier,
                "message": "Stripe session has no email — cannot process."}

    # Flip the dashboard tier
    set_subscriber_tier(email, tier)
    # Queue the Substack complimentary subscription
    queue_substack_comp(email, tier, source_session=session_id)
    # Record we've processed this session
    _record_session(session_id, email, tier, "processed")

    return {"ok": True, "email": email, "tier": tier,
            "message": f"✅ Granted {tier} access to {email}. Queued for Substack comp."}


# ── Subscriber tier store (data/subscriber_tiers.json) ──────────────────
def _load_tiers() -> dict:
    if TIERS_PATH.exists():
        try:
            return json.loads(TIERS_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_tiers(d: dict) -> None:
    TIERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TIERS_PATH.write_text(json.dumps(d, indent=2))


def set_subscriber_tier(email: str, tier: str) -> None:
    """Idempotent — sets the tier whether or not the user existed."""
    email = email.strip().lower()
    d = _load_tiers()
    # Preserve any _format_note / _examples keys
    d[email] = tier
    _save_tiers(d)


def get_subscriber_tier(email: str) -> Optional[str]:
    email = (email or "").strip().lower()
    if not email:
        return None
    return _load_tiers().get(email)


# ── Substack complimentary-subscription queue ───────────────────────────
def _load_comp_queue() -> list[dict]:
    if COMP_QUEUE_PATH.exists():
        try:
            return json.loads(COMP_QUEUE_PATH.read_text())
        except Exception:
            return []
    return []


def _save_comp_queue(q: list[dict]) -> None:
    COMP_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMP_QUEUE_PATH.write_text(json.dumps(q, indent=2, default=str))


def queue_substack_comp(email: str, tier: str,
                          source_session: str = "") -> None:
    """Append an email to the Substack comp queue. Idempotent — same email
    isn't queued twice if it's still pending."""
    email = email.strip().lower()
    q = _load_comp_queue()
    if any(e.get("email") == email and e.get("status") == "pending"
           for e in q):
        return
    q.append({
        "email":           email,
        "tier":            tier,
        "queued_at":       datetime.utcnow().isoformat() + "Z",
        "status":          "pending",
        "source_session":  source_session,
        "comped_at":       None,
    })
    _save_comp_queue(q)


def pending_substack_comps() -> list[dict]:
    return [e for e in _load_comp_queue() if e.get("status") == "pending"]


def mark_comps_processed(emails: list[str]) -> int:
    """Mark a list of emails as comped on Substack. Returns count updated."""
    emails_set = {e.strip().lower() for e in emails}
    q = _load_comp_queue()
    n = 0
    for e in q:
        if (e.get("email") in emails_set
                and e.get("status") == "pending"):
            e["status"]    = "comped"
            e["comped_at"] = datetime.utcnow().isoformat() + "Z"
            n += 1
    _save_comp_queue(q)
    return n


def comp_queue_csv() -> str:
    """Return a Substack-ready CSV: just emails, one per line.

    Substack's bulk-comp UI accepts a plain list of emails — no header
    required, no extra columns.
    """
    pending = pending_substack_comps()
    return "\n".join(e["email"] for e in pending) + ("\n" if pending else "")


# ── Stripe session log (idempotency + audit) ────────────────────────────
def _load_sessions() -> dict:
    if SESSIONS_PATH.exists():
        try:
            return json.loads(SESSIONS_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_sessions(d: dict) -> None:
    SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_PATH.write_text(json.dumps(d, indent=2, default=str))


def _record_session(session_id: str, email: str, tier: str,
                     status: str) -> None:
    d = _load_sessions()
    d[session_id] = {
        "email":       (email or "").strip().lower(),
        "tier":        tier,
        "status":      status,
        "updated_at":  datetime.utcnow().isoformat() + "Z",
    }
    _save_sessions(d)


def list_subscribers_with_status() -> list[dict]:
    """All Stripe sessions we've seen, joined with current tier status.
    Useful for the Subscription Admin page."""
    sessions = _load_sessions()
    tiers    = _load_tiers()
    out = []
    for sid, s in sessions.items():
        email = s.get("email", "")
        out.append({
            "session_id":    sid,
            "email":         email,
            "tier_at_pay":   s.get("tier"),
            "current_tier":  tiers.get(email, "free"),
            "status":        s.get("status"),
            "updated_at":    s.get("updated_at"),
        })
    return sorted(out, key=lambda r: r.get("updated_at") or "", reverse=True)
