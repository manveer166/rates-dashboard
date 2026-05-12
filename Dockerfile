# syntax=docker/dockerfile:1.6
# Macro Manv Rates Dashboard — production image
#
# Build:    docker build -t macromanv-dashboard:latest .
# Run:      docker run -p 8501:8501 --env-file .env macromanv-dashboard:latest
# Test:     curl http://localhost:8501/_stcore/health  → "ok"
#
# Targets (use --target ... to pick):
#   • base         — minimal OS + Python
#   • deps         — pip install (cached layer)
#   • runtime      — final image with code (DEFAULT)

# ─────────────────────────────────────────────────────────────────────────
FROM python:3.13.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# OS deps for matplotlib / kaleido / lxml etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl ca-certificates git \
      libfreetype6 libfontconfig1 \
      libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ─────────────────────────────────────────────────────────────────────────
FROM base AS deps

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────
FROM deps AS runtime

# Copy app code (keep data/cache for the parquet cache; .venv excluded via .dockerignore)
COPY . .

# Create cache dir (mountable as a volume in compose / k8s)
RUN mkdir -p /app/data/cache /app/briefs

EXPOSE 8501

# Healthcheck Streamlit's built-in endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

# Run as a non-root user for security
RUN useradd -m -u 1000 streamlit && chown -R streamlit:streamlit /app
USER streamlit

CMD ["python", "-m", "streamlit", "run", "dashboard/Home.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.headless=true", "--browser.gatherUsageStats=false", \
     "--theme.base=dark", "--theme.primaryColor=#4fc3f7", \
     "--theme.backgroundColor=#0a1628", \
     "--theme.secondaryBackgroundColor=#142847"]
