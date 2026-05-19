#!/usr/bin/env python3
"""Check for new tech intel briefings and send via Resend API.
Run after git pull or as a scheduled task."""
import os, re, json, subprocess
from pathlib import Path
from datetime import date, timedelta

wiki = Path(__file__).resolve().parent.parent
intel_dir = wiki / "_intel"
sent_log = intel_dir / ".sent-briefings.json"

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL = "noreply@mahoje.dk"
TO_EMAIL = "mads@mahoje.dk"

def get_sent_briefings():
    if sent_log.exists():
        return json.loads(sent_log.read_text(encoding="utf-8"))
    return []

def mark_sent(filename):
    sent = get_sent_briefings()
    sent.append(filename)
    sent_log.write_text(json.dumps(sent, indent=2), encoding="utf-8")

def send_email(subject, body):
    import urllib.request
    data = json.dumps({
        "from": FROM_EMAIL,
        "to": [TO_EMAIL],
        "subject": subject,
        "text": body
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json"
        }
    )
    try:
        resp = urllib.request.urlopen(req)
        print(f"  Email sent: {resp.read().decode()}")
        return True
    except Exception as e:
        print(f"  Email failed: {e}")
        return False

def main():
    if not intel_dir.exists():
        print("No _intel/ directory yet.")
        return

    if not RESEND_API_KEY:
        print("RESEND_API_KEY not set. Skipping email send.")
        return

    sent = get_sent_briefings()
    briefings = sorted(intel_dir.glob("*-briefing.md"))

    new_briefings = [b for b in briefings if b.name not in sent]
    if not new_briefings:
        print("No new briefings to send.")
        return

    for briefing in new_briefings:
        content = briefing.read_text(encoding="utf-8")
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', briefing.name)
        briefing_date = date_match.group(1) if date_match else "unknown"

        subject = f"Wiki Tech Intel — {briefing_date}"
        print(f"Sending: {briefing.name}")
        if send_email(subject, content):
            mark_sent(briefing.name)

if __name__ == "__main__":
    main()
