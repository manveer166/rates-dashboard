"""
Shared alert body builder — used by both the Alerts dashboard page and
the standalone send_alert.py script so the format is always in sync.

The four-section format:
  1. HIGHEST CONVICTION RV SIGNAL  — best trade by Sharpe, data-driven narrative
  2. THEME BUILDING ACROSS THE CURVE — cross-sectional cluster read
  3. MOST STRETCHED THIS WEEK       — biggest D1W mover
  4. CHART READ | Sharpe Profile    — ASCII visual of signal breadth
"""

import re
from collections import Counter
from datetime import datetime


# ── Formatting helpers ────────────────────────────────────────────────────

def format_trade_plain(trade: str, type_: str) -> str:
    """'Rcv 2Y/5Y/30Y' + 'Fly' -> '2Y5Y30Y fly'. House style."""
    tenors_part = trade.replace("Rcv ", "")
    if type_ == "Fly":
        return tenors_part.replace("/", "") + " fly"
    if type_ == "Curve":
        return f"{tenors_part} curve"
    return tenors_part  # Outright


def trade_tenors(trade: str):
    return re.findall(r"\d+[MY]", trade)


def describe_valuation(z: float) -> str:
    if z < -2.0:  return "screens deeply cheap versus history"
    if z < -1.0:  return "still looks cheap versus history"
    if z < -0.5:  return "trades modestly below fair value"
    if z <  0.5:  return "screens broadly fair to history"
    if z <  1.0:  return "trades slightly rich to history"
    if z <  2.0:  return "looks rich versus history"
    return "is stretched rich versus history"


def derive_tags(row, *, top: bool = False, mover: bool = False):
    tags = []
    if top:    tags.append("#HighConviction")
    if mover:  tags.append("#Dislocation")
    z = float(row["Z"])
    if abs(z) > 2.0:   tags.append("#Dislocation")
    elif abs(z) > 1.0: tags.append("#Valuation")
    if z < -1.0:       tags.append("#MeanReversion")
    if row["Type"] == "Fly":   tags.append("#Fly")
    if row["Type"] == "Curve": tags.append("#Curve")
    tenors = trade_tenors(row["Trade"])
    if any(t in ("2Y", "3Y") for t in tenors):   tags.append("#FrontEnd")
    if any(t in ("5Y", "7Y") for t in tenors):   tags.append("#Belly")
    if any(t in ("20Y", "30Y") for t in tenors): tags.append("#LongEnd")
    if mover: tags.append("#ShockFade")
    # Dedupe preserving insertion order
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t); out.append(t)
    return out


def theme_summary(top_rows):
    """Identify dominant tenors + type across the top of the screen."""
    tenor_counter: Counter = Counter()
    type_counter:  Counter = Counter()
    for _, r in top_rows.iterrows():
        for t in trade_tenors(r["Trade"]):
            tenor_counter[t] += 1
        type_counter[r["Type"]] += 1
    n = len(top_rows)
    common = [t for t, c in tenor_counter.most_common() if c >= max(2, n // 2)]
    dom_type = type_counter.most_common(1)[0][0] if type_counter else ""
    return {"common": common, "dom_type": dom_type}


def ascii_sharpe_chart(top_rows, width: int = 40) -> str:
    """Vertical ASCII ranking — stars indent left→right by Sharpe strength."""
    if top_rows.empty:
        return ""
    sharpes = top_rows["Sharpe"].tolist()
    lo, hi = min(sharpes), max(sharpes)
    span = max(hi - lo, 0.01)
    lines = ["|"]
    for s in sharpes:
        pos = int(round((s - lo) / span * (width - 2)))
        lines.append("|" + " " * pos + "*")
    lines.append("|" + "_" * width)
    return "\n".join(lines)


# ── Main builder ──────────────────────────────────────────────────────────

def build_body(sdf, cfg) -> str:
    """
    Build the full four-section alert body from scanner DataFrame + config dict.

    Parameters
    ----------
    sdf : pd.DataFrame
        Scanner output — must have columns: Trade, Type, Sharpe, Z, E[Ret], Risk, D1W
    cfg : dict
        Alert config (trade_types, top_n, etc.)

    Returns
    -------
    str  — plain-text alert ready for email / Substack note
    """
    if sdf is None or sdf.empty:
        return "No scanner data available."

    filt = sdf[sdf["Type"].isin(cfg.get("trade_types", ["Outright", "Curve", "Fly"]))].copy()
    filt = filt.dropna(subset=["Sharpe"])
    if filt.empty:
        return "No scanner data available."

    date_str = datetime.now().strftime("%d %b %Y")
    top_n = cfg.get("top_n", 10)
    top   = filt.nlargest(top_n, "Sharpe")
    best  = top.iloc[0]
    best_name = format_trade_plain(best["Trade"], best["Type"])
    best_z    = float(best["Z"])

    L = [f"Rates Dashboard Alert | {date_str}", "=" * 50, ""]

    # ── 1. Highest conviction ─────────────────────────────────────────────
    L.append("HIGHEST CONVICTION RV SIGNAL")
    L.append(f"Receive {best_name}")
    L.append("Tags: " + " ".join(derive_tags(best, top=True)))
    L.append("")
    L.append(
        f"Top-ranked structure on the screen today with Sharpe {best['Sharpe']:+.2f}, "
        f"expected return {best['E[Ret]']:+.0f} bps, and risk {best['Risk']:.0f}."
    )
    L.append(
        f"The structure {describe_valuation(best_z)} (z-score {best_z:+.2f}), "
        "with supportive expected return relative to risk."
    )
    if best_z < -0.5:
        L.append("Why now: the dislocation has not fully normalised despite recent stabilisation.")
    elif best_z > 0.5:
        L.append("Why now: model signal remains elevated despite rich valuation — carry and roll are doing the work.")
    else:
        L.append("Why now: model signal is strongest here with valuation broadly in line with history.")
    L.append("Regime fit: best in a lower-vol, shock-fading environment.")
    L.append("Risk: renewed long-end selling would likely delay reversion.")
    L.append("")

    # ── 2. Theme building ─────────────────────────────────────────────────
    theme = theme_summary(top)
    theme_tags = ["#ThemeBuilding"]
    if any(t in ("2Y", "3Y") for t in theme["common"]):   theme_tags.append("#FrontEnd")
    if any(t in ("5Y", "7Y") for t in theme["common"]):   theme_tags.append("#Belly")
    if any(t in ("20Y", "30Y") for t in theme["common"]): theme_tags.append("#LongEnd")
    theme_tags.append("#ReceiverBias")
    similar = [format_trade_plain(r["Trade"], r["Type"]) for _, r in top.iloc[1:4].iterrows()]
    anchor  = "/".join(theme["common"][:2]) if theme["common"] else "the curve"

    L.append("THEME BUILDING ACROSS THE CURVE")
    L.append("Tags: " + " ".join(theme_tags))
    L.append("")
    if similar:
        L.append(
            f"Signals are clustering in {anchor}-led receiver structures, "
            f"including {', '.join(similar)}."
        )
    else:
        L.append(f"Signals are clustering around {anchor}.")
    L.append("This suggests the opportunity is thematic rather than isolated.")
    L.append("")

    # ── 3. Most stretched this week ───────────────────────────────────────
    mov_sorted = filt.reindex(filt["D1W"].abs().sort_values(ascending=False).index)
    biggest    = mov_sorted.iloc[0]
    big_name   = format_trade_plain(biggest["Trade"], biggest["Type"])
    big_z      = float(biggest["Z"])
    cheap_or_rich = (
        "meaningfully cheap" if big_z < -0.5
        else ("stretched rich" if big_z > 0.5 else "close to fair")
    )

    L.append("MOST STRETCHED THIS WEEK")
    L.append(f"Receive {big_name}")
    L.append("Tags: " + " ".join(derive_tags(biggest, mover=True)))
    L.append("")
    L.append(
        f"This has been one of the largest weekly movers on the screen "
        f"(D1W {biggest['D1W']:+.1f} bps) and now looks {cheap_or_rich} "
        f"versus history at z-score {big_z:+.2f}."
    )
    L.append("Worth monitoring for reversal if rates volatility settles.")
    L.append("")

    # ── 4. Chart read ─────────────────────────────────────────────────────
    L.append("CHART READ | Sharpe Profile")
    L.append("(Top trades ranked by signal strength)")
    L.append("")
    L.append(ascii_sharpe_chart(top, width=40))
    L.append("")
    L.append(
        "Interpretation: clear lead signal at the top with a gradual decay across "
        "the curve, supporting a broad RV theme rather than a single isolated trade."
    )
    L.append("")
    L.append("— Macro Manv Rates Dashboard")
    return "\n".join(L)
