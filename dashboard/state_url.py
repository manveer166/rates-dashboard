"""URL query-param helpers — make selectors shareable and bookmarkable.

Streamlit's `st.session_state` is per-tab and dies on a hard reload.  This
module mirrors selected widget state into the URL via `st.query_params`, so:

  • a user can refresh the page and not lose their selections
  • a user can copy the URL and send "here's the 5s30s view I'm looking at"
  • a Substack-embedded link can deep-link into a specific configuration

Usage in a page:

    from dashboard.state_url import url_state

    # Read with default; subsequent write_widget() syncs the URL on change
    selected = url_state.read("tenors", default=["2Y","5Y","10Y"], cast=list)
    new_val  = st.multiselect("Tenors", options=ALL_TENORS, default=selected)
    url_state.write_widget("tenors", new_val, default=["2Y","5Y","10Y"])

    # At the top of the page, render a share-URL button:
    url_state.share_button()

The helper preserves any existing params (e.g. ?auth=<token>) and only
touches its own keys.  Reserved keys are protected via `_RESERVED`.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Union
from urllib.parse import urlencode

import streamlit as st

# Params that other systems own — we never overwrite or strip these.
_RESERVED: set[str] = {"auth"}


class _UrlState:
    """Thin wrapper over `st.query_params` with type-aware read/write."""

    # ── Reading ──────────────────────────────────────────────────────────

    def read(self, key: str, default: Any = None, cast: Any = str) -> Any:
        """Return the value of `key` from the URL, cast appropriately.

        cast=str   → returns the raw string (default)
        cast=int   → int(value), or default on parse failure
        cast=float → float(value), or default
        cast=bool  → 'true'/'1'/'yes' → True; else False
        cast=list  → comma-separated string → list of strings
        """
        qp = st.query_params
        if key not in qp:
            return default
        raw = qp[key]
        # Streamlit returns either str or list[str] for repeated params
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        try:
            if cast is str:
                return raw
            if cast is int:
                return int(raw)
            if cast is float:
                return float(raw)
            if cast is bool:
                return str(raw).lower() in ("1", "true", "yes", "y", "on")
            if cast is list:
                return [x for x in raw.split(",") if x]
        except (ValueError, TypeError):
            return default
        return raw

    # ── Writing ──────────────────────────────────────────────────────────

    def write(self, **params: Any) -> None:
        """Update query params for the given keys.  Empty / None values
        are removed from the URL (keeps it tidy).  Reserved keys are
        ignored to avoid clobbering auth tokens."""
        for k, v in params.items():
            if k in _RESERVED:
                continue
            if v is None or v == "" or (isinstance(v, (list, tuple, set)) and not v):
                if k in st.query_params:
                    del st.query_params[k]
                continue
            if isinstance(v, (list, tuple, set)):
                st.query_params[k] = ",".join(str(x) for x in v)
            elif isinstance(v, bool):
                st.query_params[k] = "1" if v else "0"
            else:
                st.query_params[k] = str(v)

    def write_widget(self, key: str, value: Any, default: Any = None) -> None:
        """Write a widget's value to the URL, but only if it differs from
        the default — keeps shareable URLs short and meaningful."""
        if default is not None and value == default:
            if key in st.query_params and key not in _RESERVED:
                del st.query_params[key]
            return
        self.write(**{key: value})

    # ── Share helper ─────────────────────────────────────────────────────

    def share_query(self) -> str:
        """Return the shareable query string '?k=v&k2=v2' (excluding auth).

        Caller appends to their host URL, e.g. `https://dashboard…{share_query}`.
        """
        params = {k: v for k, v in st.query_params.to_dict().items()
                  if k not in _RESERVED}
        return ("?" + urlencode(params, doseq=True)) if params else ""

    def share_button(self, label: str = "📋 Share this view",
                     key: str = "_share_url_btn") -> None:
        """Render a button that reveals a copyable share-URL fragment."""
        if st.button(label, key=key, use_container_width=False):
            qs = self.share_query()
            if not qs:
                st.info("No view-specific selections to share yet — "
                        "tweak a selector first.")
                return
            st.code(qs, language=None)
            st.caption(
                "👆 Append to the dashboard URL "
                "(e.g. `https://your-dashboard.com/Yield_Curve" + qs + "`) "
                "and share with subscribers."
            )


# Single shared instance — import as: `from dashboard.state_url import url_state`
url_state = _UrlState()
