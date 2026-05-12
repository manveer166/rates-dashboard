"""Email A/B test framework — variant assignment, persistence, stats.

Usage in send_alert.py:

    from analysis.ab_test import get_or_create_test, assign_variant, log_send

    test = get_or_create_test(
        name="2026-W19 weekly subject",
        variant_a="Rates Weekly · the belly is the trade",
        variant_b="This week's top RV signal — receive 2Y/5Y/30Y",
    )
    for email in recipients:
        v = assign_variant(test, email)         # deterministic per (test, email)
        subject = test["variant_a"] if v == "A" else test["variant_b"]
        send_email(to=email, subject=subject, ...)
        log_send(test, email, v)

The Alerts admin page can later mark opens / outcomes and the framework
will compute simple two-proportion z-tests for significance.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Optional

STORE = Path(__file__).parent.parent / "data" / "ab_tests.json"


def _load() -> list:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text())
        except Exception:
            return []
    return []


def _save(rows: list) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(rows, indent=2, default=str))


def get_or_create_test(name: str, variant_a: str, variant_b: str,
                       kind: str = "subject", started_on: Optional[str] = None) -> dict:
    """Find by name or create. Returns the test dict (mutated in place via list ref)."""
    rows = _load()
    for r in rows:
        if r["name"] == name:
            return r
    new = {
        "name": name,
        "kind": kind,                    # 'subject', 'body', 'cta', etc.
        "variant_a": variant_a,
        "variant_b": variant_b,
        "started_on": started_on or str(date.today()),
        "sends_a": 0, "sends_b": 0,
        "opens_a": 0, "opens_b": 0,
        "clicks_a": 0, "clicks_b": 0,
        "assignments": {},               # email -> "A" or "B"
        "log": [],                       # history of assignment + outcomes
        "winner": None,                  # set manually or by significance test
    }
    rows.append(new)
    _save(rows)
    return new


def assign_variant(test: dict, email: str) -> str:
    """Deterministic 50/50 split by hash. Caches assignment per email so a
    user always sees the same variant across re-sends of the same test."""
    if email in test["assignments"]:
        return test["assignments"][email]
    h = hashlib.md5(f"{test['name']}|{email}".encode()).hexdigest()
    v = "A" if int(h, 16) % 2 == 0 else "B"
    test["assignments"][email] = v
    rows = _load()
    for r in rows:
        if r["name"] == test["name"]:
            r["assignments"] = test["assignments"]
            break
    _save(rows)
    return v


def log_send(test: dict, email: str, variant: str) -> None:
    rows = _load()
    for r in rows:
        if r["name"] == test["name"]:
            r[f"sends_{variant.lower()}"] = r.get(f"sends_{variant.lower()}", 0) + 1
            r["log"].append({"ts": datetime.now().isoformat(), "email": email,
                             "variant": variant, "event": "send"})
            _save(rows)
            return


def log_event(test_name: str, email: str, event: str) -> None:
    """event in ('open', 'click'). Looks up the assignment by email."""
    rows = _load()
    for r in rows:
        if r["name"] == test_name:
            v = r["assignments"].get(email, "A").lower()
            key = f"{event}s_{v}"   # opens_a / clicks_b etc.
            r[key] = r.get(key, 0) + 1
            r["log"].append({"ts": datetime.now().isoformat(), "email": email,
                             "variant": v.upper(), "event": event})
            _save(rows)
            return


# ── Stats ────────────────────────────────────────────────────────────────

def two_proportion_z(p1_succ: int, p1_n: int, p2_succ: int, p2_n: int) -> tuple[float, float]:
    """Return (z_stat, p_value_two_sided) for the difference of two proportions."""
    if p1_n == 0 or p2_n == 0:
        return 0.0, 1.0
    p1 = p1_succ / p1_n
    p2 = p2_succ / p2_n
    p_pool = (p1_succ + p2_succ) / (p1_n + p2_n)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / p1_n + 1 / p2_n))
    if se == 0:
        return 0.0, 1.0
    z = (p1 - p2) / se
    # Two-sided normal p-value via erfc
    p = math.erfc(abs(z) / math.sqrt(2))
    return z, p


def compute_stats(test: dict) -> dict:
    sa, sb = test["sends_a"], test["sends_b"]
    oa, ob = test.get("opens_a", 0),  test.get("opens_b", 0)
    ca, cb = test.get("clicks_a", 0), test.get("clicks_b", 0)
    open_rate_a  = oa / sa if sa else 0.0
    open_rate_b  = ob / sb if sb else 0.0
    click_rate_a = ca / sa if sa else 0.0
    click_rate_b = cb / sb if sb else 0.0
    open_z,  open_p  = two_proportion_z(oa, sa, ob, sb)
    click_z, click_p = two_proportion_z(ca, sa, cb, sb)
    return {
        "open_rate_a":  open_rate_a, "open_rate_b":  open_rate_b,
        "click_rate_a": click_rate_a, "click_rate_b": click_rate_b,
        "open_z":  open_z,  "open_p":  open_p,
        "click_z": click_z, "click_p": click_p,
        "open_winner":  ("A" if open_rate_a > open_rate_b else "B")  if sa and sb else None,
        "click_winner": ("A" if click_rate_a > click_rate_b else "B") if sa and sb else None,
        "open_significant":  bool(sa >= 30 and sb >= 30 and open_p  < 0.05),
        "click_significant": bool(sa >= 30 and sb >= 30 and click_p < 0.05),
    }


def list_tests() -> list:
    return _load()
