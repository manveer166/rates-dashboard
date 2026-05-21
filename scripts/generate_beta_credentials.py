#!/usr/bin/env python3
"""Pre-generate N approved beta-tester credential slots.

Use case: you've BCC'd a cohort with the cover letter and want N fresh
(login, password) pairs ready to hand out as signed NDAs come back.

Outputs
-------
  • data/beta_signups.json
        N pre-approved records — status=approved, password hashed,
        all "real" fields (name, org, role) blank to fill in later.

  • data/beta_credentials_master.csv
        Plaintext one-shot record of (slot, login_email, password) plus
        empty columns to track assignment. The cleartext password lives
        ONLY here — beta_signups.json stores the hash. Don't commit this
        file (data/ is gitignored).

Usage
-----
    python scripts/generate_beta_credentials.py            # 20 slots
    python scripts/generate_beta_credentials.py 5          # 5 slots

Re-runs safely: appends to existing data instead of overwriting. Slot
numbers continue from the highest existing betaNN.
"""

from __future__ import annotations

import csv
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.components.beta_users import (    # noqa: E402
    _gen_password, _gen_salt, _hash_password, SIGNUPS_PATH,
)

CREDS_CSV   = ROOT / "data" / "beta_credentials_master.csv"
SLOT_DOMAIN = "macromanv.com"


def _load_existing() -> list[dict]:
    if SIGNUPS_PATH.exists():
        try:
            return json.loads(SIGNUPS_PATH.read_text())
        except Exception:
            return []
    return []


def _next_slot_n(existing: list[dict]) -> int:
    """Highest existing betaNN slot — so we don't reuse numbers."""
    max_n = 0
    for r in existing:
        em = (r.get("email") or "").lower()
        if em.startswith("beta") and "@" in em:
            try:
                n = int(em.split("@")[0].replace("beta", ""))
                max_n = max(max_n, n)
            except ValueError:
                pass
    return max_n


def generate(count: int = 20) -> list[dict]:
    existing  = _load_existing()
    start     = _next_slot_n(existing) + 1
    now       = datetime.utcnow().isoformat() + "Z"

    new_rows  = []
    cleartext = []

    for i in range(count):
        n           = start + i
        slot        = f"beta{n:02d}"
        login_email = f"{slot}@{SLOT_DOMAIN}"
        pw          = _gen_password()
        salt        = _gen_salt()

        new_rows.append({
            "id":                  str(uuid.uuid4()),
            "email":               login_email,
            "name":                "",
            "organisation":        "",
            "role":                "",
            "linkedin":            "",
            "substack_email":      "",
            "experience":          "",
            "why_beta":            "pre-generated cohort slot",
            "agreed_terms":        True,
            "requested_at":        now,
            "status":              "approved",
            "approved_at":         now,
            "approved_by":         "manveer (pre-generated)",
            "denied_reason":       None,
            "password_hash":       _hash_password(pw, salt),
            "password_salt":       salt,
            "credentials_sent_at": None,
            "last_login_at":       None,
        })
        cleartext.append({
            "slot":                  slot,
            "login_email":           login_email,
            "password":              pw,
            "email_sent":            "",   # cover-letter recipient (you fill)
            "email_replied":         "",   # "TRUE" / "FALSE" tickbox
            "assigned_to_real_name": "",
            "assigned_to_real_email":"",
            "organisation":          "",
            "assigned_at":           "",
            "credentials_sent_at":   "",
        })

    # Persist JSON
    SIGNUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIGNUPS_PATH.write_text(
        json.dumps(existing + new_rows, indent=2, default=str)
    )

    # Append cleartext to CSV
    csv_exists = CREDS_CSV.exists()
    CREDS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with CREDS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cleartext[0].keys())
        if not csv_exists:
            w.writeheader()
        for row in cleartext:
            w.writerow(row)

    return cleartext


def main() -> None:
    count = 20
    if len(sys.argv) > 1:
        try:
            count = int(sys.argv[1])
        except ValueError:
            print(f"Usage: {sys.argv[0]} [count]   (default 20)")
            sys.exit(1)

    creds = generate(count)

    print()
    print(f"✅ Generated {len(creds)} pre-approved beta credential slots")
    print(f"   JSON store:  {SIGNUPS_PATH.relative_to(ROOT)}")
    print(f"   Cleartext :  {CREDS_CSV.relative_to(ROOT)}")
    print()
    print(f"  {'Slot':<8} {'Login email':<30} {'Password':<22}")
    print(f"  {'-'*8} {'-'*30} {'-'*22}")
    for c in creds:
        print(f"  {c['slot']:<8} {c['login_email']:<30} {c['password']:<22}")
    print()
    print("Hand out one row to each tester as their signed NDA comes back.")
    print("Track real names/emails in the CSV as you go.")
    print()


if __name__ == "__main__":
    main()
