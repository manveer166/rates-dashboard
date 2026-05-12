# Deploying the Macro Manv dashboard

Three deployment paths, ranked by lift vs. control.

---

## 1. Streamlit Community Cloud — easiest (free, ~5 min)

**When to use:** want a public URL TODAY, don't care about custom domain.

1. Push this repo to a public or private GitHub repo
2. Visit [streamlit.io/cloud](https://streamlit.io/cloud) → sign in with GitHub → "New app"
3. Pick the repo, main branch, file = `dashboard/Home.py`, Python 3.13
4. **Secrets**: copy the contents of your local `.streamlit/secrets.toml` into the dashboard's "Secrets" panel
5. Deploy

Your URL: `https://<repo>.streamlit.app`. Free tier hibernates after inactivity; first hit takes ~10s to wake.

**Limitations:**
- 1 GB RAM, 1 CPU
- No custom domain on free tier
- Public repo recommended (private requires paid)

---

## 2. Fly.io — best balance (free trial → $5-10/mo)

**When to use:** want a real domain, persistent process, control over scaling. Recommended.

```bash
# One-time
brew install flyctl
flyctl auth signup

# Set up the app (run from the project root)
flyctl launch --copy-config --no-deploy --name macromanv-dashboard
flyctl secrets set \
    DASHBOARD_URL="https://macromanv-dashboard.fly.dev" \
    ADMIN_PASSWORD="..." \
    AUTH_SECRET="$(openssl rand -hex 32)" \
    GMAIL_USER="..." \
    GMAIL_APP_PASSWORD="..." \
    FRED_API_KEY="..." \
    ANTHROPIC_API_KEY="..."

# Add a volume so the parquet cache survives restarts
flyctl volumes create dashboard_cache --size 1 --region <near-you>

# Deploy
flyctl deploy
```

Add this to `fly.toml` (created by `flyctl launch`):

```toml
[mounts]
  source = "dashboard_cache"
  destination = "/app/data/cache"

[[services]]
  internal_port = 8501
  protocol = "tcp"

  [[services.ports]]
    handlers = ["http"]
    port = 80

  [[services.ports]]
    handlers = ["tls", "http"]
    port = 443

  [services.http_checks]
    interval = "30s"
    grace_period = "10s"
    method = "get"
    path = "/_stcore/health"

[[vm]]
  size = "shared-cpu-1x"
  memory = "1gb"
```

Custom domain: `flyctl certs create dashboard.macromanv.com`, point a CNAME at the fly.dev address.

---

## 3. Railway — middle ground (free trial → ~$5/mo)

```bash
brew install railway
railway login
railway init
railway up
# Sets env vars via:
railway variables set DASHBOARD_URL="https://..."
```

Railway auto-detects the Dockerfile. Custom domain in dashboard. No volumes — use external Postgres for state if scaling beyond one instance.

---

## Local production-equivalent (Docker)

```bash
# Create .env from .env.example
cp .env.example .env
# Edit .env with your secrets

# Build + run
docker compose up --build -d

# Logs
docker compose logs -f dashboard

# Stop
docker compose down
```

Visit `http://localhost:8501`. Volumes persist the parquet cache and briefs/ across restarts.

---

## What to set up after deploying

1. **Update `DASHBOARD_URL`** in `.streamlit/secrets.toml` to your real URL — all UTM links emitted by the briefs / weekly PDF will point here.
2. **Set up the CTA redirect endpoint** (see `/cloudflare-worker/` in this repo) so click-through analytics actually populate the CTA Audit page.
3. **Schedule the daily brief** — your host's cron or GitHub Action:
   ```yaml
   # .github/workflows/daily-brief.yml
   on:
     schedule:
       - cron: '0 11 * * 1-5'  # 07:00 ET, weekdays
   ```
4. **Schedule the weekly alert** — Mon + Fri 07:00 ET:
   ```cron
   0 11 * * 1,5 docker compose exec -T dashboard python scripts/send_alert.py
   ```
5. **Update DNS** to your custom domain (`dashboard.macromanv.com`).
6. **Test the email flow** by sending yourself the weekly PDF first before opening the floodgates to subscribers.

---

## Monitoring

The Streamlit health check (`/_stcore/health`) returns `ok` plain text. Hook it into:
- Fly.io / Railway / k8s native health probes (already configured in `Dockerfile` and `fly.toml`)
- UptimeRobot / BetterStack / Healthchecks.io for external alerts
- Posthog / Plausible (lightweight analytics — drop the JS snippet into Home.py)

---

## Costs roughly

| Option | Monthly | Custom domain |
|---|---|---|
| Streamlit Cloud free | $0 | ❌ |
| Streamlit Cloud Pro | $20 | ✅ |
| Fly.io shared-cpu-1x + 1GB RAM | ~$5-10 | ✅ |
| Railway hobby | $5 + usage | ✅ |
| Your own VPS (Hetzner CX11) | €4.51 | ✅ (any DNS) |
