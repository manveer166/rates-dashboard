# Deploying the Macro Manv dashboard

Three deployment paths, ranked by lift vs. control.

**Recommended for launch: Fly.io (option 2)** — real custom domain, scales
auto-stop when idle (~$2-5/mo when traffic is light), one container. Skip
to that section if you don't want to compare options.

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

## 2. Fly.io — recommended launch path

A `fly.toml` is already shipped in this repo with the right settings —
you don't need to write any infra config. The whole flow is ~15 min the
first time.

### Step 0 — buy the domain (if you don't have one)

For `macromanv.com` or `app.macromanv.com`, pick a registrar:

- **Cloudflare Registrar** (~$10/yr `.com`, at-cost pricing) — recommended;
  built-in fast DNS and free SSL fallback. Requires Cloudflare account.
- **Porkbun** (~$10/yr `.com`) — simple UI, free WHOIS privacy.
- **Namecheap** (~$10/yr `.com`) — most familiar, slightly more expensive
  in year 2+.

You can deploy to a `*.fly.dev` URL first and add the custom domain
later — don't let the domain block the deploy.

### Step 1 — install flyctl + sign up

```bash
# macOS
brew install flyctl

# Or:  curl -L https://fly.io/install.sh | sh

fly auth signup        # creates account + adds a credit card (no charge until you exceed free tier)
# If you already have one:
fly auth login
```

Fly's free allowance covers a small Streamlit app well: 3× shared-cpu-1x
machines + 3GB persistent volume + 160GB egress. You'll likely pay $0-3/mo.

### Step 2 — launch (uses the shipped fly.toml)

```bash
cd /path/to/rates-dashboard

# `--copy-config` keeps the fly.toml in this repo as-is. `--no-deploy`
# lets us set secrets before the first push.
fly launch --copy-config --no-deploy

# If the app name is taken, edit fly.toml line 4 and try again.
# Suggested: macromanv-dashboard, macro-manv-rates, rates-manv.
```

### Step 3 — set secrets

These get encrypted at rest on Fly's side. Replace the values with yours
(the `\` continues the line in bash):

```bash
fly secrets set \
    ADMIN_PASSWORD='your-admin-password' \
    AUTH_SECRET="$(openssl rand -hex 32)" \
    DASHBOARD_URL='https://macromanv-dashboard.fly.dev'

# Optional (only if using these features):
fly secrets set \
    ANTHROPIC_API_KEY='sk-...' \
    GEMINI_API_KEY='AIza...' \
    GMAIL_USER='you@gmail.com' \
    GMAIL_APP_PASSWORD='xxxx xxxx xxxx xxxx' \
    FRED_API_KEY='your-fred-key-if-using'
```

The FRED key is **optional** — `pandas_datareader` works without one for
moderate volume. Add it later if you hit rate limits.

### Step 4 — create the cache volume + deploy

```bash
# Volume keeps the parquet cache warm between deploys (saves ~30s of cold-start)
fly volumes create dashboard_cache --size 1 --region lhr

fly deploy
```

First build takes 6-8 min (cold layer cache). Subsequent deploys: ~90s.

When it finishes, open the URL it prints. You should see the Home page,
with no admin badge in the sidebar — that's correct, you need to log in.

### Step 5 — verify

```bash
# Tail logs
fly logs

# Open the live site
fly open

# Check resources
fly status
```

Visit `https://<your-app>.fly.dev`, click "🔒 Admin" in the sidebar, enter
the password you set. You should see the admin pages (Subscriber Sync,
Trade-of-Week write form, etc.).

### Step 6 — point a real domain at it

```bash
# Tell Fly you'll be using this domain — provisions a Let's Encrypt cert
fly certs create app.macromanv.com

# Fly prints two DNS records you need to create at your registrar:
#   A   app.macromanv.com    →  <fly-ipv4>
#   AAAA app.macromanv.com   →  <fly-ipv6>
# Use those exact IPs from the `fly certs show` output.

# After adding the DNS records, verify (cert provisioning takes 1-5 min):
fly certs show app.macromanv.com
```

**Cloudflare-specific DNS note:** if your nameservers are on Cloudflare,
add the records with the orange-cloud proxy **OFF** for the initial cert
provisioning. You can turn proxy ON afterwards if you want Cloudflare's
caching / WAF — but the Streamlit WebSocket will need "Full (strict)" SSL
mode and WebSocket compatibility enabled in Cloudflare's Network panel.

### Step 7 — update DASHBOARD_URL to the custom domain

```bash
fly secrets set DASHBOARD_URL='https://app.macromanv.com'
# Triggers a restart so UTM links in the briefs use the new host.
```

### Cost expectation (Fly)

| Traffic | Estimated monthly |
|---|---|
| <100 visits/day | $0 (auto-stop covers idle) |
| 100-1000 visits/day | $2-5 |
| 1k-5k visits/day | $5-12 |
| Custom domain SSL | free (Let's Encrypt) |

The `min_machines_running = 0` setting in `fly.toml` means Fly hibernates
the machine when idle — first visitor after a quiet stretch waits ~3s
for cold start, then it stays warm while there's traffic.

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
