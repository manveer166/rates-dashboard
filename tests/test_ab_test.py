"""Tests for the A/B test framework."""

from __future__ import annotations

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from analysis import ab_test


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    """Redirect the JSON store to a temp file so tests don't pollute real data."""
    monkeypatch.setattr(ab_test, "STORE", tmp_path / "ab_tests.json")
    yield


def test_create_and_round_trip():
    t = ab_test.get_or_create_test("subj_a_vs_b", "Alpha", "Beta",
                                     kind="subject", started_on="2026-01-01")
    assert t["variant_a"] == "Alpha"
    assert t["variant_b"] == "Beta"
    # Idempotent
    t2 = ab_test.get_or_create_test("subj_a_vs_b", "Alpha", "Beta")
    assert t2["name"] == t["name"]


def test_assign_variant_is_deterministic():
    t = ab_test.get_or_create_test("deterministic", "A", "B")
    v1 = ab_test.assign_variant(t, "user@example.com")
    v2 = ab_test.assign_variant(t, "user@example.com")
    assert v1 == v2          # same input → same variant
    assert v1 in ("A", "B")


def test_assign_variant_splits_50_50():
    t = ab_test.get_or_create_test("split", "A", "B")
    counts = {"A": 0, "B": 0}
    for i in range(200):
        counts[ab_test.assign_variant(t, f"u{i}@x.com")] += 1
    # Deterministic split — should be reasonably balanced
    assert abs(counts["A"] - counts["B"]) < 50    # within ~25% of 50/50


def test_two_proportion_z_known_values():
    """Two-sample test with known proportions."""
    # 50% vs 50% — no difference
    z, p = ab_test.two_proportion_z(50, 100, 50, 100)
    assert z == pytest.approx(0.0, abs=1e-6)
    assert p == pytest.approx(1.0, abs=1e-6)

    # Clear winner: 70% vs 30%, n=100 each — p should be tiny
    z, p = ab_test.two_proportion_z(70, 100, 30, 100)
    assert z > 5.0
    assert p < 1e-6


def test_compute_stats_significance():
    """Verify the 'significant' flag triggers above 30 sends + p<0.05."""
    t = ab_test.get_or_create_test("sig_test", "A", "B")
    rows = ab_test._load()
    for r in rows:
        if r["name"] == "sig_test":
            r["sends_a"] = 100; r["sends_b"] = 100
            r["opens_a"] = 25;  r["opens_b"] = 38     # noticeable gap
            ab_test._save(rows)
            break
    t = next(r for r in ab_test._load() if r["name"] == "sig_test")
    stats = ab_test.compute_stats(t)
    assert stats["open_rate_a"] == pytest.approx(0.25)
    assert stats["open_rate_b"] == pytest.approx(0.38)
    assert stats["open_winner"] == "B"
    assert stats["open_significant"] is True       # p ~ 0.048, n ≥ 30 ✓
