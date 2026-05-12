-- D1 schema for CTA click tracking
-- Apply with:
--   wrangler d1 execute cta_clicks --file=schema.sql

CREATE TABLE IF NOT EXISTS clicks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,            -- ISO-8601 UTC
    target      TEXT NOT NULL,            -- final destination URL
    campaign    TEXT,                     -- utm_campaign
    utm_content TEXT,                     -- utm_content (often a date)
    utm_source  TEXT,
    utm_medium  TEXT,
    ip          TEXT,                     -- coarse — for unique-visitor count
    ua          TEXT,                     -- truncated user-agent
    referer     TEXT
);

CREATE INDEX IF NOT EXISTS idx_clicks_ts        ON clicks(ts);
CREATE INDEX IF NOT EXISTS idx_clicks_campaign  ON clicks(campaign);
CREATE INDEX IF NOT EXISTS idx_clicks_content   ON clicks(utm_content);
