"""Watchlist storage helpers.

Persists pinned trades to data/watchlist.json. Each entry:

    {
        "id":           "<uuid>",
        "trade":        "Rcv 2Y/5Y/10Y",
        "type_":        "Fly",
        "direction":    "receive",
        "pinned_at":    "2026-05-14",
        "pinned_level": -15.23,
        "note":         "Belly looks cheap pre-CPI",
    }

The Watchlist page reads this + computes live PnL since pin.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

STORE = Path(__file__).parent.parent.parent / "data" / "watchlist.json"


def _load() -> list[dict]:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text())
        except Exception:
            return []
    return []


def _save(rows: list[dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(rows, indent=2, default=str))


def pin_trade(trade: str, type_: str, direction: str,
              pinned_level: float, note: str = "") -> str:
    """Pin a trade. Returns the new entry's id."""
    rows = _load()
    new_id = str(uuid.uuid4())[:8]
    rows.append({
        "id":           new_id,
        "trade":        trade,
        "type_":        type_,
        "direction":    direction,
        "pinned_at":    str(date.today()),
        "pinned_level": float(pinned_level),
        "note":         note,
    })
    _save(rows)
    return new_id


def unpin(entry_id: str) -> None:
    _save([r for r in _load() if r.get("id") != entry_id])


def list_pins() -> list[dict]:
    return _load()


def update_note(entry_id: str, note: str) -> None:
    rows = _load()
    for r in rows:
        if r.get("id") == entry_id:
            r["note"] = note
            break
    _save(rows)
