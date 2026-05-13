"""Page 21 — Post Drafter.

Generates a first-draft Substack post from today's scanner + curve state.

Three drafting modes — first available wins, no key required for the default:

  1. **Template** (default, always works) — deterministic Markdown built from
     the scanner output, curve snapshot, and Z-extremes. Genuinely useful;
     reads like a competent desk note. No API call.

  2. **Gemini** (free tier) — if `GEMINI_API_KEY` is set. Google's free tier
     is 1500 requests/day on Gemini 2.0 Flash. Get a key in 30s at
     https://aistudio.google.com — no card required.

  3. **Ollama** (local, free) — if Ollama is running on localhost:11434. Pick
     a model with `ollama pull llama3` etc.

  4. **Anthropic** — if `ANTHROPIC_API_KEY` is set. Best quality, usage-based.

Set the preferred mode below or let the page auto-pick the first available.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import (
    get_master_df, init_session_state, password_gate, is_admin, _secret,
)

st.set_page_config(page_title="Post Drafter", page_icon="✍️", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="AI Post Drafter")

st.title("✍️ Post Drafter")
st.caption(
    "First-draft Substack post from today's scanner + curve. Works with no "
    "API key (template mode); upgrades to LLM-generated prose if you wire one in."
)

if not is_admin():
    st.warning("Admin only. Log in with the admin password to use this tool.")
    st.stop()


# ── Provider detection ───────────────────────────────────────────────────
ANTHROPIC_KEY = _secret("ANTHROPIC_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_KEY    = _secret("GEMINI_API_KEY", "")    or os.getenv("GEMINI_API_KEY", "")

def _ollama_alive() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        return True
    except Exception:
        return False

OLLAMA_OK = _ollama_alive()
PROVIDERS_AVAIL = ["Template (no LLM)"]
if GEMINI_KEY:    PROVIDERS_AVAIL.append("Gemini 2.0 Flash (free)")
if OLLAMA_OK:     PROVIDERS_AVAIL.append("Ollama (local)")
if ANTHROPIC_KEY: PROVIDERS_AVAIL.append("Anthropic Claude")

df = get_master_df()
if df.empty:
    st.error("No market data — refresh the cache.")
    st.stop()


# ── Substack voice connector — pull recent posts for tone matching ────────
@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _fetch_recent_substack(limit: int = 10) -> list[dict]:
    """Pull recent Macro Manv posts via RSS — title + summary + date.
    Used by the drafter as voice-matching context."""
    try:
        import feedparser
    except ImportError:
        return []
    try:
        f = feedparser.parse("https://manveersahota.substack.com/feed")
        out = []
        for e in f.entries[:limit]:
            out.append({
                "title":     str(e.get("title", "")).strip(),
                "published": str(e.get("published", e.get("updated", ""))),
                "summary":   _strip_html(str(e.get("summary", "")))[:800],
            })
        return out
    except Exception:
        return []


def _strip_html(text: str) -> str:
    """Crude HTML→text — keeps prose, drops tags / nbsp."""
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#x27;", "'")
    return re.sub(r"\s+", " ", text).strip()


recent_posts = _fetch_recent_substack(limit=10)


# ── Build market context (shared by all providers) ───────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def _build_context() -> dict:
    """Compact structured snapshot of today's market state."""
    from scripts.send_alert import build_scanner

    out: dict = {"date": datetime.today().strftime("%Y-%m-%d")}
    tenors = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
    avail  = [t for t in tenors if t in df.columns]
    if avail:
        last = df[avail].dropna(how="all").iloc[-1]
        wk   = df[avail].dropna(how="all").iloc[max(0, len(df) - 6)] if len(df) >= 6 else last
        mo   = df[avail].dropna(how="all").iloc[max(0, len(df) - 22)] if len(df) >= 22 else last
        out["curve"] = [{
            "tenor": t, "level": float(last[t]),
            "d1w_bps": float((last[t] - wk[t]) * 100),
            "d1m_bps": float((last[t] - mo[t]) * 100),
        } for t in avail]
        if "2Y" in avail and "10Y" in avail:
            out["s2s10s_now"] = float((last["10Y"] - last["2Y"]) * 100)
            out["s2s10s_d1w"] = float(out["s2s10s_now"] - (wk["10Y"] - wk["2Y"]) * 100)

    for col, key in [("VIX", "vix"), ("IG_OAS", "ig_oas"), ("HY_OAS", "hy_oas"),
                     ("SOFR", "sofr"), ("BREAKEVEN_10Y", "be_10y")]:
        if col in df.columns:
            s = df[col].dropna()
            if not s.empty:
                out[key] = float(s.iloc[-1])

    try:
        sdf = build_scanner()
        if not sdf.empty:
            top = sdf.dropna(subset=["Sharpe"]).nlargest(10, "Sharpe")
            out["top_trades"] = top.to_dict("records")
            out["cheap"] = sdf[sdf["Z"] < -2].sort_values("Z").head(5).to_dict("records")
            out["rich"]  = sdf[sdf["Z"] >  2].sort_values("Z", ascending=False).head(5).to_dict("records")
    except Exception as e:
        out["scanner_error"] = str(e)
    return out


ctx = _build_context()


# ── Template generator (always available — the no-key path) ──────────────
def _format_trade(t: str, ttype: str) -> str:
    bare = t.replace("Rcv ", "")
    if ttype == "Fly":   return bare.replace("/", "") + " fly"
    if ttype == "Curve": return f"{bare} curve"
    return bare


def template_draft(ctx: dict, post_type: str, length: str, tone: str,
                    title_hint: str = "", angle: str = "") -> str:
    """Deterministic Markdown draft — uses every meaningful data point.
    Reads as a competent desk note, not a stub."""
    date_str = datetime.today().strftime("%d %b %Y")

    # Build the lede
    lede_parts = []
    if ctx.get("top_trades"):
        best = ctx["top_trades"][0]
        best_name = _format_trade(best["Trade"], best["Type"])
        if best["Z"] < -0.5:
            stance = f"still trades cheap (z = {best['Z']:+.2f})"
        elif best["Z"] > 0.5:
            stance = f"sits rich (z = {best['Z']:+.2f})"
        else:
            stance = "screens fairly valued"
        lede_parts.append(
            f"**The trade that screens best today is receive {best_name}** — "
            f"Sharpe {best['Sharpe']:+.2f}, expected return {best['E[Ret]']:+.0f} bps/yr — "
            f"and it {stance}."
        )
    if ctx.get("s2s10s_now") is not None:
        d = ctx.get("s2s10s_d1w", 0)
        direction = "flattened" if d < 0 else "steepened"
        lede_parts.append(
            f"2s10s sits at **{ctx['s2s10s_now']:+.0f} bps**, having {direction} "
            f"{abs(d):.0f} bps over the week."
        )

    # Headline
    if title_hint.strip():
        title = title_hint.strip()
    elif ctx.get("top_trades"):
        best = ctx["top_trades"][0]
        title = f"The {_format_trade(best['Trade'], best['Type'])} screen"
    else:
        title = "Rates this week — scanner read"

    # Build the body
    lines = [f"# {title}", f"_{date_str} — Macro Manv_", ""]
    if angle.strip():
        lines.append(f"> {angle.strip()}")
        lines.append("")
    lines.append(" ".join(lede_parts))
    lines.append("")

    # Curve walk
    if ctx.get("curve"):
        lines.append("## Where the curve sits")
        lines.append("")
        movers = sorted(ctx["curve"], key=lambda r: abs(r["d1w_bps"]), reverse=True)[:3]
        mover_strs = [f"the **{m['tenor']}** at {m['level']:.2f}% ({m['d1w_bps']:+.0f} bps on the week)" for m in movers]
        lines.append(
            "The biggest movers over the past week are " + ", ".join(mover_strs) + ". "
            "Outside that, the curve has held its shape."
        )
        lines.append("")
        lines.append("| Tenor | Level | 1w Δ | 1m Δ |")
        lines.append("|---|---:|---:|---:|")
        for r in ctx["curve"]:
            lines.append(f"| {r['tenor']} | {r['level']:.2f}% | {r['d1w_bps']:+.0f} bps | {r['d1m_bps']:+.0f} bps |")
        lines.append("")

    # Top trades
    if ctx.get("top_trades"):
        lines.append("## What the scanner is flagging")
        lines.append("")
        top5 = ctx["top_trades"][:5]
        top_names = [_format_trade(t["Trade"], t["Type"]) for t in top5]
        # Detect concentration
        from collections import Counter
        types = Counter(t["Type"] for t in top5)
        dominant = types.most_common(1)[0][0]
        if dominant == "Fly":
            theme = "Receiver flies dominate the top of the screen — the curve is pricing belly convexity attractively."
        elif dominant == "Curve":
            theme = "Flatteners are leading the screen — the model thinks the curve has further to compress."
        else:
            theme = "Outrights are leading — the model wants directional duration, not RV."
        lines.append(theme + " The top five by Sharpe:")
        lines.append("")
        lines.append("| # | Trade | Sharpe | Z | E[Ret] |")
        lines.append("|---|---|---:|---:|---:|")
        for i, t in enumerate(top5, 1):
            lines.append(
                f"| {i} | Receive {_format_trade(t['Trade'], t['Type'])} | "
                f"{t['Sharpe']:+.2f} | {t['Z']:+.2f} | {t['E[Ret]']:+.0f} bps/yr |"
            )
        lines.append("")

    # Z-extremes
    if ctx.get("cheap") or ctx.get("rich"):
        lines.append("## Stretched z-scores")
        lines.append("")
        if ctx.get("cheap"):
            cheap_names = [_format_trade(c["Trade"], c["Type"]) for c in ctx["cheap"][:3]]
            cheap_zs    = [f"{c['Z']:+.2f}" for c in ctx["cheap"][:3]]
            lines.append(
                "**Cheap (z < −2):** " +
                ", ".join(f"{n} ({z})" for n, z in zip(cheap_names, cheap_zs)) +
                ". These have moved hard enough in one direction that the 1-year history calls them dislocated."
            )
            lines.append("")
        if ctx.get("rich"):
            rich_names = [_format_trade(r["Trade"], r["Type"]) for r in ctx["rich"][:3]]
            rich_zs    = [f"{r['Z']:+.2f}" for r in ctx["rich"][:3]]
            lines.append(
                "**Rich (z > +2):** " +
                ", ".join(f"{n} ({z})" for n, z in zip(rich_names, rich_zs)) +
                "."
            )
            lines.append("")

    # Cross-asset context
    cross_parts = []
    if ctx.get("vix") is not None:
        cross_parts.append(f"VIX at **{ctx['vix']:.1f}**")
    if ctx.get("ig_oas") is not None:
        cross_parts.append(f"IG OAS **{ctx['ig_oas']:.0f} bps**")
    if ctx.get("hy_oas") is not None:
        cross_parts.append(f"HY OAS **{ctx['hy_oas']:.0f} bps**")
    if ctx.get("be_10y") is not None:
        cross_parts.append(f"10Y breakeven **{ctx['be_10y']:.2f}%**")
    if cross_parts:
        lines.append("## Backdrop")
        lines.append("")
        lines.append("For context: " + ", ".join(cross_parts) + ".")
        lines.append("")

    # Closing wrap
    if ctx.get("top_trades"):
        best = ctx["top_trades"][0]
        lines.append(
            f"**The trade I'd put on:** receive {_format_trade(best['Trade'], best['Type'])} "
            f"as the cleanest expression of where the model has its highest conviction. "
            f"Carry is supportive; the dislocation hasn't fully normalised."
        )
        lines.append("")

    lines.append("---")
    lines.append("_Subscribe to Macro Manv for the daily scan + weekly recap._")
    return "\n".join(lines)


# ── Provider implementations ─────────────────────────────────────────────
def _build_system_prompt(posts: list[dict]) -> str:
    """System prompt with optional voice samples from recent Substack posts."""
    base = (
        "You are 'Macro Manv', a fixed-income trader writing a Substack on rates "
        "relative-value, curve, and macro themes. Your readers are rates "
        "professionals — they know what 2s10s, DV01, carry/roll, fly, and z-score "
        "mean. Don't waste words explaining basics.\n\n"
        "Voice: punchy, opinionated, evidence-based. Short paragraphs. Use the "
        "data given to back specific claims. Avoid filler. Avoid 'in conclusion'. "
        "If the data doesn't support a clean call, say so — don't manufacture "
        "conviction. Markdown output, no emojis unless the user asks for them."
    )
    if not posts:
        return base
    # Include the 3 most recent post titles + summaries as voice samples
    voice = "\n\n=== RECENT SUBSTACK POSTS (your own voice — match this tone) ===\n"
    for p in posts[:3]:
        voice += f"\nTITLE: {p['title']}\n"
        if p.get("summary"):
            voice += f"OPENING: {p['summary'][:400]}\n"
    voice += ("\n=== END VOICE SAMPLES ===\n\n"
              "Match the cadence, sentence length, and willingness to be "
              "specific with numbers shown above.")
    return base + voice


SYSTEM_PROMPT = _build_system_prompt(recent_posts)


def _llm_user_msg(ctx: dict, post_type: str, length: str, tone: str,
                   title_hint: str, angle: str) -> str:
    # Compact context block (LLM-friendly)
    lines = [f"DATE: {ctx['date']}", ""]
    if ctx.get("curve"):
        lines.append("CURVE (yield % | 1w bps | 1m bps):")
        for r in ctx["curve"]:
            lines.append(f"  {r['tenor']:4s}  {r['level']:.2f}%  {r['d1w_bps']:+5.1f}  {r['d1m_bps']:+5.1f}")
    if ctx.get("s2s10s_now") is not None:
        lines.append(f"  2s10s: {ctx['s2s10s_now']:+.0f} bps (1w: {ctx['s2s10s_d1w']:+.0f})")
        lines.append("")
    cross = []
    for k, label, fmt in [("vix", "VIX", "{:.1f}"), ("ig_oas", "IG OAS", "{:.0f} bps"),
                           ("hy_oas", "HY OAS", "{:.0f} bps"), ("sofr", "SOFR", "{:.2f}%"),
                           ("be_10y", "10Y BE", "{:.2f}%")]:
        if ctx.get(k) is not None:
            cross.append(f"{label}: {fmt.format(ctx[k])}")
    if cross:
        lines.append("CROSS-ASSET: " + " · ".join(cross))
        lines.append("")
    if ctx.get("top_trades"):
        lines.append("TOP 10 RV TRADES:")
        for t in ctx["top_trades"]:
            lines.append(f"  {t['Trade']:16s} Sharpe={t['Sharpe']:+5.2f} Z={t['Z']:+5.2f} "
                          f"E[Ret]={t['E[Ret]']:+5.0f} D1W={t['D1W']:+5.1f}")
        lines.append("")
    if ctx.get("cheap"):
        lines.append("CHEAP (Z < -2): " +
                      ", ".join(f"{t['Trade']} Z={t['Z']:+.2f}" for t in ctx["cheap"]))
    if ctx.get("rich"):
        lines.append("RICH (Z > +2): " +
                      ", ".join(f"{t['Trade']} Z={t['Z']:+.2f}" for t in ctx["rich"]))
    ctx_block = "\n".join(lines)

    return (
        f"Draft a Substack post.\n\n"
        f"POST TYPE: {post_type}\n"
        f"TARGET LENGTH: {length}\n"
        f"TONE: {tone}\n"
        f"TITLE/ANGLE HINT: {title_hint or '(none — you choose)'}\n"
        f"AUTHOR'S ANGLE: {angle or '(none — derive a clean view from the data)'}\n\n"
        f"=== TODAY'S MARKET DATA ===\n{ctx_block}\n=== END DATA ===\n\n"
        f"Now write the post. Lead with the most interesting thing in the data. "
        f"Use the trade ideas / z-extremes where they support the argument. "
        f"End with a one-line wrap, no 'in conclusion'."
    )


def call_gemini(prompt: str, system: str = SYSTEM_PROMPT) -> str:
    """Call Google Gemini 2.0 Flash via REST. Free up to 1500 req/day."""
    url = ("https://generativelanguage.googleapis.com/v1beta/"
           "models/gemini-2.0-flash:generateContent?key=" + GEMINI_KEY)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2500},
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        data = json.loads(r.read())
    return data["candidates"][0]["content"]["parts"][0]["text"]


def call_ollama(prompt: str, system: str = SYSTEM_PROMPT,
                 model: str = "llama3") -> str:
    """Call local Ollama (free, runs on your machine)."""
    body = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 2000},
    }
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return data["response"]


def call_anthropic(prompt: str, system: str = SYSTEM_PROMPT) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    resp = client.messages.create(
        model=_secret("CLAUDE_MODEL", "") or "claude-sonnet-4-5",
        max_tokens=2500,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if hasattr(b, "text"))


# ── UI ────────────────────────────────────────────────────────────────────
st.divider()

with st.expander("📊 Market context — same data fed to every drafter mode",
                  expanded=False):
    st.json(ctx, expanded=False)

with st.expander(
    f"🗣️ Voice samples — {len(recent_posts)} recent Substack posts pulled for tone-matching",
    expanded=False,
):
    if recent_posts:
        for p in recent_posts[:5]:
            st.markdown(f"**{p['title']}**  ·  _{p.get('published','')[:16]}_")
            if p.get("summary"):
                st.caption(p["summary"][:300] + ("…" if len(p["summary"]) > 300 else ""))
    else:
        st.caption("RSS unavailable — drafter will use generic voice.")

st.subheader("Draft a post")

c1, c2, c3 = st.columns(3)
with c1:
    provider = st.selectbox(
        "Drafter",
        PROVIDERS_AVAIL,
        help=("Template = deterministic Markdown, no LLM, instant. "
              "Gemini = free tier, needs GEMINI_API_KEY. "
              "Ollama = local LLM. "
              "Anthropic = paid, best quality."),
    )
with c2:
    post_type = st.selectbox(
        "Post type",
        ["Monday Setup", "Friday Recap", "Mid-week Note",
         "Trade Idea — single thesis", "Educational — explainer", "Free-form"],
    )
with c3:
    target_length = st.selectbox(
        "Target length",
        ["Short (~250 words)", "Medium (~500 words)", "Long (~900 words)"],
        index=1,
    )

title_hint = st.text_input(
    "Title or angle (optional — helps the drafter anchor)",
    placeholder="e.g. 'The belly is screaming buy' or 'Why I'm fading the long-end rally'",
)
angle = st.text_area(
    "Your take / specific angle (optional but improves quality)",
    placeholder="One or two sentences on what you want to argue.",
    height=80,
)
tone = st.selectbox(
    "Tone",
    ["Punchy / desk-trader", "Educational / explainer",
     "Cautious / measured", "Hot-take / opinionated"],
)


# ── Show provider status banner ──────────────────────────────────────────
banner_msgs = []
banner_msgs.append(("Template", "✅ Always available — no key needed."))
if GEMINI_KEY:    banner_msgs.append(("Gemini",  "✅ GEMINI_API_KEY found"))
else:             banner_msgs.append(("Gemini",  "❌ Set GEMINI_API_KEY (free at https://aistudio.google.com)"))
if OLLAMA_OK:     banner_msgs.append(("Ollama",  "✅ Running on localhost:11434"))
else:             banner_msgs.append(("Ollama",  "❌ Not running. Install + `ollama serve` to enable."))
if ANTHROPIC_KEY: banner_msgs.append(("Anthropic","✅ ANTHROPIC_API_KEY found"))
else:             banner_msgs.append(("Anthropic","❌ Set ANTHROPIC_API_KEY for Claude (paid)"))

with st.expander("🔌 Drafter provider status", expanded=False):
    for name, msg in banner_msgs:
        st.markdown(f"- **{name}** — {msg}")


# ── Draft button ─────────────────────────────────────────────────────────
if st.button("✍️ Draft post", type="primary", use_container_width=True):
    with st.spinner(f"Drafting via {provider}…"):
        try:
            if provider.startswith("Template"):
                draft = template_draft(ctx, post_type, target_length, tone,
                                        title_hint, angle)
                usage_str = "Template mode — no API call, no cost."
            else:
                prompt = _llm_user_msg(ctx, post_type, target_length, tone,
                                        title_hint, angle)
                if provider.startswith("Gemini"):
                    draft = call_gemini(prompt)
                    usage_str = "Gemini 2.0 Flash · free tier · ~1500 req/day"
                elif provider.startswith("Ollama"):
                    draft = call_ollama(prompt)
                    usage_str = "Ollama local · free · model: llama3 (override in code)"
                elif provider.startswith("Anthropic"):
                    draft = call_anthropic(prompt)
                    usage_str = "Anthropic Claude · usage-based pricing"
                else:
                    draft = template_draft(ctx, post_type, target_length, tone,
                                            title_hint, angle)
                    usage_str = "Fell back to template"
            st.session_state["_draft"] = draft
            st.session_state["_draft_usage"] = usage_str
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="ignore")[:300]
            st.error(f"{provider} HTTP {e.code}: {err_body}")
            st.info("Falling back to template mode.")
            st.session_state["_draft"] = template_draft(
                ctx, post_type, target_length, tone, title_hint, angle)
            st.session_state["_draft_usage"] = "Template (fallback after error)"
        except Exception as e:
            st.error(f"{provider} failed: {e}")
            st.info("Falling back to template mode.")
            st.session_state["_draft"] = template_draft(
                ctx, post_type, target_length, tone, title_hint, angle)
            st.session_state["_draft_usage"] = "Template (fallback after error)"


# ── Render draft ──────────────────────────────────────────────────────────
draft = st.session_state.get("_draft", "")
if draft:
    st.divider()
    st.subheader("📝 Draft")
    st.caption(st.session_state.get("_draft_usage", ""))
    edited = st.text_area("Edit before copy/paste",
                          value=draft, height=520, key="_edit_buf")
    col_a, col_b = st.columns(2)
    with col_a:
        st.download_button(
            "⬇️ Download as Markdown",
            data=edited.encode("utf-8"),
            file_name=f"draft_{datetime.today().strftime('%Y-%m-%d')}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with col_b:
        if st.button("🔄 Re-draft", use_container_width=True):
            st.session_state.pop("_draft", None)
            st.rerun()

    with st.expander("🔍 Preview rendered", expanded=False):
        st.markdown(edited)
