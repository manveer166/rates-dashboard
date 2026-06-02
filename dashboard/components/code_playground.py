"""Code-on-data playground — let users prototype their own algos against
the dashboard's data.

Usage from a page:

    from dashboard.components.code_playground import render_code_playground
    render_code_playground(df=master_df)   # df is whatever DataFrame you want exposed

What the user gets:
    • Python text-area
    • A namespace pre-loaded with df, fi (fixed-income lib), np, pd, go (plotly)
    • Run button → executes code, captures stdout, renders a `result` if set
    • Worked examples to crib from

Security:
    • exec() with a custom globals dict. NOT a sandbox.
    • OK for a 14-day beta with NDA'd testers.
    • DO NOT expose this to anonymous public traffic without RestrictedPython
      or similar — would let visitors read st.secrets, write files, etc.
    • The page calls is_admin() / authenticated guards upstream; respect them.
"""

from __future__ import annotations

import contextlib
import io
import traceback
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st


EXAMPLES = {
    "📊 Yield-curve snapshot": """\
# Most recent observation across the curve
latest = df.iloc[-1].dropna()
print("As of:", df.index[-1].date())
print(latest.tail(10))

# Set 'result' to anything (DataFrame, figure, scalar) to render it below
result = latest
""",

    "📈 Realised 1d move vs 30d vol": """\
# Yesterday's moves vs the 30d rolling vol — z-score per tenor
moves   = df.diff().iloc[-1] * 100         # in bps
vols    = df.diff().rolling(30).std().iloc[-1] * 100
zscores = (moves / vols).dropna().sort_values()

result = pd.DataFrame({"move_bps": moves, "vol_30d_bps": vols,
                       "z": zscores}).dropna().sort_values("z")
""",

    "🔄 Custom carry ranking": """\
# Rank tenors by (level - 6m moving average) — a crude richness score
import numpy as np
recent  = df.iloc[-126:]                   # ~6 months
mean    = recent.mean()
current = df.iloc[-1]
richness = (current - mean) * 100          # bps from mean
ranked   = richness.dropna().sort_values()
print("Richest (low):")
print(ranked.head(5))
print()
print("Cheapest (high):")
print(ranked.tail(5))

result = ranked
""",

    "🧮 Use the fi library directly": """\
# fi exposes the same helpers the Scanner uses internally
help(fi)                                   # see what's available

# Example: compute a 5y vs 10y curve carry
# (par yields are in df; fi.carry_*_bps wants annualised yields)
import numpy as np

y5  = df["5Y"].iloc[-1] / 100.0
y10 = df["10Y"].iloc[-1] / 100.0
print(f"5Y={y5*100:.3f}%  10Y={y10*100:.3f}%  steepness={(y10-y5)*100*100:.0f}bps")
""",
}


def render_code_playground(
    df:          pd.DataFrame,
    title:       str = "🐍 Python algorithm sandbox",
    height:      int = 360,
    show_examples: bool = True,
) -> None:
    """Render the code playground as a Streamlit expander.

    Pass any DataFrame as `df`; it's the only required parameter. Common
    fixed-income helpers, numpy, and pandas are pre-imported in the
    sandboxed namespace.
    """
    with st.expander(title, expanded=False):
        st.caption(
            "Prototype your own analytics on the dashboard's data. "
            "`df`, `fi`, `np`, `pd` are pre-loaded. Print whatever you want "
            "with `print(...)`; set a `result` variable (DataFrame, Plotly "
            "figure, or scalar) to have it rendered below."
        )
        st.caption(
            "⚠️ This runs Python on the server. **For NDA'd beta testers "
            "only** — would not be safe to expose to anonymous traffic."
        )

        # ── Starter / example picker ─────────────────────────────────────
        if show_examples:
            ex_cols = st.columns(len(EXAMPLES))
            for i, (label, code) in enumerate(EXAMPLES.items()):
                if ex_cols[i].button(label, key=f"_playground_ex_{i}",
                                     use_container_width=True):
                    st.session_state["_playground_code"] = code

        default_code = st.session_state.get(
            "_playground_code",
            "# Your code here. df, fi, np, pd are available.\n"
            "# Set `result = something` to render it below.\n\n"
            "print(df.tail())\n"
            "result = df.iloc[-1].dropna()\n",
        )

        user_code = st.text_area(
            "Code",
            value=default_code,
            height=height,
            key="_playground_code_area",
            label_visibility="collapsed",
        )

        # ── Run ──────────────────────────────────────────────────────────
        if st.button("▶ Run", type="primary", key="_playground_run",
                     use_container_width=True):
            _run_code(user_code, df)


# ── Internals ────────────────────────────────────────────────────────────
def _build_namespace(df: pd.DataFrame) -> dict:
    """Construct the variables visible to user code."""
    ns: dict = {
        "df":  df,
        "np":  np,
        "pd":  pd,
    }
    # Make the fixed-income helpers available
    try:
        import fixed_income as fi   # type: ignore
        ns["fi"] = fi
    except Exception:
        ns["fi"] = None

    # Optional plotly for chart returns
    try:
        import plotly.graph_objects as go
        ns["go"] = go
    except Exception:
        pass

    return ns


def _run_code(code: str, df: pd.DataFrame) -> None:
    """Exec the code, capture stdout, render any `result` left in scope."""
    if not code or not code.strip():
        st.info("Type some code in the box above and click Run.")
        return

    ns = _build_namespace(df)
    stdout = io.StringIO()
    stderr = io.StringIO()

    try:
        with contextlib.redirect_stdout(stdout), \
             contextlib.redirect_stderr(stderr):
            exec(compile(code, "<playground>", "exec"), ns, ns)
    except Exception:
        st.error(f"❌ Exception while running your code:")
        st.code(traceback.format_exc(), language="python")
        return

    # Surface anything printed
    out = stdout.getvalue()
    if out.strip():
        st.text(out)

    err = stderr.getvalue()
    if err.strip():
        st.warning(f"stderr:\n{err}")

    # If user set a `result`, render it intelligently
    result = ns.get("result")
    if result is None:
        if not out.strip():
            st.info("✅ Ran without errors (no `print` output and no `result` set).")
        return

    st.markdown("**`result` →**")
    try:
        if isinstance(result, pd.DataFrame):
            st.dataframe(result, use_container_width=True)
        elif isinstance(result, pd.Series):
            st.dataframe(result.to_frame(name="value"),
                         use_container_width=True)
        elif "plotly" in type(result).__module__:
            st.plotly_chart(result, use_container_width=True)
        elif hasattr(result, "savefig"):   # matplotlib Figure
            st.pyplot(result)
        else:
            st.write(result)
    except Exception as e:
        st.warning(f"Could not auto-render result ({e}); raw:")
        st.write(result)
