#!/usr/bin/env python3
"""Entry point: launch the Streamlit dashboard.

Auto-uses the local venv (.venv/) if it exists — keeps everything pinned
on Python 3.13 with OpenBB.  Falls back to the current interpreter
otherwise so the script still works in CI / Docker.

Usage:
    python3 run.py                 # launches on default port 8501
    python3 run.py --port 8080     # override port
    python3 run.py --headless      # don't auto-open browser
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
VENV_PY = ROOT / ".venv" / "bin" / "python"


def _python() -> str:
    """Return the venv python if present, else the current interpreter."""
    if VENV_PY.exists():
        return str(VENV_PY)
    return sys.executable


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the Macro Manv dashboard.")
    parser.add_argument("--port", type=int, default=8501,
                        help="Port to bind Streamlit to (default 8501).")
    parser.add_argument("--headless", action="store_true",
                        help="Don't auto-open a browser.")
    args = parser.parse_args()

    app_path = ROOT / "dashboard" / "Home.py"
    if not app_path.exists():
        print(f"ERROR: {app_path} not found.", file=sys.stderr)
        return 2

    py = _python()
    using_venv = py == str(VENV_PY)
    print(f"→ Python: {py} {'(venv)' if using_venv else '(system)'}")
    print(f"→ App:    {app_path}")
    print(f"→ Port:   {args.port}")

    cmd = [
        py, "-m", "streamlit", "run", str(app_path),
        "--server.port", str(args.port),
        "--server.headless", "true" if args.headless else "false",
        "--browser.gatherUsageStats", "false",
        "--theme.base", "dark",
        "--theme.primaryColor", "#4fc3f7",
        "--theme.backgroundColor", "#0a1628",
        "--theme.secondaryBackgroundColor", "#142847",
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
