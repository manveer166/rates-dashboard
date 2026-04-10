"""Streamlit session state and cached data loading — optimised for fast startup."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from datetime import datetime

import pandas as pd
import streamlit as st

from config import DEFAULT_END_DATE, DEFAULT_START_DATE

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"


# ---------------------------------------------------------------------------
# Fast path: read parquet from disk — no network, <100ms
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def _load_from_disk() -> pd.DataFrame:
    """Read the newest on-disk parquets. Returns empty DF if none exist."""
    if not CACHE_DIR.exists():
        return pd.DataFrame()

    master = CACHE_DIR / "master.parquet"
    if master.exists():
        try:
            return pd.read_parquet(master)
        except Exception:
            pass

    # Merge latest treasury + fred parquets
    tsy_files  = sorted(CACHE_DIR.glob("treasury_*.parquet"), key=lambda p: p.stat().st_mtime)
    fred_files = sorted(CACHE_DIR.glob("fred_*.parquet"),     key=lambda p: p.stat().st_mtime)
    tsy  = pd.read_parquet(tsy_files[-1])  if tsy_files  else pd.DataFrame()
    fred = pd.read_parquet(fred_files[-1]) if fred_files else pd.DataFrame()

    if tsy.empty and fred.empty:
        return pd.DataFrame()

    if tsy.empty:
        df = fred
    elif fred.empty:
        df = tsy
    else:
        tsy.index  = pd.to_datetime(tsy.index)
        fred.index = pd.to_datetime(fred.index)
        df = tsy.join(fred, how="outer")

    df = df.sort_index().ffill(limit=3)
    core = [c for c in ["2Y", "5Y", "10Y", "30Y"] if c in df.columns]
    if core:
        df = df.dropna(subset=core, how="all")

    try:
        df.to_parquet(master)
    except Exception:
        pass
    return df


# ---------------------------------------------------------------------------
# Slow path: full network fetch — only on Refresh or first-ever run
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner="Fetching latest market data…")
def _load_from_network(start: str, end: str) -> pd.DataFrame:
    from data.pipeline import DataPipeline
    df = DataPipeline(start_date=start, end_date=end, use_cache=False).load()
    if not df.empty:
        try:
            df.to_parquet(CACHE_DIR / "master.parquet")
        except Exception:
            pass
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

VIEWER_PASSWORD = "rates"
ADMIN_PASSWORD  = "manveer"

# Backwards-compat alias (some old code may import this)
SITE_PASSWORD = VIEWER_PASSWORD


def is_admin() -> bool:
    """True if the current session is logged in with the admin password."""
    return bool(st.session_state.get("site_admin"))


def require_admin(message: str = "Admin only — log in with the admin password to make changes.") -> bool:
    """Render an info banner and return False if the current user is not admin.
    Use to gate write actions inside pages."""
    if is_admin():
        return True
    st.info(f"🔒 {message}")
    return False


def password_gate() -> None:
    """Block the entire app until the user enters a valid password.

    Two passwords are accepted:
      • "rates"   → viewer mode (read-only). Can browse every page but
                    cannot save trades, change alert config, etc.
      • "manveer" → admin mode. Full read + write access.

    Call at the top of every page (called automatically via render_sidebar_controls)."""
    if st.session_state.get("site_authenticated"):
        return
    # Hide the sidebar and main content behind a login form
    st.markdown(
        "<div style='text-align:center; padding-top:60px;'>"
        "<h1>📈 Rates Dashboard</h1>"
        "<p style='color:#8892a4; margin-bottom:30px;'>Enter the password to continue</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        with st.form("site_gate", clear_on_submit=False):
            pw = st.text_input("Password", type="password", placeholder="Enter password")
            if st.form_submit_button("Enter", use_container_width=True):
                if pw == ADMIN_PASSWORD:
                    st.session_state["site_authenticated"] = True
                    st.session_state["site_admin"] = True
                    st.rerun()
                elif pw == VIEWER_PASSWORD:
                    st.session_state["site_authenticated"] = True
                    st.session_state["site_admin"] = False
                    st.rerun()
                else:
                    st.error("Incorrect password.")
        st.page_link("pages/11_User_Guide.py", label="How to use", use_container_width=True)
        from dashboard.tutorial import render_tutorial_button
        render_tutorial_button(
            key_suffix="gate",
            chain=True,
            unlock=True,
            label="🚀 Take the Full Tour",
        )
    st.stop()


def init_session_state() -> None:
    defaults = {
        "start_date": DEFAULT_START_DATE,
        "end_date":   DEFAULT_END_DATE,
        "use_cache":  True,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def get_master_df(force_network: bool = False) -> pd.DataFrame:
    """
    Fast path: disk parquet in <100ms.
    Network path: only on force_network=True or no cache.
    """
    if force_network:
        _load_from_disk.clear()
        _load_from_network.clear()
        return _load_from_network(st.session_state.start_date, st.session_state.end_date)

    df = _load_from_disk()
    if not df.empty:
        return df

    return _load_from_network(st.session_state.start_date, st.session_state.end_date)


def refresh_data() -> None:
    _load_from_disk.clear()
    _load_from_network.clear()
    st.rerun()


def cache_age_str() -> str:
    master = CACHE_DIR / "master.parquet"
    if not master.exists():
        return "no cache"
    age = datetime.now() - datetime.fromtimestamp(master.stat().st_mtime)
    h, m = divmod(int(age.total_seconds()), 3600)
    m //= 60
    return f"{h}h {m}m ago" if h > 0 else f"{m}m ago"
