#!/usr/bin/env python3
"""Export INBOX and Sent from Hostinger IMAP to wiki _sources/."""
import os, re, html
from datetime import datetime, timedelta
from imap_tools import MailBox, AND

EMAIL = os.environ.get("HOSTINGER_EMAIL", "")
PASSWORD = os.environ.get("HOSTINGER_PASSWORD", "")
OUT_BASE = "/wiki/_sources/emails-hostinger"
FOLDERS = ["INBOX", "INBOX.Sent"]

SKIP_FROM = ["noreply", "no-reply", "donotreply", "notifications@", "newsletter",
             "mailer-daemon", "postmaster", "automated@", "system@"]

def should_skip(from_addr, subject):
    fa = (from_addr or "").lower()
    su = (subject or "").lower()
    return any(p in fa for p in SKIP_FROM)

def safe_name(s, n=60):
    s = s or 'untitled'
    s = re.sub(r'[^\w\s-]', '', s).strip()
    s = re.sub(r'\s+', '-', s).lower()
    return s[:n] or 'untitled'

def strip_html(s):
    if not s:
        return ''
    s = re.sub(r'<style[^>]*>.*?</style>', '', s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r'<script[^>]*>.*?</script>', '', s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r'<br\s*/?>', '\n', s, flags=re.IGNORECASE)
    s = re.sub(r'</p>', '\n\n', s, flags=re.IGNORECASE)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    return re.sub(r'\n\s*\n\s*\n+', '\n\n', s).strip()

def export_folder(mb, folder):
    try:
        mb.folder.set(folder)
    except Exception as e:
        print(f"  SKIP {folder}: {e}")
        return 0, 0

    since = datetime.now() - timedelta(days=7)
    exported = skipped = 0

    for msg in mb.fetch(AND(date_gte=since.date()), mark_seen=False):
        try:
            date_str = msg.date.strftime('%Y-%m-%d') if msg.date else 'nodate'
            year_month = date_str[:7] if date_str != 'nodate' else 'unknown'
            from_addr = msg.from_ or 'unknown'
            subject = msg.subject or 'no-subject'

            if should_skip(from_addr, subject):
                skipped += 1
                continue

            body = msg.text or strip_html(msg.html or '')
            if not body or len(body.strip()) < 20:
                skipped += 1
                continue

            folder_safe = folder.replace('INBOX.', '').replace('INBOX', 'Inbox')
            outdir = os.path.join(OUT_BASE, folder_safe, year_month)
            os.makedirs(outdir, exist_ok=True)

            fname = f"{date_str}_{safe_name(from_addr.split('<')[0], 30)}_{safe_name(subject, 50)}.txt"
            path = os.path.join(outdir, fname)

            if os.path.exists(path):
                skipped += 1
                continue

            content = (
                f"FROM: {from_addr}\n"
                f"TO: {', '.join(msg.to) if msg.to else ''}\n"
                f"DATE: {msg.date_str or ''}\n"
                f"SUBJECT: {subject}\n"
                f"FOLDER: {folder}\n\n---\n\n{body}"
            )

            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            exported += 1
        except Exception:
            skipped += 1

    return exported, skipped

def main():
    if not PASSWORD:
        print("HOSTINGER_PASSWORD not set!")
        return

    print(f"Connecting as {EMAIL}...")
    total_e = total_s = 0

    with MailBox("imap.hostinger.com").login(EMAIL, PASSWORD) as mb:
        for folder in FOLDERS:
            e, s = export_folder(mb, folder)
            print(f"  {folder}: exported={e}, skipped={s}")
            total_e += e
            total_s += s

    print(f"Done: {total_e} exported, {total_s} skipped")

if __name__ == "__main__":
    main()
