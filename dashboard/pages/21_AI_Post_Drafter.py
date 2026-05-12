"""Page 21 — AI Post Drafter.

Streamlit page that turns today's scanner output + curve state into a
first-draft Substack post via the Anthropic SDK.  Admin-only.

Configuration:
  ANTHROPIC_API_KEY — set in .streamlit/secrets.toml or environment.
  Optional: CLAUDE_MODEL — defaults to a sensible Sonnet variant if unset.

The draft uses prompt caching: the system prompt + data context block are
cache-marked, so subsequent iterations on the same data (rewrite, change
tone, etc.) only pay output tokens, not input tokens.
"""

import os
import sys
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

st.set_page_config(page_title="AI Post Drafter", page_icon="✍️", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="AI Post Drafter")

st.title("✍️ AI Post Drafter")
st.caption("Turn today's scanner + curve into a first-draft Substack post.")

if not is_admin():
    st.warning("Admin only. Log in with the admin password to use this tool.")
    st.stop()

st.divider()

# ── Anthropic client ──────────────────────────────────────────────────────
API_KEY = _secret("ANTHROPIC_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")
MODEL   = _secret("CLAUDE_MODEL", "")    or os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")

if not API_KEY:
    st.error(
        "**No `ANTHROPIC_API_KEY` configured.**  Add it to "
        "`.streamlit/secrets.toml` (or your environment) and reload the page.\n\n"
        "Example:\n```toml\nANTHROPIC_API_KEY = \"sk-ant-…\"\n```"
    )
    st.info(
        "Get a key at https://console.anthropic.com/  ·  "
        "Pricing is usage-based; each draft typically costs a few cents."
    )
    st.stop()

try:
    import anthropic
except ImportError:
    st.error("`anthropic` package not installed. Run `pip install anthropic`.")
    st.stop()

client = anthropic.Anthropic(api_key=API_KEY)

# ── Data context ──────────────────────────────────────────────────────────
df = get_master_df()
if df.empty:
    st.error("No market data — refresh the cache.")
    st.stop()

@st.cache_data(ttl=600, show_spinner=False)
def _build_context() -> str:
    """Compact, model-friendly summary of today's market state."""
    from scripts.send_alert import build_scanner

    lines: list[str] = []
    lines.append(f"DATE: {datetime.today().strftime('%Y-%m-%d')}")
    lines.append("")

    # Curve snapshot
    tenors = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
    avail  = [t for t in tenors if t in df.columns]
    if avail:
        last = df[avail].dropna(how="all").iloc[-1]
        wk   = df[avail].dropna(how="all").iloc[max(0, len(df)-6)] if len(df) >= 6 else last
        mo   = df[avail].dropna(how="all").iloc[max(0, len(df)-22)] if len(df) >= 22 else last
        lines.append("CURVE (yields % | 1w bps | 1m bps):")
        for t in avail:
            d1w = (last[t] - wk[t]) * 100
            d1m = (last[t] - mo[t]) * 100
            lines.append(f"  {t:4s}  {last[t]:.2f}%  {d1w:+5.1f}  {d1m:+5.1f}")
        if "2Y" in avail and "10Y" in avail:
            slope_now = (last["10Y"] - last["2Y"]) * 100
            slope_wk  = (wk["10Y"]   - wk["2Y"])   * 100
            lines.append(f"  2s10s: {slope_now:+.0f} bps (1w change: {slope_now-slope_wk:+.0f} bps)")
        lines.append("")

    # Cross-asset context
    other_specs = [
        ("VIX",     "VIX",     "{:.1f}"),
        ("IG_OAS",  "IG OAS",  "{:.2f}%"),
        ("HY_OAS",  "HY OAS",  "{:.2f}%"),
        ("SOFR",    "SOFR o/n", "{:.2f}%"),
    ]
    rows = []
    for col, label, fmt in other_specs:
        if col in df.columns:
            s = df[col].dropna()
            if not s.empty:
                rows.append(f"  {label}: {fmt.format(s.iloc[-1])}")
    if rows:
        lines.append("CROSS-ASSET:")
        lines.extend(rows)
        lines.append("")

    # Scanner top 10
    try:
        sdf = build_scanner()
        if not sdf.empty:
            top = sdf.dropna(subset=["Sharpe"]).nlargest(10, "Sharpe")
            lines.append("TOP 10 RV TRADES (by Sharpe; rcv = receive):")
            lines.append("  Trade            Sharpe   Z   E[Ret]  Risk  D1W")
            for _, r in top.iterrows():
                lines.append(f"  {r['Trade']:16s} {r['Sharpe']:+5.2f}  "
                             f"{r['Z']:+5.2f}  {r['E[Ret]']:+5.0f}  {r['Risk']:4.0f}  {r['D1W']:+5.1f}")
            lines.append("")

            # Z-extremes
            cheap = sdf[sdf["Z"] < -2].sort_values("Z").head(5)
            rich  = sdf[sdf["Z"] >  2].sort_values("Z", ascending=False).head(5)
            if not cheap.empty:
                lines.append("Z-EXTREMES — CHEAP (Z < -2):")
                for _, r in cheap.iterrows():
                    lines.append(f"  {r['Trade']:16s} Z={r['Z']:+.2f}")
                lines.append("")
            if not rich.empty:
                lines.append("Z-EXTREMES — RICH (Z > +2):")
                for _, r in rich.iterrows():
                    lines.append(f"  {r['Trade']:16s} Z={r['Z']:+.2f}")
                lines.append("")
    except Exception as e:
        lines.append(f"(scanner unavailable: {e})")

    return "\n".join(lines)

context_block = _build_context()

with st.expander("📊 Market context being sent to the model", expanded=False):
    st.code(context_block, language=None)

# ── Form ──────────────────────────────────────────────────────────────────
st.subheader("Draft a post")

c1, c2 = st.columns([1, 1])
with c1:
    post_type = st.selectbox(
        "Post type",
        ["Monday Setup",
         "Friday Recap",
         "Mid-week Note",
         "Trade Idea — single thesis",
         "Educational — explainer",
         "Free-form"],
        key="ai_post_type",
    )
with c2:
    target_length = st.selectbox(
        "Target length",
        ["Short (~250 words)", "Medium (~500 words)", "Long (~900 words)"],
        index=1,
        key="ai_post_length",
    )

title_hint = st.text_input(
    "Title or angle (optional — helps the model anchor)",
    placeholder="e.g. 'The belly is screaming buy' or 'Why I'm fading the long-end rally'",
    key="ai_post_title",
)
angle = st.text_area(
    "Your take / specific angle (optional but improves quality)",
    placeholder="One or two sentences on what you want to argue. The model will work the data into your view, not invent one.",
    height=80,
    key="ai_post_angle",
)
tone = st.selectbox(
    "Tone",
    ["Punchy / desk-trader",
     "Educational / explainer",
     "Cautious / measured",
     "Hot-take / opinionated"],
    key="ai_post_tone",
)

# ── Compose system + user messages ────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are 'Macro Manv', a fixed-income trader who writes a Substack on "
    "rates relative-value, curve, and macro themes. You write for other "
    "rates professionals — they know what 2s10s, DV01, carry/roll, fly, and "
    "z-score mean. Don't waste words explaining basics.\n\n"
    "Voice: punchy, opinionated, evidence-based. Short paragraphs. Use the "
    "data given to back specific claims. Avoid filler. Avoid 'in conclusion'. "
    "If the data doesn't support a clean call, say so — don't manufacture "
    "conviction. Markdown output, no emojis unless the user asks for them."
)

user_msg = (
    f"Draft a Substack post.\n\n"
    f"POST TYPE: {post_type}\n"
    f"TARGET LENGTH: {target_length}\n"
    f"TONE: {tone}\n"
    f"TITLE/ANGLE HINT: {title_hint or '(none — you choose)'}\n"
    f"AUTHOR'S ANGLE: {angle or '(none — derive a clean view from the data)'}\n\n"
    f"=== TODAY'S MARKET DATA ===\n{context_block}\n=== END DATA ===\n\n"
    f"Now write the post. Lead with the most interesting thing in the data. "
    f"Use the trade ideas / z-extremes where they support the argument. "
    f"End with a one-line wrap, no 'in conclusion'."
)

if st.button("✍️ Draft post", type="primary", use_container_width=True, key="ai_draft_btn"):
    with st.spinner("Claude is drafting your post…"):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=2500,
                system=[
                    {"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}},
                ],
                messages=[{"role": "user", "content": user_msg}],
            )
            draft = "".join(b.text for b in resp.content if hasattr(b, "text"))
            st.session_state["_ai_last_draft"] = draft
            usage = resp.usage
            st.session_state["_ai_last_usage"] = (
                f"in: {usage.input_tokens} (cache_read: "
                f"{getattr(usage, 'cache_read_input_tokens', 0)}, "
                f"cache_create: {getattr(usage, 'cache_creation_input_tokens', 0)}) · "
                f"out: {usage.output_tokens}"
            )
        except Exception as e:
            st.error(f"Anthropic call failed: {e}")
            st.stop()

# ── Render draft ──────────────────────────────────────────────────────────
draft = st.session_state.get("_ai_last_draft", "")
if draft:
    st.divider()
    st.subheader("📝 Draft")
    st.caption(st.session_state.get("_ai_last_usage", ""))
    edited = st.text_area("Edit before copy/paste",
                          value=draft, height=480, key="_ai_edit_buf")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇️ Download as Markdown",
                           data=edited.encode("utf-8"),
                           file_name=f"draft_{datetime.today().strftime('%Y-%m-%d')}.md",
                           mime="text/markdown",
                           use_container_width=True)
    with c2:
        if st.button("🔄 Re-draft (same data, new attempt)",
                     use_container_width=True, key="_ai_redraft"):
            st.session_state.pop("_ai_last_draft", None)
            st.rerun()

    with st.expander("🔍 Preview rendered", expanded=False):
        st.markdown(edited)
