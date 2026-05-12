# Macro Manv — Rates Dashboard

Streamlit-based rates analytics + content engine for the
[Macro Manv Substack](https://manveersahota.substack.com). Built for one
trader, designed for paying subscribers.

> ⚠️ This is a working personal project, not a polished SaaS. The analytics
> are real; production gloss is uneven by design.

## What's in here

- **30+ analytical pages** — yield curves (US/EU/UK/Asia), spreads, scanner,
  regime detector, backtester, DV01-neutral trade builder, vol scorecard, FX,
  inflation, auctions, cross-asset overview, global macro.
- **Content engine** — daily/weekly briefs (markdown + branded PDF), AI post
  drafter (Anthropic), 1080×1080 social cards, RSS-injected headlines.
- **Subscriber tooling** — admin-only A/B test framework, premium gate
  component, Trade-of-the-Week tracker with public performance attribution,
  trade journal, CTA / UTM audit.
- **Infra** — Docker, Cloudflare Worker for CTA click tracking, GitHub Actions
  cron, OpenBB integration where it adds value.

## Quick start

```bash
# Clone, create venv, install
git clone <repo>
cd rates-dashboard
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Add secrets
cp .env.example .env  # then edit
mkdir -p .streamlit && cp .streamlit/secrets.example.toml .streamlit/secrets.toml

# Run
python run.py
# → http://localhost:8501
```

## Project layout

```
rates-dashboard/
├── dashboard/                 # Streamlit UI
│   ├── Home.py                # entry point
│   ├── pages/                 # 38 pages, one file per page
│   ├── components/            # header (grouped nav), controls, news, search, premium gate
│   ├── state.py               # auth, master-df loading, session helpers
│   └── state_url.py           # URL save-state helper
├── fixed_income/              # quant library — DV01, carry/roll, NS, PCA
├── analysis/                  # weekly PDF, alert body, social card renderer, A/B framework
├── data/
│   ├── fetchers/              # FRED, Treasury, ECB, BoE, NY Fed, CFTC, EODHD
│   ├── openbb_data.py         # OpenBB wrapper (keyless endpoints)
│   ├── pipeline.py            # merges all sources → master.parquet
│   └── cache/                 # parquet caches (gitignored)
├── scripts/
│   ├── daily_brief.py         # Substack-ready brief generator (cron'd)
│   ├── send_alert.py          # Mon + Fri email alert (cron'd)
│   └── google_apps_script.js  # alternative serverless cron
├── briefs/                    # generated daily + weekly artefacts (per-date subdirs)
├── cloudflare-worker/         # CTA click tracker (D1-backed)
├── .github/workflows/         # daily-brief, weekly-alert, smoke-test
├── Dockerfile + docker-compose.yml
├── DEPLOY.md                  # Streamlit Cloud / Fly.io / Railway instructions
└── requirements.txt
```

## Navigation

The 38 pages are grouped into 7 top-level categories:

| Pill | Pages |
|---|---|
| 📈 Markets | Yield Curve · Global Curves · Spreads · FX · Real Rates · Cross-Asset · Vol Scorecard · Inflation · Macro |
| 🔬 Analytics | Analysis (Scanner) · Regression · PCA · Correlation · Vol Surface · Regime · Trade Decomposition |
| 🎯 Trade | Builder · Backtester · Tracker · Trade of the Week · Performance · Journal |
| 📅 Events | Auctions · Calendar · CTA Positioning |
| 📨 Publish | Alerts · AI Drafter · Social Cards |
| ⚙️ Admin | A/B Tests · CTA Audit · Subscriber Growth · Reader Polls · Admin · Feature Request |
| 📚 Help | Data Sources · Glossary · User Guide |

Sidebar 🔎 search jumps to any page by keyword.

## Data sources

- **Treasury.gov XML** (primary US Treasury par yields)
- **FRED** via fredapi + pandas-datareader (SOFR, ICE BofA credit, macro, FX,
  TIPS, breakevens, MOVE, ON RRP)
- **ECB SDW** (euro-area AAA yield curve)
- **BoE IADB** (UK gilt yields)
- **TreasuryDirect** (auction calendar + results)
- **NY Fed** (SOFR/TGCR/BGCR)
- **CFTC** (Commitment of Traders)
- **EODHD** (supplementary international govt yields)
- **OpenBB econdb** (Asian sovereign curves, OECD CPI/CLI/unemployment, money supply)
- **RSS** — Substack, Bloomberg, FT, Fed press releases, ECB, BoE

## Deployment

See [DEPLOY.md](./DEPLOY.md) for the full guide. Quick options:

- **Streamlit Community Cloud** — free, ~5 min, no custom domain
- **Fly.io** — $5-10/mo, custom domain, persistent volume for cache
- **Self-hosted via Docker** — `docker compose up --build`

## Scheduled jobs (GitHub Actions)

- `.github/workflows/daily-brief.yml` — weekdays 07:00 ET
- `.github/workflows/weekly-alert.yml` — Mon + Fri 07:00 ET
- `.github/workflows/smoke-test.yml` — every push to main

Configure secrets in Settings → Secrets and variables → Actions:
`FRED_API_KEY`, `DASHBOARD_URL`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`,
`ADMIN_PASSWORD`, `ANTHROPIC_API_KEY` (optional, for AI drafter).

## License

Private / personal project — not currently licensed for redistribution.
