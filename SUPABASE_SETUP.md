# Supabase setup — persistent beta-tester activity

Why: Streamlit Cloud's filesystem is **ephemeral** — `data/beta_activity.jsonl`
gets wiped on every container restart (which happens on every `git push`
and roughly daily idle). Without Supabase, the /Beta_Admin Activity tab
shows only recent activity from the current container life.

With Supabase wired up, every page view + login is persisted in a real
Postgres DB. The dashboard transparently uses Supabase when configured
and falls back to the local JSONL file when not.

**Time:** ~6 minutes end to end. No `pip install` needed — the client
uses `httpx` (already in requirements) to hit Supabase's REST API
directly. Lighter and more reliable than the `supabase-py` package.

---

## 1. Create a Supabase project

1. Go to [supabase.com](https://supabase.com) → **Start your project** → sign in with GitHub.
2. **New project** → name `macro-manv-beta` → region `London (eu-west-2)` (or whatever's nearest to Streamlit Cloud's US-East default — Frankfurt is fine).
3. Set a database password — save it in your password manager. You will not need it for the dashboard (we use the service key instead), but Supabase wants one.
4. Pick the **Free** tier. 500 MB DB, unlimited rows. Enough for 100+ testers × 6 months.
5. Wait ~90 seconds for the project to spin up.

## 2. Create the activity table

1. In the Supabase project sidebar → **SQL Editor** → **+ New query**.
2. Open `scripts/supabase_schema.sql` from this repo, copy the whole file.
3. Paste into the editor → **Run** (or Cmd+Enter).
4. You should see `Success. No rows returned`.

Sanity-check the table:
1. Sidebar → **Table Editor** → you should see `beta_activity` listed.

## 3. Grab the credentials

1. Sidebar → **Project Settings** (the gear icon, bottom-left) → **API**.
2. You'll see two values:
   - **Project URL** — looks like `https://abcdefghijklmno.supabase.co`
   - **service_role key** — long JWT string starting with `eyJh...`. **This is the secret one — do not share it publicly. It bypasses Row Level Security.**

Copy both.

## 4. Add them to Streamlit Cloud secrets

1. Open [share.streamlit.io](https://share.streamlit.io) → your app → **⋮** → **Settings** → **Secrets**.
2. Append these two lines:
   ```toml
   SUPABASE_URL = "https://abcdefghijklmno.supabase.co"
   SUPABASE_SERVICE_KEY = "eyJh...your-long-service-role-key-here"
   ```
3. **Save**. Streamlit reloads the secrets within ~30 seconds — no redeploy required.

## 5. Add them to your local `.streamlit/secrets.toml` too

(So local dev mirrors prod.)

```toml
SUPABASE_URL = "https://abcdefghijklmno.supabase.co"
SUPABASE_SERVICE_KEY = "eyJh...your-long-service-role-key-here"
```

`.streamlit/secrets.toml` is already in `.gitignore`, so no risk of committing it.

## 6. Verify

After ~30 seconds:

1. Log in to the dashboard (as admin or as `beta01@macromanv.com`).
2. Visit a few pages — Scanner, Backtester, Methodology.
3. Open **Beta Admin → Activity** tab.
4. You should see one row per page visit, ordered most-recent-first.
5. Go back to Supabase → **Table Editor → beta_activity** — the same rows should be there.

If the Activity tab is empty after you've visited pages, the dashboard fell back to JSONL — check Streamlit logs for a Supabase connection error and verify the URL + key.

---

## Sanity query (run in Supabase SQL Editor any time)

```sql
SELECT user_email,
       COUNT(*)            AS views,
       COUNT(DISTINCT page) AS distinct_pages,
       MAX(ts)              AS last_seen
FROM beta_activity
GROUP BY user_email
ORDER BY last_seen DESC;
```

This is the same shape as the "per-user usage" table on /Beta_Admin —
useful when you want to query straight from the DB.

---

## What happens if Supabase goes down?

The dashboard catches the connection error and silently falls back to
the local JSONL file for that container's lifetime. Reads on the Activity
tab will show only what's been logged in the current container.
When Supabase recovers, the next write/read switches back automatically.

---

## Cost

- Free tier covers everything described here (500 MB DB, unlimited rows,
  unlimited API requests on the free tier within fair-use limits).
- 20 testers × 50 page views/day × 14 days ≈ 14,000 rows ≈ <1 MB. You'll
  never see a bill at this scale.
