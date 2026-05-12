"""
16_Substack_Models.py — Gated interactive models linked from Substack articles.

URL scheme (embed in each article):
    …/16_Substack_Models?model=iran_energy
    …/16_Substack_Models?model=vol_control
    …/16_Substack_Models?model=cta

Access tiers
~~~~~~~~~~~~
  1. Full dashboard user (site_admin or site_authenticated viewer with no page-lock)
     → sees all models; no article password needed
  2. Article reader who enters the correct password
     → session-unlocked for that model ONLY; cannot navigate to other models
  3. No auth / wrong password
     → model-specific gate (or neutral landing if no ?model= param)

Password rule  (computed from article_title in _MODELS, not shown to users)
     first_3_letters + last_3_letters  of title, all lowercase, letters only.
     e.g. "Iran and Energy The Barbell Trade" → "iraade"
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import PLOTLY_THEME

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_VISITS_FILE = _DATA_DIR / "substack_visits.json"


def _log_visit(model_id: str, email: str = "") -> None:
    visits = []
    if _VISITS_FILE.exists():
        try:
            visits = json.loads(_VISITS_FILE.read_text())
        except Exception:
            pass
    visits.append({
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "model_id":  model_id,
        "model_name": _MODELS[model_id]["display_name"],
        "email":     email.strip().lower() if email else "",
    })
    _DATA_DIR.mkdir(exist_ok=True)
    _VISITS_FILE.write_text(json.dumps(visits, indent=2))

st.set_page_config(
    page_title="Substack Models · Macro Manv",
    page_icon="📊",
    layout="wide",
)

# ══════════════════════════════════════════════════════════════════════════════
#  Model registry
#  article_title  ← must match the published Substack article title EXACTLY
#                   (punctuation/case ignored; only letters matter for password)
# ══════════════════════════════════════════════════════════════════════════════

_MODELS: dict = {
    "vol_control": {
        "article_title": "Volatility Control Funds How Vol Targeting Moves Two Hundred Billion",
        "display_name":  "Vol-Control Fund Flows",
        "icon":          "⚙️",
        "summary":       "EWMA vol-targeting exposure and forward flow projections across 11 global equity markets.",
    },
    "cta": {
        "article_title": "CTA Trend Machines Where Three Hundred Billion Sits After the Shock",
        "display_name":  "CTA Positioning Model",
        "icon":          "📡",
        "summary":       "Systematic trend-following momentum positioning across equities, bonds and commodities.",
    },
    "iran_energy": {
        "article_title": "Iran and Energy The Barbell Trade",
        "display_name":  "Iran & Energy: The Barbell Trade",
        "icon":          "🛢️",
        "summary":       "Regime Sharpe analysis, positioning z-scores, and call-spread Monte Carlo.",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
#  Auth helpers
# ══════════════════════════════════════════════════════════════════════════════

def _derive_pw(article_title: str) -> str:
    """Compute the article password from its title.  Never call this in UI copy."""
    letters = [c.lower() for c in article_title if c.isalpha()]
    if len(letters) < 6:
        return "".join(letters)
    return "".join(letters[:3] + letters[-3:])


def _full_access() -> bool:
    """True for site_admin or a site viewer without a page-lock."""
    if not st.session_state.get("site_authenticated"):
        return False
    lock = st.session_state.get("page_lock", "")
    return bool(st.session_state.get("site_admin")) or not lock


def _back_button() -> None:
    """Render a Back button that returns to the hub (only for non-full-access users)."""
    if not _full_access():
        if st.button("← Back", key="_back_btn"):
            st.query_params.clear()
            st.rerun()
        st.markdown("---")


def _model_unlocked(model_id: str) -> bool:
    return (
        _full_access()
        or bool(st.session_state.get("_su_master"))
        or bool(st.session_state.get(f"_su_{model_id}"))
    )


def _show_gate(model_id: str) -> bool:
    """Render the password gate.  Returns True only after a successful unlock."""
    if _model_unlocked(model_id):
        return True

    cfg = _MODELS[model_id]
    st.markdown(
        f"<div style='text-align:center;padding:60px 0 24px'>"
        f"<div style='font-size:2.8rem'>{cfg['icon']}</div>"
        f"<h2 style='margin:14px 0 6px'>{cfg['display_name']}</h2>"
        f"<p style='color:#94a8c9;max-width:460px;margin:0 auto 32px;line-height:1.6'>"
        f"{cfg['summary']}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )
    _, col, _ = st.columns([1, 1, 1])
    with col:
        email = st.text_input(
            "Email (optional)",
            key=f"_su_email_{model_id}",
            placeholder="your@email.com",
        )
        pw = st.text_input(
            "Password",
            type="password",
            key=f"_su_pw_{model_id}",
            placeholder="Enter your article password",
            label_visibility="collapsed",
        )
        if st.button("Unlock →", key=f"_su_btn_{model_id}",
                     type="primary", use_container_width=True):
            entered = pw.strip().lower()
            if entered == "manveer":
                st.session_state["_su_master"] = True
                _log_visit(model_id, email)
                st.rerun()
            elif entered == _derive_pw(cfg["article_title"]):
                st.session_state[f"_su_{model_id}"] = True
                _log_visit(model_id, email)
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  Model 1 — Iran & Energy: The Barbell Trade
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _iran_load() -> pd.DataFrame:
    import yfinance as yf
    syms = {"XLE": "XLE", "SPY": "SPY", "BRENT": "BZ=F",
            "XOP": "XOP", "GLD": "GLD"}
    frames = {}
    for name, sym in syms.items():
        try:
            raw = yf.download(sym, start="2010-01-01", progress=False, auto_adjust=True)
            if not raw.empty:
                s = raw["Close"].squeeze().dropna()
                s.index = pd.to_datetime(s.index)
                frames[name] = s
        except Exception:
            pass
    return pd.concat(frames, axis=1).dropna(how="all") if frames else pd.DataFrame()


_EVENTS = {
    "Libya (2011)":          ("2011-02-15", "2011-05-15"),
    "Saudi Abqaiq (2019)":   ("2019-09-13", "2019-10-13"),
    "Soleimani (2020)":      ("2020-01-02", "2020-01-31"),
    "Russia-Ukraine (2022)": ("2022-02-23", "2022-03-31"),
    "Israel-Hamas (2023)":   ("2023-10-06", "2023-11-06"),
    "Iran-Israel (2024)":    ("2024-04-12", "2024-05-15"),
    "Iran War (2026)":       ("2026-02-26", "2026-04-08"),
}
_EV_COLORS = ["#4fc3f7", "#a78bfa", "#fbbf24", "#ef4444",
              "#22c55e", "#f97316", "#e11d48"]


def _iran_regime(prices: pd.DataFrame) -> pd.DataFrame:
    r = prices.pct_change().dropna().copy()
    r["b30"] = prices["BRENT"].pct_change(30) if "BRENT" in prices.columns else 0
    r["b90"] = prices["BRENT"].pct_change(90) if "BRENT" in prices.columns else 0
    r["s30"] = prices["SPY"].pct_change(30)   if "SPY"   in prices.columns else 0

    def _reg(row):
        if row["b30"] > 0.15:                          return "Oil Shock"
        if row["b90"] < -0.15 and row["s30"] < -0.05: return "Demand Destruction"
        if abs(row["b90"]) < 0.10 and row["s30"] > 0: return "Soft Landing"
        return "Other"

    r["regime"] = r.apply(_reg, axis=1)
    rows = []
    for reg in ["Soft Landing", "Oil Shock", "Demand Destruction"]:
        sub = r[r["regime"] == reg]
        row: dict = {"Regime": reg, "Days": len(sub)}
        for asset in ["XLE", "SPY", "XOP", "GLD"]:
            if asset in sub.columns:
                s = sub[asset].dropna()
                if len(s) > 5:
                    row[f"{asset}"] = round(s.mean() / s.std() * np.sqrt(252), 2)
        rows.append(row)
    return pd.DataFrame(rows)


def _iran_zscore(prices: pd.DataFrame, yrs: int) -> dict[str, float]:
    cut = pd.Timestamp.now() - pd.DateOffset(years=yrs)
    p   = prices.loc[cut:].dropna(how="all")
    out: dict = {}
    if "XLE" in p.columns and "SPY" in p.columns:
        s = (p["XLE"] / p["SPY"]).dropna()
        out["XLE / SPY"] = round(float((s.iloc[-1] - s.mean()) / s.std()), 2)
    if "XOP" in p.columns and "XLE" in p.columns:
        s = (p["XOP"] / p["XLE"]).dropna()
        out["XOP / XLE"] = round(float((s.iloc[-1] - s.mean()) / s.std()), 2)
    if "XLE" in p.columns and "BRENT" in p.columns:
        xn = p["XLE"].dropna() / p["XLE"].dropna().iloc[0]
        bn = p["BRENT"].dropna() / p["BRENT"].dropna().iloc[0]
        s  = (xn / bn).dropna()
        out["XLE vs Brent"] = round(float((s.iloc[-1] - s.mean()) / s.std()), 2)
    return out


def _mc_spread(S0, K1, K2, net_debit, T, scenarios, n=25_000):
    np.random.seed(42)
    rows = []
    for name, (drift, vol, weight) in scenarios.items():
        z  = np.random.standard_normal(n)
        ST = S0 * np.exp((drift - 0.5 * vol**2) * T + vol * np.sqrt(T) * z)
        pl = np.maximum(np.minimum(ST, K2) - K1, 0) - net_debit
        rows.append({
            "Scenario":    name,
            "Weight":      weight,
            "Drift":       f"{drift:+.0%}",
            "Vol":         f"{vol:.0%}",
            "E[P&L]":      round(float(pl.mean()), 2),
            "Prob Profit": f"{(pl > 0).mean():.1%}",
            "Prob Max":    f"{(ST >= K2).mean():.1%}",
            "Sharpe":      round(float(pl.mean() / pl.std()) if pl.std() > 0 else 0, 2),
        })
    return pd.DataFrame(rows)


def _render_iran_energy():
    _back_button()
    st.markdown("## 🛢️ Iran & Energy: The Barbell Trade")
    st.caption("Macro Manv · April 2026  ·  live data via Yahoo Finance")

    with st.spinner("Loading market data…"):
        prices = _iran_load()

    if prices.empty:
        st.error("Market data unavailable — check your internet connection.")
        return

    t1, t2, t3, t4 = st.tabs([
        "📅 Geopolitical Events",
        "📊 Regime Sharpe",
        "🎯 Positioning Z-Scores",
        "⚡ Call Spread Monte Carlo",
    ])

    # ── Tab 1 ─────────────────────────────────────────────────────────────────
    with t1:
        st.markdown("#### Brent path during geopolitical shocks — indexed to 100")
        fig = go.Figure()
        for i, (name, (s0, s1)) in enumerate(_EVENTS.items()):
            if "BRENT" not in prices.columns:
                continue
            seg = prices["BRENT"].loc[s0:s1].dropna()
            if len(seg) < 3:
                continue
            norm = seg.values / seg.iloc[0] * 100
            is26 = "2026" in name
            fig.add_trace(go.Scatter(
                x=list(range(len(norm))), y=norm, mode="lines", name=name,
                line=dict(color=_EV_COLORS[i % len(_EV_COLORS)],
                          width=2.8 if is26 else 1.4),
                opacity=1.0 if is26 else 0.6,
            ))
        fig.add_hline(y=100, line=dict(color="rgba(148,168,201,0.3)", width=1, dash="dash"))
        fig.update_layout(template=PLOTLY_THEME, height=360,
                          xaxis_title="Trading days", yaxis_title="Indexed to 100",
                          legend=dict(bgcolor="rgba(0,0,0,0)", font_size=10),
                          margin=dict(l=50, r=10, t=16, b=40))
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Total return: event start → end")
        ev_rows = []
        for name, (s0, s1) in _EVENTS.items():
            row: dict = {"Event": name}
            for a in ["BRENT", "XLE", "XOP"]:
                if a not in prices.columns:
                    continue
                seg = prices[a].loc[s0:s1].dropna()
                row[a] = round((seg.iloc[-1] / seg.iloc[0] - 1) * 100, 1) if len(seg) >= 2 else None
            ev_rows.append(row)
        ev_df = pd.DataFrame(ev_rows)
        num_cols = [c for c in ["BRENT", "XLE", "XOP"] if c in ev_df.columns]
        st.dataframe(
            ev_df.style
                .format({c: lambda v: f"{v:+.1f}%" if v is not None else "—" for c in num_cols})
                .background_gradient(subset=num_cols, cmap="RdYlGn", vmin=-30, vmax=50),
            use_container_width=True, hide_index=True,
        )

    # ── Tab 2 ─────────────────────────────────────────────────────────────────
    with t2:
        st.markdown("#### Annualised Sharpe by macro regime  (2010 – present)")
        st.caption("**Oil Shock** = Brent +15% / 30d  ·  "
                   "**Soft Landing** = Brent ±10% / SPY positive  ·  "
                   "**Demand Destruction** = Brent −15% / 90d AND SPY −5%")
        reg_df = _iran_regime(prices)
        asset_cols = [c for c in reg_df.columns if c not in ("Regime", "Days")]
        _ac = {"XLE": "#f97316", "SPY": "#4fc3f7", "XOP": "#f59e0b", "GLD": "#fbbf24"}

        fig2 = go.Figure()
        for a in asset_cols:
            fig2.add_trace(go.Bar(
                name=a, x=reg_df["Regime"].tolist(), y=reg_df[a].tolist(),
                marker_color=_ac.get(a, "#94a8c9"),
                text=[f"{v:+.2f}" for v in reg_df[a]], textposition="outside",
            ))
        fig2.add_hline(y=0, line=dict(color="rgba(148,168,201,0.35)", width=1))
        fig2.update_layout(template=PLOTLY_THEME, height=360, barmode="group",
                           yaxis_title="Annualised Sharpe",
                           legend=dict(bgcolor="rgba(0,0,0,0)"),
                           margin=dict(l=50, r=10, t=16, b=40))
        st.plotly_chart(fig2, use_container_width=True)

        st.dataframe(
            reg_df.style
                .format({c: "{:+.2f}" for c in asset_cols})
                .background_gradient(subset=asset_cols, cmap="RdYlGn", vmin=-1.5, vmax=2.5),
            use_container_width=True, hide_index=True,
        )
        st.caption("Sharpe = (mean daily ret × 252) ÷ (daily vol × √252), in-regime only.")

    # ── Tab 3 ─────────────────────────────────────────────────────────────────
    with t3:
        st.markdown("#### Positioning z-scores")
        _, cw, _ = st.columns([1, 1, 3])
        with cw:
            win = st.selectbox("Window", [1, 3, 5, 10], index=2,
                               format_func=lambda x: f"{x}-year", key="_iz_win")
        zs = _iran_zscore(prices, win)
        if zs:
            fig3 = go.Figure()
            for lbl, val in zs.items():
                c = "#22c55e" if val < -1 else "#ef4444" if val > 1 else "#f97316"
                fig3.add_trace(go.Bar(
                    x=[lbl], y=[val], name=lbl, marker_color=c,
                    text=[f"{val:+.2f}"], textposition="outside", showlegend=False,
                ))
            for yv, col in [(1, "rgba(239,68,68,0.4)"), (-1, "rgba(34,197,94,0.4)")]:
                fig3.add_hline(y=yv, line=dict(color=col, width=1, dash="dot"))
            fig3.add_hline(y=0, line=dict(color="rgba(148,168,201,0.3)", width=1))
            fig3.update_layout(template=PLOTLY_THEME, height=280,
                               yaxis_title=f"Z-score ({win}Y)",
                               margin=dict(l=50, r=10, t=16, b=40))
            st.plotly_chart(fig3, use_container_width=True)

        st.markdown("#### XLE vs Brent — rebased to 100 at window start")
        cut = pd.Timestamp.now() - pd.DateOffset(years=win)
        if "XLE" in prices.columns and "BRENT" in prices.columns:
            ps = prices.loc[cut:].dropna(how="all")
            xl  = ps["XLE"].dropna();   xl  = xl  / xl.iloc[0]  * 100
            br  = ps["BRENT"].dropna(); br  = br  / br.iloc[0]  * 100
            fig4 = go.Figure()
            fig4.add_trace(go.Scatter(x=xl.index, y=xl,  name="XLE",
                                      line=dict(color="#f97316", width=1.8)))
            fig4.add_trace(go.Scatter(x=br.index, y=br,  name="Brent",
                                      line=dict(color="#4fc3f7", width=1.8)))
            fig4.update_layout(template=PLOTLY_THEME, height=300,
                               yaxis_title="Indexed to 100",
                               legend=dict(bgcolor="rgba(0,0,0,0)"),
                               margin=dict(l=50, r=10, t=10, b=40))
            st.plotly_chart(fig4, use_container_width=True)
        st.caption("**Negative z** = cheap vs window mean · **Positive z** = rich. "
                   "±1σ dotted lines.")

    # ── Tab 4 ─────────────────────────────────────────────────────────────────
    with t4:
        st.markdown("#### XLE call spread — Jan 2027 $65 / $75")

        spot_live = float(prices["XLE"].dropna().iloc[-1]) if "XLE" in prices.columns else 56.54
        cA, cB, cC = st.columns(3)
        with cA:
            S0 = st.number_input("XLE spot ($)", value=round(spot_live, 2),
                                 step=0.01, key="_mc_S0")
            K1 = st.number_input("Long strike",  value=65.0, step=1.0, key="_mc_K1")
        with cB:
            K2        = st.number_input("Short strike", value=75.0, step=1.0, key="_mc_K2")
            net_debit = st.number_input("Net debit ($)", value=2.40, step=0.05, key="_mc_nd")
        with cC:
            T_mo  = st.number_input("Months to expiry", value=9, step=1, key="_mc_T")
            r_rf  = st.number_input("Risk-free rate (%)", value=4.2, step=0.1, key="_mc_rf") / 100

        T = T_mo / 12.0
        st.markdown("**Scenario inputs** — drift, vol, scenario weight:")
        sc_names = ["Base (range-bound)", "Growth acceleration", "Hormuz redux", "Demand destruction"]
        sc_defs  = [(2, 28, 40), (12, 26, 20), (25, 40, 25), (-15, 35, 15)]
        sc_cols  = st.columns(4)
        scenarios: dict = {}
        for i, (name, (d0, v0, p0)) in enumerate(zip(sc_names, sc_defs)):
            with sc_cols[i]:
                st.caption(f"**{name}**")
                d = st.slider("Drift %",  -30, 50, d0, 1, key=f"_sc_d{i}") / 100
                v = st.slider("Vol %",     10, 80, v0, 1, key=f"_sc_v{i}") / 100
                p = st.slider("Weight %",   0,100, p0, 5, key=f"_sc_p{i}")
                scenarios[name] = (d, v, p)

        # Normalise weights
        tot_w = sum(w for _, _, w in scenarios.values()) or 1
        sc_norm = {k: (d, v, p / tot_w) for k, (d, v, p) in scenarios.items()}

        # Payoff diagram
        ST_r = np.linspace(max(30.0, S0 * 0.45), S0 * 1.85, 400)
        pl_r = np.maximum(np.minimum(ST_r, K2) - K1, 0) - net_debit
        figp = go.Figure()
        figp.add_trace(go.Scatter(
            x=ST_r, y=pl_r * 100, name="P&L / contract",
            line=dict(color="#4fc3f7", width=2.2),
            fill="tozeroy", fillcolor="rgba(79,195,247,0.07)",
        ))
        for xv, col, lbl in [
            (S0,          "#94a8c9", f"Spot ${S0:.2f}"),
            (K1+net_debit,"#22c55e", f"BE ${K1+net_debit:.2f}"),
        ]:
            figp.add_vline(x=xv, line=dict(color=col, width=1.2, dash="dot"),
                           annotation_text=lbl, annotation_position="top right")
        figp.add_hline(y=0, line=dict(color="rgba(148,168,201,0.25)", width=1))
        figp.update_layout(template=PLOTLY_THEME, height=280,
                           xaxis_title="XLE at expiry ($)", yaxis_title="P&L / contract ($)",
                           margin=dict(l=50, r=10, t=20, b=40))
        st.plotly_chart(figp, use_container_width=True)

        mc = _mc_spread(S0, K1, K2, net_debit, T, sc_norm)
        disp = mc[["Scenario", "Drift", "Vol", "E[P&L]", "Prob Profit", "Prob Max", "Sharpe"]].copy()
        disp["Weight"] = mc["Weight"].map(lambda w: f"{w:.0%}")
        st.dataframe(
            disp.style
                .background_gradient(subset=["E[P&L]"], cmap="RdYlGn",
                                     vmin=-net_debit, vmax=K2 - K1 - net_debit)
                .background_gradient(subset=["Sharpe"], cmap="RdYlGn", vmin=-1, vmax=2),
            use_container_width=True, hide_index=True,
        )
        ev_blend = float((mc["E[P&L]"] * mc["Weight"]).sum())
        c = "#22c55e" if ev_blend > 0 else "#ef4444"
        st.markdown(
            f"Blended EV: **<span style='color:{c}'>${ev_blend:.2f}</span>** per spread  ·  "
            f"max loss **${net_debit:.2f}**  ·  max profit **${K2-K1-net_debit:.2f}**  ·  "
            f"payoff ratio **{(K2-K1-net_debit)/net_debit:.1f}×**",
            unsafe_allow_html=True,
        )
        st.caption("50,000-path GBM per scenario. Probabilities are model outputs under stated "
                   "assumptions, not forecasts. Past regime performance ≠ forward returns.")


# ══════════════════════════════════════════════════════════════════════════════
#  Model 2 — Vol-Control Fund Flows
# ══════════════════════════════════════════════════════════════════════════════

def _render_vol_control():
    _back_button()
    st.markdown("## ⚙️ Vol-Control Fund Flows")
    st.caption("EWMA vol-targeting exposure and forward scenario flows across 11 global equity markets.")

    try:
        from analysis.vol_control import (
            MARKETS, load_market_prices, load_sp500,
            ewma_vol_series, vol_used_series, exposure_series, build_flows_table,
        )
    except ImportError as e:
        st.error(f"Could not load vol-control module: {e}")
        return

    cA, cB, cC = st.columns(3)
    with cA:
        target_vol = st.slider("Target vol (%)", 5, 25, 12, 1, key="_vc_tv") / 100
    with cB:
        total_aum_bn = st.slider("Universe AUM ($bn)", 50, 500, 200, 10, key="_vc_aum")
    with cC:
        lambda_30 = st.slider("λ 30d", 0.90, 0.97, 0.94, 0.01, key="_vc_l30")

    total_aum  = total_aum_bn * 1e9
    lambda_90  = 0.97

    with st.spinner("Loading equity index data…"):
        mkt_prices = load_market_prices()
        sp_prices  = load_sp500()

    if sp_prices.empty:
        st.error("Could not load S&P 500 data.")
        return

    sp_rets = np.log(sp_prices / sp_prices.shift(1)).dropna()
    v30 = ewma_vol_series(sp_rets, lambda_30)
    v90 = ewma_vol_series(sp_rets, lambda_90)
    vu  = vol_used_series(v30, v90)
    exp = exposure_series(vu, target_vol)

    lookback = sp_rets.index[-252 * 3] if len(sp_rets) > 252 * 3 else sp_rets.index[0]
    m = sp_rets.index >= lookback

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.06, row_heights=[0.55, 0.45])
    fig.add_trace(go.Scatter(x=v30.index[m], y=v30.values[m] * 100, name="EWMA vol 30d",
                             line=dict(color="#4fc3f7", width=1.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=v90.index[m], y=v90.values[m] * 100, name="EWMA vol 90d",
                             line=dict(color="#94a8c9", width=1.2, dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=vu.index[m], y=vu.values[m] * 100, name="Vol used (max)",
                             line=dict(color="#f97316", width=1.8)), row=1, col=1)
    fig.add_hline(y=target_vol * 100, row=1, col=1,
                  line=dict(color="rgba(148,168,201,0.35)", width=1, dash="dash"))
    fig.add_trace(go.Scatter(x=exp.index[m], y=exp.values[m] * 100, name="Equity exposure",
                             line=dict(color="#22c55e", width=1.8),
                             fill="tozeroy", fillcolor="rgba(34,197,94,0.07)"), row=2, col=1)
    fig.add_hline(y=100, row=2, col=1, line=dict(color="rgba(148,168,201,0.25)", width=1, dash="dot"))
    fig.update_layout(template=PLOTLY_THEME, height=460,
                      yaxis=dict(title="Ann. vol (%)"),
                      yaxis2=dict(title="Equity exposure (%)"),
                      legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", y=1.03),
                      margin=dict(l=55, r=10, t=30, b=40))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### 5-day scenario flows  ($MM)")
    mkt_weights = {k: v[1] for k, v in MARKETS.items()}
    flows = build_flows_table(mkt_prices, mkt_weights, total_aum,
                              target_vol, lambda_30, lambda_90)
    if not flows.empty:
        st.dataframe(
            flows.style.background_gradient(cmap="RdYlGn", vmin=-5_000, vmax=5_000, axis=None)
                       .format("{:,.0f}", subset=flows.select_dtypes("number").columns),
            use_container_width=True,
        )
        st.caption("**Flat** = vol drift zero · **Up +2σ** = risk-off · "
                   "**Down −2.5σ** = crash · **Last Week/Month** = realised flows")
    else:
        st.info("Insufficient data for scenario flows.")


# ══════════════════════════════════════════════════════════════════════════════
#  Model 3 — CTA Positioning
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _cta_load() -> pd.DataFrame:
    import yfinance as yf
    syms = {
        "S&P 500":    "^GSPC", "Nasdaq 100": "^NDX",
        "Euro Stoxx": "^STOXX50E", "TOPIX":  "^N225",
        "Gold":       "GC=F",  "Brent":      "BZ=F",
        "10Y UST":    "^TNX",  "DXY":        "DX-Y.NYB",
        "Copper":     "HG=F",
    }
    frames = {}
    for name, sym in syms.items():
        try:
            raw = yf.download(sym, start="2021-01-01", progress=False, auto_adjust=True)
            if not raw.empty:
                frames[name] = raw["Close"].squeeze().dropna()
        except Exception:
            pass
    return pd.concat(frames, axis=1).dropna(how="all") if frames else pd.DataFrame()


def _render_cta():
    _back_button()
    st.markdown("## 📡 CTA Positioning Model")
    st.caption("Trend-following momentum signals across equities, bonds, FX and commodities.")

    with st.spinner("Loading CTA data…"):
        px = _cta_load()

    if px.empty:
        st.error("Could not load CTA model data.")
        return

    fast_d = st.slider("Fast window (days)", 10, 60, 21, 1, key="_cta_fast")
    slow_d = st.slider("Slow window (days)", 60, 250, 126, 5, key="_cta_slow")

    rows = []
    for mkt in px.columns:
        s = px[mkt].dropna()
        if len(s) < slow_d + 10:
            continue
        fast_ma = s.rolling(fast_d).mean().iloc[-1]
        slow_ma = s.rolling(slow_d).mean().iloc[-1]
        trend_z = (fast_ma - slow_ma) / (s.rolling(slow_d).std().iloc[-1] or 1)

        rets = s.pct_change().dropna()
        sharpe_63 = float(rets.tail(63).mean() / rets.tail(63).std() * np.sqrt(252)) if len(rets) >= 63 else 0

        signal = "📈 Long" if trend_z > 0.5 else ("📉 Short" if trend_z < -0.5 else "⏸️ Flat")

        rows.append({
            "Market":     mkt,
            "Signal":     signal,
            "Trend Z":    round(float(trend_z), 2),
            "1M %":       round(float(s.iloc[-1] / s.iloc[-21] - 1) * 100, 1) if len(s) > 21 else None,
            "3M %":       round(float(s.iloc[-1] / s.iloc[-63] - 1) * 100, 1) if len(s) > 63 else None,
            "12M %":      round(float(s.iloc[-1] / s.iloc[-252] - 1) * 100, 1) if len(s) > 252 else None,
            "Sharpe 63d": round(sharpe_63, 2),
        })

    if not rows:
        st.info("Insufficient data for CTA signals.")
        return

    df = pd.DataFrame(rows)
    num = [c for c in ["Trend Z", "1M %", "3M %", "12M %", "Sharpe 63d"] if c in df.columns]

    st.dataframe(
        df.style
            .background_gradient(subset=[c for c in num if "%" in c or "Trend" in c or "Sharpe" in c],
                                  cmap="RdYlGn", vmin=-20, vmax=20)
            .format({c: "{:+.2f}" for c in ["Trend Z", "Sharpe 63d"]}),
        use_container_width=True, height=340, hide_index=True,
    )

    # Trend Z bar chart
    df_s = df.sort_values("Trend Z")
    fig = go.Figure(go.Bar(
        x=df_s["Market"], y=df_s["Trend Z"],
        marker_color=["#22c55e" if v > 0.5 else "#ef4444" if v < -0.5 else "#94a8c9"
                      for v in df_s["Trend Z"]],
        text=[f"{v:+.2f}" for v in df_s["Trend Z"]], textposition="outside",
    ))
    fig.add_hline(y=0, line=dict(color="rgba(148,168,201,0.3)", width=1))
    for yv, col in [(0.5, "rgba(34,197,94,0.3)"), (-0.5, "rgba(239,68,68,0.3)")]:
        fig.add_hline(y=yv, line=dict(color=col, width=1, dash="dot"))
    fig.update_layout(template=PLOTLY_THEME, height=300,
                      yaxis_title=f"Trend Z  ({fast_d}d vs {slow_d}d MA)",
                      margin=dict(l=50, r=10, t=16, b=40))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Trend Z = (MA{fast_d} − MA{slow_d}) ÷ {slow_d}d σ. "
               "Long >+0.5σ · Short <−0.5σ · Flat otherwise.")


# ══════════════════════════════════════════════════════════════════════════════
#  Renderer dispatch
# ══════════════════════════════════════════════════════════════════════════════

_RENDERERS = {
    "vol_control":  _render_vol_control,
    "cta":          _render_cta,
    "iran_energy":  _render_iran_energy,
}

# ══════════════════════════════════════════════════════════════════════════════
#  Main routing
# ══════════════════════════════════════════════════════════════════════════════

model_id: str = st.query_params.get("model", "").strip().lower()

# ── Full dashboard access ─────────────────────────────────────────────────────
if _full_access():
    try:
        from dashboard.state import init_session_state
        from dashboard.components.controls import render_sidebar_controls
        from dashboard.components.header import render_page_header
        init_session_state()
        render_sidebar_controls()
        render_page_header(current="Substack Models")
    except Exception:
        pass

    if model_id in _RENDERERS:
        _RENDERERS[model_id]()
    else:
        st.title("📊 Substack Models")
        st.caption("Interactive models published alongside Macro Manv Substack articles.")
        st.divider()
        for mid, cfg in _MODELS.items():
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**{cfg['icon']} {cfg['display_name']}**  \n{cfg['summary']}")
            with c2:
                st.markdown("")
                if st.button("Open →", key=f"_hub_{mid}", use_container_width=True):
                    st.query_params["model"] = mid
                    st.rerun()
            st.divider()
        if st.session_state.get("site_admin"):
            with st.expander("ℹ️ How to link a Substack article to a model"):
                st.markdown(
                    "Add `?model=<id>` to this page URL in your article:  \n"
                    "`…/16_Substack_Models?model=iran_energy`  \n"
                    "`…/16_Substack_Models?model=vol_control`  \n"
                    "`…/16_Substack_Models?model=cta`  \n\n"
                    "The password is derived automatically from the `article_title` field in the "
                    "`_MODELS` registry at the top of this file — keep it identical to the published title."
                )

# ── Article reader — model param present ─────────────────────────────────────
elif model_id in _MODELS:
    if _model_unlocked(model_id):
        _RENDERERS[model_id]()
        st.divider()
        st.caption("Macro Manv · macroManv.substack.com")
    else:
        _show_gate(model_id)

# ── No model param, not authenticated — neutral landing ───────────────────────
else:
    st.markdown(
        "<div style='text-align:center;padding:80px 0 24px'>"
        "<div style='font-size:3rem'>📊</div>"
        "<h1 style='margin:18px 0 8px'>Macro Manv · Substack Models</h1>"
        "<p style='color:#94a8c9;max-width:480px;margin:0 auto 36px;line-height:1.6'>"
        "Interactive models from Macro Manv articles on Substack.  "
        "Use the link in your article to access the model."
        "</p></div>",
        unsafe_allow_html=True,
    )
    st.divider()
    _, col, _ = st.columns([1, 2, 1])
    with col:
        for cfg in _MODELS.values():
            st.markdown(f"**{cfg['icon']} {cfg['display_name']}**")
            st.caption(cfg["summary"])
            st.markdown("&nbsp;")
    st.divider()
    st.caption("Macro Manv · macroManv.substack.com")
