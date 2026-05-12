"""
Generate a branded PDF for the Monday setup or Friday recap alert.

  Monday  → "Rates Weekly — Setup"   curve state, top signals, key watch-outs
  Friday  → "Rates Weekly — Recap"   what moved, signal scorecard, weekly PnL

Both share the same header/footer/table renderer.

Usage:
    from analysis.weekly_pdf import build_weekly_pdf
    path = build_weekly_pdf(scanner_df, curve_df, cfg)   # returns Path
"""

from __future__ import annotations

import io
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ── ReportLab imports ─────────────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import KeepTogether
from reportlab.lib.utils import ImageReader

# ── Logo paths ────────────────────────────────────────────────────────────
_LOGO_PATH        = Path(__file__).parent.parent / "assets" / "mm_logo.png"
_LOGO_SIGNAL_PATH = Path(__file__).parent.parent / "assets" / "mm_logo_signal.png"

# ── Brand palette ─────────────────────────────────────────────────────────
C_BG        = colors.HexColor("#0a1628")
C_PANEL     = colors.HexColor("#122340")
C_PANEL2    = colors.HexColor("#1a3056")
C_ACCENT    = colors.HexColor("#4fc3f7")
C_TEXT1     = colors.HexColor("#e8eef9")
C_TEXT2     = colors.HexColor("#94a8c9")
C_TEXT3     = colors.HexColor("#6a7e9e")
C_GREEN     = colors.HexColor("#4ade80")
C_GREEN_D   = colors.HexColor("#166534")
C_GREEN_L   = colors.HexColor("#bbf7d0")
C_RED       = colors.HexColor("#f87171")
C_RED_D     = colors.HexColor("#7f1d1d")
C_RED_L     = colors.HexColor("#fecaca")
C_ORANGE    = colors.HexColor("#fb923c")
C_YELLOW    = colors.HexColor("#fbbf24")
C_WHITE     = colors.white
C_DIVIDER   = colors.HexColor("#233e6e")

PAGE_W, PAGE_H = A4

# ── Helpers ───────────────────────────────────────────────────────────────

def _monday_of_week(dt: Optional[date] = None) -> date:
    d = dt or date.today()
    return d - timedelta(days=d.weekday())


def _is_friday(dt: Optional[date] = None) -> bool:
    return (dt or date.today()).weekday() == 4


def _z_color(z: float) -> colors.Color:
    """Heatmap: red (rich >+2) → white (0) → green (cheap <-2)."""
    if pd.isna(z):
        return C_PANEL
    if z > 2.0:   return C_RED_D
    if z > 1.0:   return colors.HexColor("#7f1d1d")
    if z > 0.5:   return colors.HexColor("#431407")
    if z < -2.0:  return C_GREEN_D
    if z < -1.0:  return colors.HexColor("#14532d")
    if z < -0.5:  return colors.HexColor("#052e16")
    return C_PANEL


def _z_text_color(z: float) -> colors.Color:
    if pd.isna(z): return C_TEXT2
    if abs(z) > 1.0: return C_WHITE
    return C_TEXT1


def _sharpe_color(s: float) -> colors.Color:
    if pd.isna(s): return C_PANEL
    if s > 1.0:  return C_GREEN_D
    if s > 0.5:  return colors.HexColor("#14532d")
    if s > 0.0:  return colors.HexColor("#052e16")
    if s < -0.5: return C_RED_D
    return colors.HexColor("#3a1010")


def _move_color(v: float) -> colors.Color:
    if pd.isna(v): return C_PANEL
    if v > 20:   return C_GREEN_D
    if v > 5:    return colors.HexColor("#052e16")
    if v < -20:  return C_RED_D
    if v < -5:   return colors.HexColor("#3a1010")
    return C_PANEL


# ── Styles ────────────────────────────────────────────────────────────────

def _make_styles():
    base = getSampleStyleSheet()
    def ps(name, **kw) -> ParagraphStyle:
        defaults = dict(fontName="Helvetica", textColor=C_TEXT1,
                        backColor=None, spaceAfter=0, spaceBefore=0)
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)
    return {
        "title":    ps("title",    fontSize=22, fontName="Helvetica-Bold",
                       textColor=C_TEXT1, alignment=TA_LEFT),
        "subtitle": ps("subtitle", fontSize=12, textColor=C_TEXT2, alignment=TA_LEFT),
        "section":  ps("section",  fontSize=11, fontName="Helvetica-Bold",
                       textColor=C_ACCENT, spaceBefore=8),
        "body":     ps("body",     fontSize=9,  textColor=C_TEXT1, leading=14),
        "caption":  ps("caption",  fontSize=8,  textColor=C_TEXT2, leading=12),
        "tag":      ps("tag",      fontSize=7.5, textColor=C_ACCENT),
        "footer":   ps("footer",   fontSize=7.5, textColor=C_TEXT3, alignment=TA_CENTER),
        "mono":     ps("mono",     fontName="Courier", fontSize=8, textColor=C_TEXT1, leading=11),
    }




# ── Editorial annotation helpers ─────────────────────────────────────────────

_CONTENT_W = 170 * mm     # usable content width inside page margins


def _note_flowables(text: str) -> list:
    """Accent-bordered italic note — prepended to a section.  Returns [] if empty."""
    if not text or not text.strip():
        return []
    note_s = ParagraphStyle(
        "_nf_style", fontName="Helvetica-Oblique", fontSize=9,
        textColor=C_ACCENT, leading=13,
    )
    tbl = Table([[Paragraph(f"✏️ &nbsp;{text.strip()}", note_s)]], colWidths=[_CONTENT_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0), colors.HexColor("#0e1f3a")),
        ("BOX",           (0, 0), (0, 0), 0.8, C_ACCENT),
        ("LEFTPADDING",   (0, 0), (0, 0), 8),
        ("RIGHTPADDING",  (0, 0), (0, 0), 8),
        ("TOPPADDING",    (0, 0), (0, 0), 5),
        ("BOTTOMPADDING", (0, 0), (0, 0), 5),
    ]))
    return [tbl, Spacer(1, 2 * mm)]


def _comment_flowables(text: str) -> list:
    """Green-bordered personal comment block — sits right below the cover header."""
    if not text or not text.strip():
        return []
    label_s = ParagraphStyle(
        "_cf_label", fontName="Helvetica-Bold", fontSize=7.5,
        textColor=C_GREEN, leading=11,
    )
    body_s = ParagraphStyle(
        "_cf_body", fontName="Helvetica", fontSize=10,
        textColor=C_TEXT1, leading=15,
    )
    tbl = Table(
        [
            [Paragraph("✏️  Personal note from Macro Manv", label_s)],
            [Paragraph(text.strip(), body_s)],
        ],
        colWidths=[_CONTENT_W],
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#061a0e")),
        ("BOX",           (0, 0), (-1, -1), 1.2, C_GREEN),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (0,  0),  7),
        ("BOTTOMPADDING", (0, 0), (0,  0),  3),
        ("TOPPADDING",    (0, 1), (0,  1),  3),
        ("BOTTOMPADDING", (0, 1), (0,  1),  9),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.5, C_GREEN),
    ]))
    return [tbl, Spacer(1, 5 * mm)]

# ── Page template ──────────────────────────────────────────────────────────

class _MMDoc(BaseDocTemplate):
    def __init__(self, path: str, title: str, subtitle: str):
        super().__init__(
            path,
            pagesize=A4,
            rightMargin=18*mm, leftMargin=18*mm,
            topMargin=22*mm, bottomMargin=20*mm,
        )
        self._title    = title
        self._subtitle = subtitle
        self._build_templates()

    def _build_templates(self):
        frame = Frame(
            self.leftMargin, self.bottomMargin,
            PAGE_W - self.leftMargin - self.rightMargin,
            PAGE_H - self.topMargin   - self.bottomMargin,
            id="main",
        )
        self.addPageTemplates([PageTemplate(id="main", frames=frame,
                                            onPage=self._draw_page)])

    def _draw_page(self, canvas, doc):
        canvas.saveState()
        # Dark background
        canvas.setFillColor(C_BG)
        canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        # Header bar
        canvas.setFillColor(C_PANEL)
        canvas.rect(0, PAGE_H - 18*mm, PAGE_W, 18*mm, stroke=0, fill=1)
        # Accent strip
        canvas.setFillColor(C_ACCENT)
        canvas.rect(0, PAGE_H - 18*mm, 3*mm, 18*mm, stroke=0, fill=1)
        # Title text
        canvas.setFillColor(C_TEXT1)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawString(8*mm, PAGE_H - 11*mm, self._title)
        canvas.setFillColor(C_TEXT2)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(8*mm, PAGE_H - 16*mm, self._subtitle)
        # Logo — top-right corner of header
        if _LOGO_PATH.exists():
            logo_h = 11 * mm          # slightly smaller to sit cleanly in 18mm bar
            logo_w = logo_h * (504 / 409)   # preserve aspect (504×409 px)
            logo_x = PAGE_W - 18*mm - logo_w
            logo_y = PAGE_H - 18*mm + 3.5*mm   # vertically centred in bar
            canvas.drawImage(
                str(_LOGO_PATH),
                logo_x, logo_y,
                width=logo_w, height=logo_h,
                preserveAspectRatio=True,
                mask="auto",
            )
        # Footer
        canvas.setFillColor(C_DIVIDER)
        canvas.rect(0, 12*mm, PAGE_W, 0.3*mm, stroke=0, fill=1)
        canvas.setFillColor(C_TEXT3)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(18*mm, 7*mm,
            "Macro Manv Rates Dashboard · Model estimates only · Not investment advice")
        canvas.drawRightString(PAGE_W - 18*mm, 7*mm,
            f"Page {doc.page}")
        canvas.restoreState()


# ── Table builder ──────────────────────────────────────────────────────────

def _scanner_table(df: pd.DataFrame, top_n: int = 15,
                   sort_col: str = "Sharpe") -> Table:
    """Coloured scanner table — top_n rows, sorted by sort_col."""
    show = df.dropna(subset=[sort_col]).nlargest(top_n, sort_col).reset_index(drop=True)
    cols = ["Trade", "Type", "Z", "E[Ret]", "Risk", "Sharpe", "D1W"]
    headers = ["Trade", "Type", "Z", "E[Ret]\nbps/yr", "Risk\nbps/yr", "Sharpe", "ΔW\nbps"]

    col_w = [52*mm, 16*mm, 16*mm, 18*mm, 18*mm, 18*mm, 16*mm]

    data = [headers]
    for _, r in show.iterrows():
        row = [
            r.get("Trade", ""),
            r.get("Type", ""),
            f"{r['Z']:+.2f}" if pd.notna(r.get("Z")) else "—",
            f"{r['E[Ret]']:+.0f}" if pd.notna(r.get("E[Ret]")) else "—",
            f"{r['Risk']:.0f}"  if pd.notna(r.get("Risk")) else "—",
            f"{r['Sharpe']:+.2f}" if pd.notna(r.get("Sharpe")) else "—",
            f"{r['D1W']:+.1f}" if pd.notna(r.get("D1W")) else "—",
        ]
        data.append(row)

    t = Table(data, colWidths=col_w, repeatRows=1)

    style = [
        # Header
        ("BACKGROUND", (0,0), (-1,0), C_PANEL2),
        ("TEXTCOLOR",  (0,0), (-1,0), C_ACCENT),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,0), 7.5),
        ("ALIGN",      (0,0), (-1,0), "CENTER"),
        ("BOTTOMPADDING", (0,0), (-1,0), 5),
        ("TOPPADDING",    (0,0), (-1,0), 5),
        # Body
        ("FONTSIZE",   (0,1), (-1,-1), 8),
        ("FONTNAME",   (0,1), (-1,-1), "Helvetica"),
        ("TEXTCOLOR",  (0,1), (-1,-1), C_TEXT1),
        ("ALIGN",      (0,1), (0,-1), "LEFT"),
        ("ALIGN",      (1,1), (-1,-1), "CENTER"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [C_PANEL, C_BG]),
        ("BOTTOMPADDING", (0,1), (-1,-1), 4),
        ("TOPPADDING",    (0,1), (-1,-1), 4),
        ("LINEBELOW", (0,0), (-1,0), 0.5, C_DIVIDER),
        ("GRID",      (0,0), (-1,-1), 0.3, C_DIVIDER),
    ]

    # Z-score cell colouring
    for i, (_, r) in enumerate(show.iterrows(), start=1):
        z = r.get("Z", float("nan"))
        s = r.get("Sharpe", float("nan"))
        d = r.get("D1W", float("nan"))
        if not pd.isna(z):
            style += [
                ("BACKGROUND", (2, i), (2, i), _z_color(z)),
                ("TEXTCOLOR",  (2, i), (2, i), _z_text_color(z)),
            ]
        if not pd.isna(s):
            style += [
                ("BACKGROUND", (5, i), (5, i), _sharpe_color(s)),
                ("TEXTCOLOR",  (5, i), (5, i),
                 C_WHITE if abs(s) > 0.5 else C_TEXT1),
            ]
        if not pd.isna(d):
            style += [
                ("BACKGROUND", (6, i), (6, i), _move_color(d)),
                ("TEXTCOLOR",  (6, i), (6, i),
                 C_WHITE if abs(d) > 10 else C_TEXT1),
            ]

    t.setStyle(TableStyle(style))
    return t


def _curve_table(curve_dict: dict, hist: Optional[pd.DataFrame] = None) -> Table:
    """Tenor snapshot table: Level | ΔW | Δ1M | Z(252d)."""
    tenors = ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
    headers = ["Tenor", "Level (%)", "ΔW (bps)", "Δ1M (bps)", "Z (252d)"]
    col_w = [20*mm, 24*mm, 24*mm, 24*mm, 24*mm]
    data = [headers]

    for t in tenors:
        if hist is not None and t in hist.columns:
            s = hist[t].dropna()
            level  = f"{float(s.iloc[-1]):.3f}" if len(s) else "—"
            d1w    = f"{(float(s.iloc[-1]) - float(s.iloc[-6]))*100:+.1f}" if len(s) > 5 else "—"
            d1m    = f"{(float(s.iloc[-1]) - float(s.iloc[-22]))*100:+.1f}" if len(s) > 21 else "—"
            mu = s.rolling(252).mean().iloc[-1]; sd = s.rolling(252).std().iloc[-1]
            z      = f"{(float(s.iloc[-1]) - mu) / sd:+.2f}" if sd and sd > 0 else "—"
            z_val  = (float(s.iloc[-1]) - mu) / sd if sd and sd > 0 else float("nan")
        else:
            level = d1w = d1m = z = "—"; z_val = float("nan")
        data.append([t, level, d1w, d1m, z])

    t_obj = Table(data, colWidths=col_w, repeatRows=1)
    style = [
        ("BACKGROUND", (0,0), (-1,0), C_PANEL2),
        ("TEXTCOLOR",  (0,0), (-1,0), C_ACCENT),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 8),
        ("ALIGN",      (0,0), (-1,-1), "CENTER"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [C_PANEL, C_BG]),
        ("TEXTCOLOR",  (0,1), (-1,-1), C_TEXT1),
        ("GRID",       (0,0), (-1,-1), 0.3, C_DIVIDER),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
    ]

    # Colour the ΔW, Δ1M, Z columns
    for i, row in enumerate(data[1:], start=1):
        for col_idx, raw in [(2, row[2]), (3, row[3])]:
            try:
                v = float(raw)
                style += [
                    ("BACKGROUND", (col_idx, i), (col_idx, i), _move_color(v)),
                    ("TEXTCOLOR",  (col_idx, i), (col_idx, i),
                     C_WHITE if abs(v) > 10 else C_TEXT1),
                ]
            except (ValueError, TypeError):
                pass
        # Z column (idx 4) — use z_color
        try:
            z_num = float(row[4])
            style += [
                ("BACKGROUND", (4, i), (4, i), _z_color(z_num)),
                ("TEXTCOLOR",  (4, i), (4, i), _z_text_color(z_num)),
            ]
        except (ValueError, TypeError):
            pass

    t_obj.setStyle(TableStyle(style))
    return t_obj


# ── Monday setup content ───────────────────────────────────────────────────

def _emit_section(story: list, title: str, key: str, styles: dict,
                  section_notes: Optional[dict] = None) -> None:
    """Append a section heading, preceded by the admin's note (if any) for
    this short key.  Keys match the ones used by the Alerts-page composer UI
    so both the PDF and HTML paths read from the same dict."""
    note = ((section_notes or {}).get(key) or "").strip()
    if note:
        story.extend(_note_flowables(note))
    story.append(Paragraph(title, styles["section"]))
    story.append(Spacer(1, 2*mm))


def _monday_story(sdf: pd.DataFrame, hist_df: Optional[pd.DataFrame],
                  cfg: dict, styles: dict, monday: date,
                  section_notes: Optional[dict] = None) -> list:
    """Build the Monday 'setup' story elements."""
    from analysis.alert_body import (
        build_body, format_trade_plain, derive_tags, theme_summary,
        describe_valuation, ascii_sharpe_chart,
    )

    S = styles
    story = []

    # ── Intro ─────────────────────────────────────────────────────────────
    week_str = monday.strftime("%-d %B %Y")
    story += _note_flowables(((section_notes or {}).get("intro") or "").strip())
    story += [
        Paragraph(f"Week of {week_str} — What to watch", S["section"]),
        Spacer(1, 2*mm),
        Paragraph(
            "The following is the model-derived relative value setup for the week ahead. "
            "All signals are based on carry, roll, and z-score dislocation — not forecasts.",
            S["body"],
        ),
        Spacer(1, 3*mm),
    ]

    # ── Curve snapshot ────────────────────────────────────────────────────
    _emit_section(story, "CURVE SNAPSHOT", "curve_snapshot", S, section_notes)
    if hist_df is not None and not hist_df.empty:
        story.append(_curve_table({}, hist=hist_df))
    else:
        story.append(Paragraph("Curve data unavailable.", S["caption"]))
    story.append(Spacer(1, 4*mm))

    if sdf.empty:
        story.append(Paragraph("Scanner data unavailable.", S["body"]))
        return story

    filt = sdf[sdf["Type"].isin(cfg.get("trade_types", ["Outright","Curve","Fly"]))].dropna(subset=["Sharpe"])
    top  = filt.nlargest(cfg.get("top_n", 10), "Sharpe")
    best = top.iloc[0]
    best_name = format_trade_plain(best["Trade"], best["Type"])
    best_z    = float(best["Z"])

    # ── Highest conviction ────────────────────────────────────────────────
    _emit_section(story, "HIGHEST CONVICTION RV SIGNAL", "top_signal", S, section_notes)
    story.append(Paragraph(f"Receive {best_name}", ParagraphStyle(
        "best", fontName="Helvetica-Bold", fontSize=13, textColor=C_ACCENT,
    )))
    story.append(Paragraph(
        "Tags: " + " ".join(derive_tags(best, top=True)), S["tag"]
    ))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        f"Top-ranked structure on the screen with Sharpe <b>{best['Sharpe']:+.2f}</b>, "
        f"expected return <b>{best['E[Ret]']:+.0f} bps/yr</b>, and risk {best['Risk']:.0f}. "
        f"The structure {describe_valuation(best_z)} (z-score {best_z:+.2f}).",
        S["body"],
    ))
    if best_z < -0.5:
        why = "Dislocation has not fully normalised — carry is supportive while valuation remains cheap."
    elif best_z > 0.5:
        why = "Carry and roll are doing the work; signal remains elevated despite rich valuation."
    else:
        why = "Model signal is strongest here with valuation broadly in line with history."
    story += [
        Paragraph(f"<b>Why now:</b> {why}", S["body"]),
        Paragraph("<b>Regime fit:</b> best in lower-vol, shock-fading environment.", S["body"]),
        Paragraph("<b>Risk:</b> renewed long-end selling or vol spike would delay reversion.", S["body"]),
        Spacer(1, 4*mm),
    ]

    # ── Theme building ────────────────────────────────────────────────────
    theme = theme_summary(top)
    similar = [format_trade_plain(r["Trade"], r["Type"]) for _, r in top.iloc[1:4].iterrows()]
    anchor  = "/".join(theme["common"][:2]) if theme["common"] else "the curve"

    _emit_section(story, "THEME BUILDING ACROSS THE CURVE", "theme", S, section_notes)
    if similar:
        story.append(Paragraph(
            f"Signals are clustering in <b>{anchor}</b>-led receiver structures, "
            f"including {', '.join(similar)}. This suggests the opportunity is "
            "thematic rather than isolated.",
            S["body"],
        ))
    story.append(Spacer(1, 4*mm))

    # ── Top 15 scanner table ──────────────────────────────────────────────
    _emit_section(story, "TOP SIGNALS BY SHARPE", "top_table", S, section_notes)
    story.append(_scanner_table(filt, top_n=15, sort_col="Sharpe"))
    story.append(Spacer(1, 4*mm))

    # ── Most stretched this week ──────────────────────────────────────────
    mov = filt.reindex(filt["D1W"].abs().sort_values(ascending=False).index)
    biggest = mov.iloc[0]
    _emit_section(story, "MOST STRETCHED — WATCH FOR REVERSAL", "movers", S, section_notes)
    big_name = format_trade_plain(biggest["Trade"], biggest["Type"])
    big_z = float(biggest["Z"])
    cheap_rich = "cheap" if big_z < -0.5 else ("rich" if big_z > 0.5 else "near fair value")
    story.append(Paragraph(
        f"<b>Receive {big_name}</b> — moved {biggest['D1W']:+.1f} bps last week "
        f"and now screens {cheap_rich} at z-score {big_z:+.2f}. "
        "Watch for mean reversion if vol stabilises.",
        S["body"],
    ))

    return story


# ── Friday recap content ───────────────────────────────────────────────────

def _friday_story(sdf: pd.DataFrame, hist_df: Optional[pd.DataFrame],
                  cfg: dict, styles: dict, monday: date,
                  section_notes: Optional[dict] = None) -> list:
    """Build the Friday 'what happened' story elements."""
    from analysis.alert_body import format_trade_plain, derive_tags

    S = styles
    story = []

    # ── Intro ─────────────────────────────────────────────────────────────
    week_str = monday.strftime("%-d %B %Y")
    story += _note_flowables(((section_notes or {}).get("intro") or "").strip())
    story += [
        Paragraph(f"Week of {week_str} — What happened", S["section"]),
        Spacer(1, 2*mm),
        Paragraph(
            "End-of-week recap: curve moves, signal performance, and any "
            "notable dislocations that emerged during the week.",
            S["body"],
        ),
        Spacer(1, 3*mm),
    ]

    # ── Curve moves ───────────────────────────────────────────────────────
    _emit_section(story, "THIS WEEK'S CURVE MOVES", "curve", S, section_notes)
    if hist_df is not None and not hist_df.empty:
        story.append(_curve_table({}, hist=hist_df))
    else:
        story.append(Paragraph("Curve data unavailable.", S["caption"]))
    story.append(Spacer(1, 4*mm))

    if sdf.empty:
        story.append(Paragraph("Scanner data unavailable.", S["body"]))
        return story

    filt = sdf[sdf["Type"].isin(cfg.get("trade_types", ["Outright","Curve","Fly"]))].dropna(subset=["Sharpe"])

    # ── Biggest weekly movers ─────────────────────────────────────────────
    _emit_section(story, "BIGGEST WEEKLY MOVERS", "movers_fri", S, section_notes)
    movers = filt.reindex(filt["D1W"].abs().sort_values(ascending=False).index).head(12)
    story.append(_scanner_table(movers, top_n=12, sort_col="D1W"))
    story.append(Spacer(1, 4*mm))

    # ── Signal scorecard: did the week's top signals pay? ─────────────────
    _emit_section(story, "SIGNAL SCORECARD — Did the top signals deliver?", "scorecard", S, section_notes)
    top15 = filt.nlargest(15, "Sharpe")
    heads = ["Trade", "Sharpe", "Z", "D1W bps", "Verdict"]
    cw    = [52*mm, 18*mm, 18*mm, 18*mm, 40*mm]
    tdata = [heads]
    for _, r in top15.iterrows():
        d = float(r["D1W"]) if pd.notna(r.get("D1W")) else 0.0
        z = float(r.get("Z", 0))
        if d > 2:      verdict = "✓ Worked"
        elif d < -2:   verdict = "✗ Went against"
        else:          verdict = "→ Flat"
        tdata.append([
            format_trade_plain(r["Trade"], r["Type"]),
            f"{r['Sharpe']:+.2f}",
            f"{z:+.2f}",
            f"{d:+.1f}",
            verdict,
        ])
    sc = Table(tdata, colWidths=cw, repeatRows=1)
    sc_style = [
        ("BACKGROUND",   (0,0), (-1,0), C_PANEL2),
        ("TEXTCOLOR",    (0,0), (-1,0), C_ACCENT),
        ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,-1), 8),
        ("ALIGN",        (0,0), (-1,-1), "CENTER"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [C_PANEL, C_BG]),
        ("TEXTCOLOR",    (0,1), (-1,-1), C_TEXT1),
        ("GRID",         (0,0), (-1,-1), 0.3, C_DIVIDER),
        ("BOTTOMPADDING",(0,0), (-1,-1), 4),
        ("TOPPADDING",   (0,0), (-1,-1), 4),
    ]
    for i, row in enumerate(tdata[1:], 1):
        verdict = row[4]
        if "✓" in verdict:
            sc_style += [("TEXTCOLOR", (4,i), (4,i), C_GREEN),
                         ("FONTNAME",  (4,i), (4,i), "Helvetica-Bold")]
        elif "✗" in verdict:
            sc_style += [("TEXTCOLOR", (4,i), (4,i), C_RED),
                         ("FONTNAME",  (4,i), (4,i), "Helvetica-Bold")]
        # Colour Z
        try:
            zv = float(row[2])
            sc_style += [("BACKGROUND",(2,i),(2,i), _z_color(zv)),
                         ("TEXTCOLOR", (2,i),(2,i), _z_text_color(zv))]
        except ValueError:
            pass
        # Colour D1W
        try:
            dv = float(row[3])
            sc_style += [("BACKGROUND",(3,i),(3,i), _move_color(dv)),
                         ("TEXTCOLOR", (3,i),(3,i), C_WHITE if abs(dv) > 5 else C_TEXT1)]
        except ValueError:
            pass
    sc.setStyle(TableStyle(sc_style))
    story.append(sc)
    story.append(Spacer(1, 4*mm))

    # ── Fresh top signals for next week ───────────────────────────────────
    _emit_section(story, "INTO NEXT WEEK — Refreshed top signals", "next_week", S, section_notes)
    story.append(_scanner_table(filt, top_n=10, sort_col="Sharpe"))

    # ── Week in review headlines (auto-embedded) ─────────────────────────
    headlines = _fetch_headlines(limit_per_source=3)
    if headlines:
        story.append(Spacer(1, 5*mm))
        _emit_section(story, "WEEK IN REVIEW — Headlines", "headlines", S, section_notes)
        item_s = ParagraphStyle("hl_item", fontName="Helvetica", fontSize=8.5,
                                textColor=C_TEXT1, leading=12)
        src_s  = ParagraphStyle("hl_src",  fontName="Helvetica-Bold", fontSize=8,
                                textColor=C_ACCENT, leading=12)
        for h in headlines[:18]:
            story.append(Paragraph(
                f'<font color="{C_ACCENT.hexval()}"><b>{h["source"]}</b></font> · '
                f'<a href="{h["link"]}" color="{C_TEXT1.hexval()}">{h["title"]}</a>',
                item_s,
            ))
            story.append(Spacer(1, 0.8*mm))

    return story


def _fetch_headlines(limit_per_source: int = 3) -> list:
    """Pull recent headlines for the WEEK IN REVIEW section.  Self-contained
    (no streamlit dep) so the weekly_pdf builder works from cron too."""
    try:
        import feedparser
    except ImportError:
        return []
    feeds = [
        ("Macro Manv", "https://manveersahota.substack.com/feed"),
        ("Bloomberg",  "https://feeds.bloomberg.com/markets/news.rss"),
        ("FT",         "https://www.ft.com/markets?format=rss"),
        ("Fed",        "https://www.federalreserve.gov/feeds/press_monetary.xml"),
        ("ECB",        "https://www.ecb.europa.eu/rss/press.html"),
        ("BoE",        "https://www.bankofengland.co.uk/rss/news"),
    ]
    out: list = []
    for src, url in feeds:
        try:
            f = feedparser.parse(url)
        except Exception:
            continue
        for e in f.entries[:limit_per_source]:
            out.append({
                "source": src,
                "title":  str(e.get("title", "")).strip()[:140],
                "link":   str(e.get("link", "#")),
            })
    return out


# ── Main entry point ──────────────────────────────────────────────────────

def build_weekly_pdf(
    scanner_df: pd.DataFrame,
    hist_df: Optional[pd.DataFrame],
    cfg: dict,
    out_dir: Optional[Path] = None,
    force_day: Optional[str] = None,   # "monday" | "friday" for testing
    personal_comment: str = "",
    section_notes: Optional[dict] = None,
) -> Path:
    """
    Build the PDF and return its path.

    Parameters
    ----------
    scanner_df       : scanner output DataFrame
    hist_df          : master DataFrame with tenor columns (for curve table)
    cfg              : alert config dict
    out_dir          : where to write the PDF (default: briefs/<date>/)
    force_day        : override weekday detection ("monday" or "friday")
    personal_comment : admin's free-text note rendered at the top of the PDF
    section_notes    : {section_title: note_text} rendered above each section
    """
    today   = date.today()
    monday  = _monday_of_week(today)
    is_fri  = (force_day == "friday") if force_day else _is_friday(today)
    day_tag = "Friday" if is_fri else "Monday"

    mon_str    = monday.strftime("%d %b %Y")
    title      = f"Rates Weekly — Macro Manv  |  {mon_str}"
    subtitle   = f"{'Recap · What happened this week' if is_fri else 'Setup · What to watch this week'}"
    filename   = f"Rates_Weekly_{monday.strftime('%Y-%m-%d')}_{day_tag}.pdf"

    out_dir = out_dir or (Path(__file__).parent.parent / "briefs" / monday.strftime("%Y-%m-%d"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    styles = _make_styles()
    doc    = _MMDoc(str(out_path), title=title, subtitle=subtitle)

    # Cover header (inside content area — the page template draws the top bar)
    story = [
        Paragraph("Rates Weekly — Macro Manv", ParagraphStyle(
            "cover_title", fontName="Helvetica-Bold", fontSize=26,
            textColor=C_TEXT1, leading=34, spaceAfter=4,
        )),
        Paragraph(
            f"{'RECAP · What happened this week' if is_fri else 'SETUP · What to watch this week'}"
            f"  ·  Week of {mon_str}",
            ParagraphStyle("cover_sub", fontName="Helvetica", fontSize=13,
                           textColor=C_ACCENT, leading=18, spaceAfter=2),
        ),
        HRFlowable(width="100%", thickness=0.5, color=C_DIVIDER, spaceAfter=6),
        Spacer(1, 4*mm),
    ]

    # Admin's personal comment, if any, sits right below the cover header.
    story.extend(_comment_flowables(personal_comment))

    if is_fri:
        story += _friday_story(scanner_df, hist_df, cfg, styles, monday, section_notes)
    else:
        story += _monday_story(scanner_df, hist_df, cfg, styles, monday, section_notes)

    # ── Closing page — centred signal logo + tagline ───────────────────────
    story += _closing_page_flowables()

    doc.build(story)
    return out_path


def _closing_page_flowables() -> list:
    """
    Returns flowables for the branded closing page:
    large centred mm_logo_signal.png + disclaimer line.
    Falls back gracefully if the file is missing.
    """
    PAGE_W, _ = A4
    content_w = PAGE_W - 36 * mm   # matches left+right margins

    flowables: list = [
        # Push to a new page
        Spacer(1, 6 * mm),
        HRFlowable(width="100%", thickness=0.4, color=C_DIVIDER, spaceAfter=0),
    ]

    if _LOGO_SIGNAL_PATH.exists():
        logo_size = 72 * mm   # ~72mm square — large but not full-page
        img = Image(
            str(_LOGO_SIGNAL_PATH),
            width=logo_size,
            height=logo_size,
            kind="proportional",
        )
        # Centre by wrapping in a 1-cell Table
        logo_tbl = Table(
            [[img]],
            colWidths=[content_w],
            rowHeights=[logo_size + 4 * mm],
            style=TableStyle([
                ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
                ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND",  (0, 0), (-1, -1), C_BG),
                ("BOX",         (0, 0), (-1, -1), 0, C_BG),
            ]),
        )
        flowables.append(Spacer(1, 18 * mm))
        flowables.append(logo_tbl)
        flowables.append(Spacer(1, 8 * mm))

    flowables.append(
        Paragraph(
            "Macro Manv · Charts, Trades and Signal · macromanv.substack.com",
            ParagraphStyle(
                "closing_cap",
                fontName="Helvetica",
                fontSize=9,
                textColor=C_TEXT2,
                alignment=TA_CENTER,
                spaceAfter=4,
            ),
        )
    )
    flowables.append(
        Paragraph(
            "Model estimates only · Not investment advice · Data sourced from public APIs",
            ParagraphStyle(
                "closing_disc",
                fontName="Helvetica",
                fontSize=8,
                textColor=C_TEXT3,
                alignment=TA_CENTER,
            ),
        )
    )
    return flowables
