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

if st.session_state.get("_sc_bytes"):
    st.success(f"✓ Generated: `{Path(st.session_state['_sc_path']).name}`")
    st.image(st.session_state["_sc_bytes"], use_column_width=False)
    st.download_button(
        "⬇️ Download PNG",
        data=st.session_state["_sc_bytes"],
        file_name=Path(st.session_state["_sc_path"]).name,
        mime="image/png",
        use_container_width=True,
    )
    st.caption(
        "Tip: drop this straight into Substack as a header image, or post "
        "to Instagram. The deep links from your weekly brief and the dashboard "
        "are already UTM-tagged so you can attribute the click-throughs."
    )
else:
    st.info("Click **Generate card** to render today's top RV signal.")
