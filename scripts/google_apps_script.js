/**
 * Google Apps Script — free cron for Rates Dashboard alerts.
 *
 * HOW TO SET UP:
 *   1. Go to https://script.google.com  and create a new project.
 *   2. Paste this entire file into Code.gs.
 *   3. Set WEBHOOK_URL below to your deployed endpoint (see options below).
 *   4. Run  installTriggers()  once from the editor (Run > installTriggers).
 *      Approve the permissions prompt — it only needs "external fetch".
 *   5. Done. It fires Mon & Fri at 07:00 Eastern (12:00 UTC).
 *
 * DEPLOYMENT OPTIONS (pick one):
 *
 *   A) Streamlit Cloud  — no webhook needed, use a GitHub Action instead
 *      (see .github/workflows/send_alert.yml in the repo).
 *
 *   B) Render / Railway / any always-on server:
 *      Set WEBHOOK_URL to your server's alert endpoint, e.g.
 *        https://your-app.onrender.com/api/send-alert
 *      The script hits that URL; your server runs send_alert.py.
 *
 *   C) Local machine (always-on Mac/PC):
 *      Skip this script entirely and use a local crontab instead:
 *        0 12 * * 1,5 cd /path/to/rates-dashboard && python3 scripts/send_alert.py
 *
 *   D) Google Apps Script only (no server at all):
 *      This script can send the alert email directly using Gmail.
 *      Uncomment the sendDirectEmail() function and call it from
 *      triggerAlert() instead of the UrlFetchApp call.
 */

// ── Config ─────────────────────────────────────────────────────────────────
var WEBHOOK_URL = "https://YOUR-SERVER.onrender.com/api/send-alert";
var SECRET_TOKEN = "change-me-to-a-random-string"; // shared secret for auth
var TIMEZONE = "America/New_York";
var ALERT_HOUR = 7;   // 7 AM Eastern
var ALERT_MINUTE = 0;

// ── Install triggers (run once manually) ────────────────────────────────
function installTriggers() {
  // Remove any existing triggers from this project
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    ScriptApp.deleteTrigger(triggers[i]);
  }

  // Monday at 07:00 ET
  ScriptApp.newTrigger("triggerAlert")
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(ALERT_HOUR)
    .nearMinute(ALERT_MINUTE)
    .inTimezone(TIMEZONE)
    .create();

  // Friday at 07:00 ET
  ScriptApp.newTrigger("triggerAlert")
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.FRIDAY)
    .atHour(ALERT_HOUR)
    .nearMinute(ALERT_MINUTE)
    .inTimezone(TIMEZONE)
    .create();

  Logger.log("Triggers installed: Monday & Friday at " +
             ALERT_HOUR + ":" + ("0" + ALERT_MINUTE).slice(-2) + " " + TIMEZONE);
}


// ── Main trigger function ───────────────────────────────────────────────
function triggerAlert() {
  try {
    var response = UrlFetchApp.fetch(WEBHOOK_URL, {
      method: "post",
      contentType: "application/json",
      headers: {
        "Authorization": "Bearer " + SECRET_TOKEN
      },
      payload: JSON.stringify({
        source: "google-apps-script",
        timestamp: new Date().toISOString()
      }),
      muteHttpExceptions: true
    });

    var code = response.getResponseCode();
    var body = response.getContentText().substring(0, 500);

    if (code >= 200 && code < 300) {
      Logger.log("Alert sent successfully (" + code + "): " + body);
    } else {
      Logger.log("Alert endpoint returned " + code + ": " + body);
      // Optionally notify yourself of failures:
      // MailApp.sendEmail("you@gmail.com", "Alert cron failed", "HTTP " + code + "\n" + body);
    }
  } catch (e) {
    Logger.log("Alert trigger error: " + e.message);
  }
}


// ── Alternative: send email directly from Apps Script ────────────────────
// Uncomment and use this if you don't have a server.
// This won't run the full scanner — it just sends a reminder email.
// For the full scanner output, use option B or C above.

/*
function sendDirectReminder() {
  var now = Utilities.formatDate(new Date(), TIMEZONE, "dd MMM yyyy");
  var subject = "Rates Alert Reminder — " + now;
  var body = "This is your scheduled reminder to check the Rates Dashboard.\n\n" +
             "Open the dashboard to see the latest scanner results:\n" +
             "https://your-app.streamlit.app\n\n" +
             "— Macro Manv Rates Dashboard";

  MailApp.sendEmail({
    to: "manveer166@gmail.com",
    subject: subject,
    body: body
  });

  Logger.log("Reminder email sent for " + now);
}
*/
