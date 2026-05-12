/**
 * Macro Manv CTA tracker — Cloudflare Worker.
 *
 * Routes:
 *   GET /go?to=<base64url>&c=<campaign>&u=<utm_content>
 *     Logs the click to D1 then 302s to the decoded target URL.
 *   GET /clicks?since=YYYY-MM-DD&campaign=…
 *     Returns JSON aggregates the dashboard's CTA Audit page reads.
 *
 * Deploy:
 *   npm install -g wrangler
 *   wrangler login
 *   wrangler d1 create cta_clicks   # paste the database_id into wrangler.toml
 *   wrangler d1 execute cta_clicks --file=schema.sql
 *   wrangler deploy
 *
 * URL format the dashboard now emits:
 *   https://cta.macromanv.com/go?to=<b64url(target)>&c=morning_scan&u=2026-05-11
 */

const ALLOWED_HOSTS = [
  "macromanv.substack.com",
  "manveersahota.substack.com",
  // your dashboard URL — set DASHBOARD_HOST at deploy time
];

function b64urlDecode(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  return atob(s);
}

function clientIp(req) {
  return req.headers.get("cf-connecting-ip") || "unknown";
}

function jsonHeaders(extra = {}) {
  return {
    "content-type": "application/json",
    "access-control-allow-origin": "*",
    ...extra,
  };
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);

    // ── /go — log click + redirect ─────────────────────────────────────
    if (url.pathname === "/go") {
      const to = url.searchParams.get("to");
      if (!to) return new Response("missing ?to", { status: 400 });
      let target;
      try {
        target = b64urlDecode(to);
        const tu = new URL(target);
        if (!ALLOWED_HOSTS.some((h) => tu.host.endsWith(h))) {
          return new Response("destination not allowed", { status: 400 });
        }
      } catch {
        return new Response("invalid ?to", { status: 400 });
      }

      const row = {
        ts:           new Date().toISOString(),
        target:       target,
        campaign:     url.searchParams.get("c")   || "",
        utm_content:  url.searchParams.get("u")   || "",
        utm_source:   url.searchParams.get("s")   || "",
        utm_medium:   url.searchParams.get("m")   || "",
        ip:           clientIp(req),
        ua:           (req.headers.get("user-agent") || "").slice(0, 256),
        referer:      (req.headers.get("referer")    || "").slice(0, 256),
      };

      // Best-effort: don't block the redirect on DB failure
      try {
        await env.DB.prepare(`
          INSERT INTO clicks (ts, target, campaign, utm_content, utm_source,
                              utm_medium, ip, ua, referer)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        `).bind(row.ts, row.target, row.campaign, row.utm_content,
                row.utm_source, row.utm_medium, row.ip, row.ua, row.referer)
          .run();
      } catch (e) {
        console.error("D1 insert failed:", e.message);
      }

      return Response.redirect(target, 302);
    }

    // ── /clicks — JSON for the dashboard CTA Audit page ────────────────
    if (url.pathname === "/clicks") {
      const since = url.searchParams.get("since") || "2026-01-01";
      const campaign = url.searchParams.get("campaign");

      let q = `
        SELECT campaign, utm_content,
               COUNT(*) AS clicks,
               COUNT(DISTINCT ip) AS unique_ips,
               MIN(ts) AS first_click,
               MAX(ts) AS last_click
        FROM clicks
        WHERE ts >= ?
      `;
      const binds = [since];
      if (campaign) {
        q += " AND campaign = ?";
        binds.push(campaign);
      }
      q += " GROUP BY campaign, utm_content ORDER BY clicks DESC LIMIT 500";

      const { results } = await env.DB.prepare(q).bind(...binds).all();
      return new Response(JSON.stringify({ since, campaign, rows: results }),
                          { headers: jsonHeaders() });
    }

    // ── /health ────────────────────────────────────────────────────────
    if (url.pathname === "/health") {
      return new Response("ok", { status: 200 });
    }

    return new Response("Macro Manv CTA tracker. Routes: /go, /clicks, /health",
                        { status: 200 });
  },
};
