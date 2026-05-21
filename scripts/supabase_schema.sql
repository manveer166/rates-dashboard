-- ───────────────────────────────────────────────────────────────────────
-- Macro Manv beta-tester activity store
--
-- Paste this in Supabase → SQL Editor → New Query → RUN, once, after
-- creating the project. Idempotent — safe to re-run.
--
-- The dashboard's `log_activity()` inserts one row per page view, and
-- `load_activity_df()` reads recent rows for the /Beta_Admin Activity
-- tab. See dashboard/components/beta_users.py.
-- ───────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS beta_activity (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    user_email TEXT         NOT NULL,
    page       TEXT         NOT NULL,
    action     TEXT         NOT NULL DEFAULT 'view',
    extra      JSONB
);

-- "Show me what Alice has been doing" queries
CREATE INDEX IF NOT EXISTS idx_beta_activity_user_email
    ON beta_activity (user_email);

-- "Show me the last 100 events across all users" queries
CREATE INDEX IF NOT EXISTS idx_beta_activity_ts_desc
    ON beta_activity (ts DESC);

-- "Which pages did Alice hit today?" queries
CREATE INDEX IF NOT EXISTS idx_beta_activity_user_ts
    ON beta_activity (user_email, ts DESC);


-- ───────────────────────────────────────────────────────────────────────
-- Sanity-check query (run after dashboard fires its first event):
--   SELECT user_email, COUNT(*) AS views, MAX(ts) AS last_seen
--   FROM beta_activity
--   GROUP BY user_email
--   ORDER BY last_seen DESC;
-- ───────────────────────────────────────────────────────────────────────
