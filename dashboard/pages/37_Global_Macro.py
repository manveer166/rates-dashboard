"""Page 37 — Global Macro Tracker.

Two things our regular curve pipeline doesn't have:

  1. OECD Composite Leading Indicators — leading recession-probability proxy
     across G7 countries; published monthly with about a 4-6 week lag.

  2. JOLTS — Job Openings/Quits/Layoffs from BLS; Fed-watched, more granular
     than the headline NFP we already track.

Both pulled direct from FRED (no API key needed) — OECD CLI series are
mirrored on FRED under the {ISO3}LOLITONOSTSAM pattern.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import PLOTLY_THEME
from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import init_session_state, password_gate

st.set_page_config(page_title="Global Macro", page_icon="🌐", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Global Macro")

st.title("🌐 Global Macro Tracker")
st.caption(
    "OECD leading indicators across G7 + JOLTS labour data, via FRED's "
    "OECD mirrors. Things our regular curve pipeline doesn't cover directly."
)
st.divider()


# OECD uses its own country codes — map from friendly labels.
OECD_COUNTRIES = {
    "United States":  "united_states",
    "United Kingdom": "united_kingdom",
    "Germany":        "germany",
    "France":         "france",
    "Italy":          "italy",
    "Japan":          "japan",
    "China":          "china",
    "India":          "india",
    "Canada":         "canada",
    "G7 aggregate":   "g7",
    "G20 aggregate":  "g20",
    "Europe-4 (FR/DE/IT/UK)": "europe4",
    "Asia-5":         "asia5",
}


@st.cache_data(ttl=24 * 3600, show_spinner="Pulling OECD CLI via FRED…")
def _fetch_cli(countries_csv: str, years: int) -> pd.DataFrame:
    from data.openbb_data import oecd_cli
    start = (datetime.today() - timedelta(days=years * 365)).strftime("%Y-%m-%d")
    return oecd_cli(tuple(countries_csv.split(",")), start=start)


@st.cache_data(ttl=24 * 3600, show_spinner="Pulling JOLTS via FRED…")
def _fetch_jolts(years: int) -> pd.DataFrame:
    """JOLTS via FRED (no key)."""
    import warnings; warnings.filterwarnings("ignore")
    import pandas_datareader.data as web
    start = datetime.today() - timedelta(days=years * 365)
    end = datetime.today()
    frames = []
    for sid, label in [("JTSJOL", "Job openings (thousands)"),
                        ("JTSQUR", "Quits rate (%)"),
                        ("JTSLDR", "Layoffs rate (%)")]:
        try:
            s = web.DataReader(sid, "fred", start, end).squeeze()
            s.name = sid
            frames.append(s)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, axis=1).dropna(how="all")
    df.index.name = "date"
    # Reshape to long form so existing render code works
    return df.reset_index().melt(id_vars="date", var_name="symbol",
                                  value_name="value").set_index("date").dropna()


# ── OECD Composite Leading Indicator ─────────────────────────────────────
st.subheader("📈 OECD Composite Leading Indicator")
st.caption(
    "**Read:** 100 = trend; below 100 = below-trend growth (recession risk); "
    "rising = improving outlook. Built from yield curves, ISM, building permits, "
    "and consumer confidence across each country."
)

labels = st.multiselect(
    "Countries / aggregates",
    list(OECD_COUNTRIES.keys()),
    default=["United States", "Germany", "G7 aggregate"],
)
years_back = st.slider("Years of history", 2, 15, 5, key="cli_years")

country_codes = [OECD_COUNTRIES[l] for l in labels] if labels else ["united_states"]
cli = _fetch_cli(",".join(country_codes), years_back)

if cli.empty:
    st.warning(
        "OECD CLI unavailable right now (FRED upstream issue or rate limit). "
        "Retry in a few minutes."
    )
else:
    # Wrapper returns long-form: date | country | value
    if "country" in cli.columns and "value" in cli.columns:
        fig = go.Figure()
        palette = ["#4fc3f7", "#a78bfa", "#fb923c", "#4ade80", "#f472b6", "#fbbf24", "#f87171"]
        for i, c in enumerate(sorted(cli["country"].unique())):
            sub = cli[cli["country"] == c].sort_index()
            fig.add_trace(go.Scatter(
                x=sub.index, y=sub["value"], name=c,
                line=dict(color=palette[i % len(palette)], width=2),
            ))
        fig.add_hline(y=100, line_dash="dash", line_color="#94a8c9",
                       annotation_text="Trend = 100",
                       annotation_position="right")
        fig.update_layout(template=PLOTLY_THEME, height=420,
                          margin=dict(l=10, r=10, t=10, b=10),
                          hovermode="x unified",
                          yaxis_title="CLI level (100 = trend)",
                          legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                      xanchor="right", x=1))
        st.plotly_chart(fig, use_container_width=True)

        # Latest values + 6m change as a snapshot
        st.markdown("**📍 Latest snapshot**")
        snap_rows = []
        for c in sorted(cli["country"].unique()):
            sub = cli[cli["country"] == c].sort_index()
            last = sub.iloc[-1] if not sub.empty else None
            if last is None: continue
            six_idx = max(0, len(sub) - 6)
            chg_6m = float(sub.iloc[-1]["value"] - sub.iloc[six_idx]["value"]) if len(sub) > 6 else None
            snap_rows.append({
                "Country":     c,
                "Latest CLI":  round(float(last["value"]), 2),
                "vs Trend":    round(float(last["value"]) - 100, 2),
                "Δ 6m":        round(chg_6m, 2) if chg_6m is not None else None,
                "Date":        sub.index[-1].strftime("%Y-%m"),
            })
        st.dataframe(pd.DataFrame(snap_rows).set_index("Country"),
                      use_container_width=True)
    else:
        st.dataframe(cli, use_container_width=True)

st.divider()

# ── JOLTS Labour Indicators ──────────────────────────────────────────────
st.subheader("👷 JOLTS — Job Openings, Quits, Layoffs")
st.caption(
    "The Fed's preferred labour-market gauges beyond NFP. **Openings/Unemployed "
    "ratio** is the signal Powell quotes most often (above ~1.5 = tight market)."
)

jolts = _fetch_jolts(5)
if jolts.empty:
    st.warning("JOLTS unavailable right now (FRED returned no data).")
else:
    # FRED returns long-form with symbol column
    if "symbol" in jolts.columns and "value" in jolts.columns:
        labels = {
            "JTSJOL": ("Job openings (thousands)", "#4fc3f7"),
            "JTSQUR": ("Quits rate (%)",            "#fb923c"),
            "JTSLDR": ("Layoffs rate (%)",          "#f87171"),
        }
        fig2 = make_subplots(rows=3, cols=1, shared_xaxes=True,
                              vertical_spacing=0.05,
                              subplot_titles=tuple(v[0] for v in labels.values()))
        row = 1
        for sid, (lbl, color) in labels.items():
            sub = jolts[jolts["symbol"] == sid].sort_index()
            if sub.empty: continue
            fig2.add_trace(go.Scatter(
                x=sub.index, y=sub["value"], name=lbl,
                line=dict(color=color, width=2), showlegend=False),
                row=row, col=1)
            row += 1
        fig2.update_layout(template=PLOTLY_THEME, height=520,
                            margin=dict(l=10, r=10, t=40, b=10),
                            hovermode="x unified")
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.dataframe(jolts, use_container_width=True)

st.divider()
st.caption(
    "Data via FRED (Federal Reserve Economic Data) — OECD series are mirrored "
    "there for free. Cached for 24h — typical first load is ~2-3s."
)
