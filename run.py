"""Entry point: launch the Streamlit dashboard."""
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    app_path = Path(__file__).parent / "dashboard" / "Home.py"
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path),
         "--server.headless", "false",
         "--theme.base", "dark",
         "--theme.primaryColor", "#00D4FF",
         "--theme.backgroundColor", "#0e1117",
         "--theme.secondaryBackgroundColor", "#161b27"],
        check=True,
    )
