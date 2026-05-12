# Macro Manv CTA tracker

Cloudflare Worker that wraps every UTM-tagged link with click tracking,
then 302s to the real destination. Closes the gap on the "no click capture"
note that's been on the CTA Audit page.

## Deploy (one-time, ~10 minutes)

```bash
npm install -g wrangler
wrangler login

cd cloudflare-worker
wrangler d1 create cta_clicks          # paste the database_id into wrangler.toml
wrangler d1 execute cta_clicks --file=schema.sql
wrangler deploy
```

You'll get a URL like `https://macromanv-cta.<your-account>.workers.dev`.
For a custom domain, add a route in the Cloudflare dashboard:
`cta.macromanv.com/*` → this worker.

## How the dashboard uses it

Set `CTA_TRACKER_URL` in `.streamlit/secrets.toml`:

```toml
CTA_TRACKER_URL = "https://cta.macromanv.com"
```

Then any helper that builds a UTM link should wrap it through the tracker.
For the brief generator: change the `utm()` function in `scripts/daily_brief.py`:

```python
import base64
def utm(path, campaign, date_str):
    target = f"{DASHBOARD_URL}/{path}?utm_source=substack&utm_medium=brief&utm_campaign={campaign}&utm_content={date_str}"
    if CTA_TRACKER_URL:
        b64 = base64.urlsafe_b64encode(target.encode()).rstrip(b"=").decode()
        return f"{CTA_TRACKER_URL}/go?to={b64}&c={campaign}&u={date_str}"
    return target
```

## Reading the data back

The CTA Audit page in the dashboard polls `https://cta.macromanv.com/clicks?since=YYYY-MM-DD`.
Replace the manual click-count UI with a GET to that endpoint — auto-populated.

## Free-tier limits

- 100,000 requests/day
- 5GB of D1 storage (you'll never hit this — a million clicks ~= 200MB)
- 10ms CPU per request
- No cost until you exceed those

## Privacy

The worker stores:
- IP address (Cloudflare's `cf-connecting-ip` header) — used for unique-visitor counts only
- User-agent (first 256 chars) — coarse device fingerprint
- Referer (first 256 chars)
- Campaign + utm_content (already public in the URL)
- Target URL + timestamp

No personal data is captured. If you want stricter privacy, drop the `ip` and
`ua` columns from the schema.
