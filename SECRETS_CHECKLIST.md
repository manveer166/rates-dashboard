# Secrets checklist

Single page reference: every credential, where to get it, where to paste it.

## What you need

| Secret name | Required? | Where to get it |
|---|---|---|
| `FRED_API_KEY` | **Yes** | https://fred.stlouisfed.org/docs/api/api_key.html (free, 32 chars) |
| `ADMIN_PASSWORD` | **Yes** | Whatever you pick — used to log in as admin |
| `AUTH_SECRET` | **Yes** | Generate with `openssl rand -hex 32` |
| `DASHBOARD_URL` | **Yes** | Will be the public URL once deployed (e.g. `https://macromanv-dashboard.fly.dev`) |
| `GMAIL_USER` | If sending emails | The Gmail address that sends alerts |
| `GMAIL_APP_PASSWORD` | If sending emails | https://myaccount.google.com → Security → App passwords (16 chars, not your real password) |
| `ANTHROPIC_API_KEY` | If using AI Drafter | https://console.anthropic.com (starts `sk-ant-`) |
| `VIEWER_PASSWORDS` | Optional | Comma-separated `password:label` pairs for shared viewer access |

## Where to paste them

### 1. Streamlit Community Cloud
After creating the app:
1. Dashboard → your app → **Settings → Secrets**
2. Paste the **entire `.streamlit/secrets.toml`** contents (TOML format)
3. Save — app auto-restarts

### 2. Fly.io
```bash
flyctl secrets set \
    FRED_API_KEY="..." \
    ADMIN_PASSWORD="..." \
    AUTH_SECRET="$(openssl rand -hex 32)" \
    DASHBOARD_URL="https://macromanv-dashboard.fly.dev" \
    GMAIL_USER="..." \
    GMAIL_APP_PASSWORD="..." \
    ANTHROPIC_API_KEY="..."
```

### 3. GitHub Actions (for daily-brief + weekly-alert workflows)
**URL: https://github.com/manveer166/rates-dashboard/settings/secrets/actions**

Click **"New repository secret"** for each one:

| Name | Value |
|---|---|
| `FRED_API_KEY` | from above |
| `ADMIN_PASSWORD` | from above |
| `DASHBOARD_URL` | from above |
| `GMAIL_USER` | from above |
| `GMAIL_APP_PASSWORD` | from above |
| `ANTHROPIC_API_KEY` | from above (optional) |

Once set, the daily/weekly workflows will run automatically at 11:00 UTC.

### 4. Local development
Just edit `.streamlit/secrets.toml` (it's already in `.gitignore`, won't be committed).

---

## Quick verify

After setting secrets in any target, verify the dashboard reads them:

```bash
# Locally
python -c "
from dashboard.state import _secret
for k in ['ADMIN_PASSWORD','FRED_API_KEY','DASHBOARD_URL','GMAIL_USER']:
    v = _secret(k, '')
    print(f'{k:25} = {(v[:10] + \"...\") if v else \"❌ MISSING\"}')
"
```

If your dashboard is live, hit `/Sources` — it'll show which secrets are loaded (without exposing values).
