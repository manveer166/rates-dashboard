"""Page 32 — Rates Calendar.

Upcoming FOMC, NFP, CPI, retail sales, and Treasury auctions on one page,
with countdown days and impact tier. Critical context for rates traders +
Substack content timing.

Data sources (all free):
  • TreasuryDirect public API (no key) — auction announcements
  • Hardcoded FOMC dates (publicly announced 2026 schedule)
  • Algorithmic 1st-Friday-of-month for NFP, mid-month for CPI/PPI/retail sales
"""

from __future__ import annotations

import calendar as _cal
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import requests
import streamlit as st

from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import init_session_state, password_gate

st.set_page_config(page_title="Rates Calendar", page_icon="📅", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Rates Calendar")

st.title("📅 Rates Calendar")
st.caption(
    "Upcoming FOMC, top-tier macro releases, and Treasury auctions. "
    "Sorted by date with countdown days and impact tier — handy for "
    "deciding when to publish a Substack post or send the weekly alert."
)
st.divider()


# ── Tier definitions ─────────────────────────────────────────────────────
TIER_1 = {"FOMC", "NFP", "CPI"}                 # market-moving, plan around them
TIER_2 = {"Retail Sales", "PPI", "PCE", "GDP"}  # important macro
TIER_3 = {"Auction"}                            # supply / mechanical

TIER_COLORS = {
    "Tier 1": "#f87171",
    "Tier 2": "#fbbf24",
    "Tier 3": "#94a8c9",
}

def _tier(event_type: str) -> str:
    if event_type in TIER_1: return "Tier 1"
    if event_type in TIER_2: return "Tier 2"
    return "Tier 3"


# ── 2026 FOMC dates (publicly announced) ─────────────────────────────────
FOMC_2026 = [
    date(2026, 1, 28),  date(2026, 3, 18),
    date(2026, 4, 29),  date(2026, 6, 17),
    date(2026, 7, 29),  date(2026, 9, 16),
    date(2026, 10, 28), date(2026, 12, 16),
]
FOMC_2027_PROJECTED = [   # rough projection — Fed publishes around June 2026
    date(2027, 1, 27),  date(2027, 3, 17),
    date(2027, 4, 28),  date(2027, 6, 16),
]


def _first_friday(year: int, month: int) -> date:
    """First Friday of the month — when NFP is published."""
    d = date(year, month, 1)
    while d.weekday() != 4:    # Friday
        d += timedelta(days=1)
    return d


def _macro_calendar(start: date, months_ahead: int = 6) -> list[dict]:
    """Generate algorithmic NFP / CPI / PPI / Retail Sales / PCE dates."""
    out = []
    cur = date(start.year, start.month, 1)
    for _ in range(months_ahead + 1):
        y, m = cur.year, cur.month

        # NFP — 1st Friday (published 8:30 ET)
        out.append({
            "date":  _first_friday(y, m),
            "event": f"NFP — {_cal.month_abbr[m]} payrolls",
            "type":  "NFP",
        })
        # CPI — typically 10th-15th, second Wednesday-ish of the month
        d = date(y, m, 10)
        while d.weekday() != 2:    # Wednesday
            d += timedelta(days=1)
        if d.day < 10: d += timedelta(days=7)  # ensure ≥ 10th
        out.append({
            "date":  d,
            "event": f"CPI — {_cal.month_abbr[m]}",
            "type":  "CPI",
        })
        # PPI — usually day after CPI
        out.append({
            "date":  d + timedelta(days=1),
            "event": f"PPI — {_cal.month_abbr[m]}",
            "type":  "PPI",
        })
        # Retail Sales — mid-month, around 15th
        d2 = date(y, m, 15)
        while d2.weekday() > 4:    # skip weekends
            d2 += timedelta(days=1)
        out.append({
            "date":  d2,
            "event": f"Retail Sales — {_cal.month_abbr[m]}",
            "type":  "Retail Sales",
        })
        # PCE — last Friday of month-ish
        d3 = date(y, m, _cal.monthrange(y, m)[1])
        while d3.weekday() != 4:
            d3 -= timedelta(days=1)
        out.append({
            "date":  d3,
            "event": f"PCE — {_cal.month_abbr[m]}",
            "type":  "PCE",
        })
        # advance to next month
        if m == 12: cur = date(y + 1, 1, 1)
        else:        cur = date(y, m + 1, 1)
    return out


# ── TreasuryDirect auctions ──────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_auctions() -> list[dict]:
    try:
        r = requests.get(
            "https://www.treasurydirect.gov/TA_WS/securities/announced",
            params={"format": "json"}, timeout=15,
        )
        r.raise_for_status()
        items = r.json()
    except Exception:
        return []
    out = []
    for it in items:
        try:
            d = datetime.fromisoformat(
                it["auctionDate"].replace("Z", "")
            ).date()
            term  = it.get("securityTerm", "")
            stype = it.get("securityType", "")
            out.append({
                "date":  d,
                "event": f"{term} {stype} auction",
                "type":  "Auction",
                "extra": f"CUSIP {it.get('cusip', '?')}",
            })
        except Exception:
            continue
    return out


# ── Build the calendar dataframe ─────────────────────────────────────────
today = date.today()
events = []

# FOMC (current + projected next year)
for d in FOMC_2026 + FOMC_2027_PROJECTED:
    events.append({"date": d, "event": "FOMC decision",
                   "type": "FOMC"})

# Macro (algorithmic next 6 months)
events.extend(_macro_calendar(today, months_ahead=6))

# Auctions (TreasuryDirect)
events.extend(_fetch_auctions())

cal_df = pd.DataFrame(events)
cal_df["days_away"] = (pd.to_datetime(cal_df["date"]) - pd.Timestamp(today)).dt.days
cal_df = cal_df[cal_df["days_away"] >= 0].copy()
cal_df["tier"] = cal_df["type"].apply(_tier)
cal_df["weekday"] = pd.to_datetime(cal_df["date"]).dt.day_name().str.slice(0, 3)
cal_df = cal_df.sort_values(["date", "tier"]).reset_index(drop=True)


# ── Top: next big event ──────────────────────────────────────────────────
tier1 = cal_df[cal_df["tier"] == "Tier 1"]
if not tier1.empty:
    nxt = tier1.iloc[0]
    days = int(nxt["days_away"])
    when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
    st.markdown(
        f"<div style='background:#122340;border-left:4px solid #f87171;"
        f"padding:14px 18px;border-radius:6px;margin:8px 0 16px'>"
        f"<div style='color:#94a8c9;font-size:11px;letter-spacing:1px;"
        f"font-weight:700'>NEXT TIER-1 EVENT</div>"
        f"<div style='color:#e8eef9;font-size:22px;font-weight:700;"
        f"margin:4px 0 4px'>{nxt['event']}</div>"
        f"<div style='color:#fbbf24;font-size:14px'>"
        f"{nxt['date'].strftime('%a, %d %b %Y')}  ·  <b>{when}</b></div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ── Filters ──────────────────────────────────────────────────────────────
fc1, fc2, fc3 = st.columns(3)
with fc1:
    tier_filter = st.multiselect(
        "Filter tier",
        ["Tier 1", "Tier 2", "Tier 3"],
        default=["Tier 1", "Tier 2"],
    )
with fc2:
    type_filter = st.multiselect(
        "Filter event type",
        sorted(cal_df["type"].unique()),
        default=[],
        help="Leave empty to show all types in the selected tiers.",
    )
with fc3:
    horizon_days = st.slider("Horizon (days ahead)", 7, 180, 60,
                              help="Limit the table to the next N days.")

view = cal_df[cal_df["tier"].isin(tier_filter)]
if type_filter:
    view = view[view["type"].isin(type_filter)]
view = view[view["days_away"] <= horizon_days]


# ── Calendar table ───────────────────────────────────────────────────────
st.subheader(f"📋 Next {horizon_days} days  ({len(view)} events)")

def _row_color(t):
    return f"background-color: {TIER_COLORS.get(t, '#94a8c9')}; color: white"

display = view.assign(
    Date     = view["date"].apply(lambda d: d.strftime("%a · %d %b %Y")),
    Countdown= view["days_away"].apply(
        lambda n: "today" if n == 0 else
                  f"tomorrow" if n == 1 else
                  f"+{n}d"
    ),
).rename(columns={"event": "Event", "type": "Type", "tier": "Tier"})
display = display[["Date", "Countdown", "Tier", "Type", "Event"]]

st.dataframe(
    display.style.applymap(_row_color, subset=["Tier"]),
    use_container_width=True, hide_index=True,
)


# ── Month grid view ──────────────────────────────────────────────────────
with st.expander("🗓️ Month grid view"):
    months = sorted(set((e["date"].year, e["date"].month) for e in events
                        if (e["date"] - today).days >= 0
                        and (e["date"] - today).days <= horizon_days))
    for y, m in months[:3]:   # next 3 months only (keep page tight)
        st.markdown(f"#### {_cal.month_name[m]} {y}")
        weeks = _cal.monthcalendar(y, m)
        # Build a 7-col table of events per day
        rows = []
        for week in weeks:
            row = {}
            for i, day in enumerate(week):
                wd = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][i]
                if day == 0:
                    row[wd] = ""
                    continue
                evs = cal_df[(pd.to_datetime(cal_df["date"]).dt.year == y)
                             & (pd.to_datetime(cal_df["date"]).dt.month == m)
                             & (pd.to_datetime(cal_df["date"]).dt.day == day)]
                if evs.empty:
                    row[wd] = f"{day}"
                else:
                    badges = " · ".join(
                        f"**{t}**" for t in evs["type"].head(3)
                    )
                    row[wd] = f"**{day}**  {badges}"
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Quick callouts: Substack timing ──────────────────────────────────────
st.divider()
st.subheader("✍️ Substack timing")
nxt_t1_2 = cal_df[cal_df["tier"].isin(["Tier 1", "Tier 2"])].head(5)
ideas = []
for _, e in nxt_t1_2.iterrows():
    days = int(e["days_away"])
    if e["type"] == "FOMC":
        ideas.append(
            f"**{e['date'].strftime('%a %d %b')}** — FOMC. "
            f"Pre-meeting (T-1 to T-3) post: 'what the curve is pricing'. "
            f"Post-meeting recap (T+0 to T+1): how the curve repriced."
        )
    elif e["type"] == "NFP":
        ideas.append(
            f"**{e['date'].strftime('%a %d %b')}** — NFP. "
            f"Pre: front-end positioning + payroll-sensitive trades. "
            f"Post: fade or follow the move?"
        )
    elif e["type"] == "CPI":
        ideas.append(
            f"**{e['date'].strftime('%a %d %b')}** — CPI. "
            f"Pre: breakeven setup. Post: real-yield reaction in TIPS."
        )
    elif e["type"] == "Retail Sales":
        ideas.append(
            f"**{e['date'].strftime('%a %d %b')}** — Retail Sales. "
            f"Sets the tone for growth narrative — 5s30s reaction worth covering."
        )
    elif e["type"] == "PCE":
        ideas.append(
            f"**{e['date'].strftime('%a %d %b')}** — PCE. "
            f"Fed's preferred inflation gauge. Lower-volatility setup."
        )

for line in ideas:
    st.markdown(f"- {line}")

st.caption(
    "Tier-3 (Treasury auctions) are mechanical — usually not Substack-worthy "
    "on their own unless they tail badly or have unusual foreign demand."
)
