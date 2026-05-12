"""Social-card generator — branded 1080×1080 PNG for Instagram / X / Substack notes.

Pure matplotlib (no kaleido / streamlit deps) so this works from cron too.

Usage:
    from analysis.social_card import build_social_card
    path = build_social_card(scanner_df, hist_df, out_dir=Path("briefs/2026-05-07/social"))
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # non-interactive backend, safe in cron
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import numpy as np
import pandas as pd

# Brand palette (mirrors dashboard config.py / weekly_pdf.py)
BG       = "#0a1628"
PANEL    = "#122340"
ACCENT   = "#4fc3f7"
GREEN    = "#4ade80"
RED      = "#f87171"
TEXT1    = "#e8eef9"
TEXT2    = "#94a8c9"
TEXT3    = "#6a7e9e"


def _fmt_trade(trade: str, ttype: str) -> str:
    """'Rcv 2Y/5Y/10Y' + 'Fly' → '2Y5Y10Y fly'."""
    bare = trade.replace("Rcv ", "")
    if ttype == "Fly":
        return bare.replace("/", "") + " fly"
    if ttype == "Curve":
        return f"{bare} curve"
    return bare


def build_social_card(
    scanner_df: pd.DataFrame,
    hist_df: pd.DataFrame,
    out_dir: Path,
    sort_by: str = "Sharpe",
    top_n: int = 1,
    fmt: str = "square",
) -> Path:
    """Render the social card PNG and return its path.

    fmt: 'square' (1080×1080), 'story' (1080×1920), or 'twitter' (1200×675).
    """
    sizes = {
        "square":  (10.8, 10.8),     # 1080×1080 @ 100 dpi
        "story":   (10.8, 19.2),     # 1080×1920
        "twitter": (12.0,  6.75),    # 1200×675
    }
    figsize = sizes.get(fmt, sizes["square"])

    if scanner_df.empty:
        # Render a placeholder card
        fig = plt.figure(figsize=figsize, facecolor=BG, dpi=100)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_facecolor(BG); ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values(): s.set_visible(False)
        ax.text(0.5, 0.5, "No scanner data", ha="center", va="center",
                color=TEXT2, fontsize=24)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"social_card_{fmt}_{date.today().isoformat()}.png"
        fig.savefig(out_path, facecolor=BG, dpi=100, bbox_inches="tight")
        plt.close(fig)
        return out_path

    # ── Pick the headline trade ──────────────────────────────────────────
    sdf = scanner_df.dropna(subset=[sort_by]).copy()
    top = sdf.nlargest(top_n, sort_by) if sort_by in ("Sharpe", "E[Ret]") \
          else sdf.nsmallest(top_n, sort_by)
    best = top.iloc[0]
    trade_name = _fmt_trade(best["Trade"], best["Type"])

    # ── Layout (square) ───────────────────────────────────────────────────
    fig = plt.figure(figsize=figsize, facecolor=BG, dpi=100)
    gs = GridSpec(
        nrows=10, ncols=1, figure=fig,
        height_ratios=[1.4, 0.4, 1.4, 1.0, 0.4, 4.5, 0.6, 1.0, 0.3, 0.4],
        left=0.07, right=0.93, top=0.96, bottom=0.04, hspace=0.05,
    )

    # Brand header
    ax_brand = fig.add_subplot(gs[0])
    ax_brand.set_facecolor(BG); ax_brand.axis("off")
    ax_brand.text(0.0, 0.5, "MACRO MANV", color=ACCENT, fontsize=22,
                  fontweight="bold", va="center", ha="left",
                  family="sans-serif")
    ax_brand.text(0.0, 0.0, "Rates · Charts · Signal",
                  color=TEXT3, fontsize=12, va="center", ha="left")
    ax_brand.text(1.0, 0.5, date.today().strftime("%d %b %Y"),
                  color=TEXT2, fontsize=12, va="center", ha="right")

    # Headline label
    ax_label = fig.add_subplot(gs[2])
    ax_label.set_facecolor(BG); ax_label.axis("off")
    ax_label.text(0.0, 1.0, "TODAY'S TOP RV SIGNAL", color=TEXT3,
                  fontsize=11, fontweight="bold", ha="left", va="top")
    ax_label.text(0.0, 0.10, f"Receive {trade_name}", color=TEXT1,
                  fontsize=42, fontweight="bold", ha="left", va="bottom",
                  family="sans-serif")

    # Stats row
    ax_stats = fig.add_subplot(gs[3])
    ax_stats.set_facecolor(BG); ax_stats.axis("off")
    metrics = [
        ("SHARPE",    f"{best['Sharpe']:+.2f}",  GREEN if best["Sharpe"] > 0 else RED),
        ("Z-SCORE",   f"{best['Z']:+.2f}",       GREEN if best["Z"] < 0 else RED),
        ("E[RET]",    f"{best['E[Ret]']:+.0f}",  TEXT1),
        ("RISK",      f"{best['Risk']:.0f}",     TEXT2),
    ]
    for i, (label, val, color) in enumerate(metrics):
        x = i / len(metrics) + (1 / len(metrics)) / 2
        ax_stats.text(x, 0.7, label, color=TEXT3, fontsize=10,
                      fontweight="bold", ha="center", va="center")
        ax_stats.text(x, 0.25, val, color=color, fontsize=30,
                      fontweight="bold", ha="center", va="center",
                      family="sans-serif")

    # Curve mini-chart
    ax_chart = fig.add_subplot(gs[5])
    ax_chart.set_facecolor(PANEL)
    ALL_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
    avail = [t for t in ALL_TENORS if t in hist_df.columns]
    if avail and not hist_df.empty:
        last_row = hist_df.iloc[-1]
        wk_idx   = max(0, len(hist_df) - 6)
        mo_idx   = max(0, len(hist_df) - 22)
        wk_row   = hist_df.iloc[wk_idx]
        mo_row   = hist_df.iloc[mo_idx]

        x = np.arange(len(avail))
        ax_chart.plot(x, [mo_row[t] for t in avail],
                      color=TEXT3, linewidth=1.5, linestyle=":",  marker="o",
                      markersize=4, label="1m ago")
        ax_chart.plot(x, [wk_row[t] for t in avail],
                      color="#7dd3fc", linewidth=1.8, linestyle="--", marker="o",
                      markersize=5, label="1w ago")
        ax_chart.plot(x, [last_row[t] for t in avail],
                      color=ACCENT,  linewidth=3.0,                marker="o",
                      markersize=7, label="Today")
        ax_chart.set_xticks(x)
        ax_chart.set_xticklabels(avail, color=TEXT2, fontsize=11)
        ax_chart.tick_params(axis="y", colors=TEXT2, labelsize=11)
        ax_chart.set_ylabel("Yield (%)", color=TEXT2, fontsize=11)
        for s in ax_chart.spines.values(): s.set_color(TEXT3)
        ax_chart.grid(True, alpha=0.15, color=TEXT3)
        ax_chart.legend(loc="upper left", facecolor=PANEL, edgecolor=TEXT3,
                        labelcolor=TEXT1, fontsize=10)
        ax_chart.set_title("US Treasury yield curve",
                           color=TEXT1, fontsize=13, fontweight="bold", pad=8)

    # Footer label
    ax_foot1 = fig.add_subplot(gs[7])
    ax_foot1.set_facecolor(BG); ax_foot1.axis("off")
    type_str = best["Type"]
    z_word   = ("cheap" if best["Z"] < -0.5 else
                "rich" if best["Z"] > 0.5 else "fairly valued")
    ax_foot1.text(0.5, 0.7,
                  f"Top-ranked {type_str.lower()} on the screen — currently {z_word} "
                  f"vs 1Y history.",
                  color=TEXT2, fontsize=14, ha="center", va="center",
                  family="sans-serif", wrap=True)
    ax_foot1.text(0.5, 0.20,
                  "Receive: profit if level falls.   Pay: profit if level rises.",
                  color=TEXT3, fontsize=10, ha="center", va="center")

    # Brand footer strip
    ax_foot = fig.add_subplot(gs[9])
    ax_foot.set_facecolor(BG); ax_foot.axis("off")
    ax_foot.text(0.0, 0.5, "macromanv.substack.com",
                 color=ACCENT, fontsize=12, fontweight="bold",
                 ha="left", va="center")
    ax_foot.text(1.0, 0.5,
                 "Model estimates · Not investment advice",
                 color=TEXT3, fontsize=9, ha="right", va="center")

    # Save
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"social_card_{fmt}_{date.today().isoformat()}.png"
    fig.savefig(out_path, facecolor=BG, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return out_path
