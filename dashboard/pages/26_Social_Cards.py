"""Page 26 — Social Card Generator.

One-click branded image for Instagram / X / Substack notes.  Pulls today's
top scanner trade and renders a 1080×1080 (or story / twitter) PNG with the
same brand palette as the dashboard / weekly PDF.
"""

import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from dashboard.components.controls import render_sidebar_controls
from dashboard.components.header import render_page_header
from dashboard.state import (
    get_master_df, init_session_state, password_gate, is_admin,
)

st.set_page_config(page_title="Social Cards", page_icon="🖼️", layout="wide")
password_gate()
init_session_state()
render_sidebar_controls()
render_page_header(current="Social Cards")

st.title("🖼️ Social Card Generator")
st.caption(
    "One-click branded image for Instagram, X, or Substack notes — "
    "today's top scanner trade rendered against the dashboard's palette."
)
st.divider()

# Lazy import: pulls scanner build path
from scripts.send_alert import build_scanner   # noqa: E402
from analysis.social_card import build_social_card   # noqa: E402

c1, c2, c3 = st.columns([1, 1, 1])
with c1:
    fmt = st.selectbox(
        "Format",
        ["square (1080×1080)", "story (1080×1920)", "twitter (1200×675)"],
        key="sc_fmt",
    )
    fmt_key = fmt.split(" ")[0]
with c2:
    sort_by = st.selectbox("Pick the trade by",
                            ["Sharpe", "E[Ret]", "Z (cheapest)"], key="sc_sort")
with c3:
    st.write("")
    st.write("")
    go = st.button("🖼️ Generate card", type="primary", use_container_width=True,
                    key="sc_go")

def _one_liner(sdf, sort_col: str) -> str:
    """Auto-compose a Twitter/Substack-Note one-liner from the top trade."""
    if sdf.empty: return ""
    top = (sdf.dropna(subset=[sort_col]).nlargest(1, sort_col).iloc[0]
           if sort_col in ("Sharpe", "E[Ret]") else
           sdf.dropna(subset=["Z"]).nsmallest(1, "Z").iloc[0])
    name = top["Trade"].replace("Rcv ", "")
    if top["Type"] == "Fly":   name = name.replace("/", "") + " fly"
    elif top["Type"] == "Curve": name += " curve"
    z = float(top["Z"]); s = float(top["Sharpe"])
    stance = ("trading cheap to history" if z < -0.5 else
              "stretched rich" if z > 0.5 else
              "fairly priced")
    return (f"Today's screen: receive {name}.\n\n"
            f"Sharpe {s:+.2f}, Z {z:+.2f} ({stance}). "
            f"E[Ret] {top['E[Ret]']:+.0f} bps/yr.\n\n"
            f"Full scanner + thesis on the dashboard.\n\n"
            f"#rates #fixedincome #macromanv")


if go:
    with st.spinner("Building social card…"):
        sdf = build_scanner()
        hist_df = get_master_df()
        out_dir = Path(__file__).parent.parent.parent / "briefs" / date.today().isoformat() / "social"
        sort_col = sort_by if sort_by in ("Sharpe", "E[Ret]") else "Z"
        path = build_social_card(sdf, hist_df, out_dir,
                                  sort_by=sort_col, fmt=fmt_key)
        st.session_state["_sc_path"]  = str(path)
        st.session_state["_sc_bytes"] = path.read_bytes()
        st.session_state["_sc_caption"] = _one_liner(sdf, sort_col)

if st.session_state.get("_sc_bytes"):
    st.success(f"✓ Generated: `{Path(st.session_state['_sc_path']).name}`")
    cardcol, sidecol = st.columns([2, 1])
    with cardcol:
        st.image(st.session_state["_sc_bytes"], use_column_width=True)
        st.download_button(
            "⬇️ Download PNG",
            data=st.session_state["_sc_bytes"],
            file_name=Path(st.session_state["_sc_path"]).name,
            mime="image/png",
            use_container_width=True,
        )
    with sidecol:
        st.markdown("**📝 Auto one-liner (Substack Note / X)**")
        caption = st.text_area(
            "Edit before posting",
            value=st.session_state.get("_sc_caption", ""),
            height=240,
            key="_sc_caption_edit",
        )
        st.download_button(
            "⬇️ Download caption",
            data=caption.encode("utf-8"),
            file_name=f"caption_{date.today().isoformat()}.txt",
            mime="text/plain",
            use_container_width=True,
        )
        st.caption(
            "Tip: copy the caption + drag the PNG into a Substack Note "
            "or X post. UTM tags on the dashboard links handle attribution."
        )
else:
    st.info("Click **Generate card** to render today's top RV signal.")
