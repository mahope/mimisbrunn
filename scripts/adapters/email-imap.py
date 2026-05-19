#!/usr/bin/env python3
"""Generic IMAP email exporter. Works with any email provider."""
import os, re, html, sys
from datetime import datetime, timedelta

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

SKIP_FROM = ["noreply", "no-reply", "donotreply", "notifications@",
             "newsletter", "mailer-daemon", "postmaster", "automated@"]

def export_imap(host, email, password, output_dir, days=30, folders=None):
    """Export emails from any IMAP server."""
    try:
        from imap_tools import MailBox, AND
    except ImportError:
        print("Install imap_tools: pip install imap_tools")
        return []

    if folders is None:
        folders = ["INBOX"]

    os.makedirs(output_dir, exist_ok=True)
    since = datetime.now() - timedelta(days=days)
    exported = []

    print(f"Connecting to {host} as {email}...")
    with MailBox(host).login(email, password) as mb:
        for folder in folders:
            try:
                mb.folder.set(folder)
            except Exception as e:
                print(f"  Skip {folder}: {e}")
                continue

            count = 0
            for msg in mb.fetch(AND(date_gte=since.date()), mark_seen=False):
                from_addr = msg.from_ or 'unknown'
                subject = msg.subject or 'no-subject'

                if any(p in from_addr.lower() for p in SKIP_FROM):
                    continue

                body = msg.text or strip_html(msg.html or '')
                if not body or len(body.strip()) < 20:
                    continue

                date_str = msg.date.strftime('%Y-%m-%d') if msg.date else 'nodate'
                year_month = date_str[:7]
                outdir = os.path.join(output_dir, folder.replace('.', '/'), year_month)
                os.makedirs(outdir, exist_ok=True)

                fname = f"{date_str}_{safe_name(from_addr.split('<')[0], 30)}_{safe_name(subject, 50)}.txt"
                path = os.path.join(outdir, fname)

                if os.path.exists(path):
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
                count += 1
                exported.append({"file": fname, "from": from_addr, "subject": subject, "date": date_str})

            print(f"  {folder}: {count} emails exported")

    return exported

# Common IMAP servers
PROVIDERS = {
    "gmail": "imap.gmail.com",
    "outlook": "outlook.office365.com",
    "hotmail": "outlook.office365.com",
    "yahoo": "imap.mail.yahoo.com",
    "hostinger": "imap.hostinger.com",
    "protonmail": "127.0.0.1",  # requires ProtonMail Bridge
    "icloud": "imap.mail.me.com",
    "fastmail": "imap.fastmail.com",
}

if __name__ == "__main__":
    if len(sys.argv) < 4:
        providers = ", ".join(PROVIDERS.keys())
        print(f"Usage: email-imap.py <provider-or-host> <email> <password> [days] [output-dir]")
        print(f"Providers: {providers}")
        print(f"Or use a custom IMAP host: email-imap.py imap.example.com user@example.com password")
        sys.exit(1)

    host_or_provider = sys.argv[1]
    email_addr = sys.argv[2]
    password = sys.argv[3]
    days = int(sys.argv[4]) if len(sys.argv) > 4 else 30

    host = PROVIDERS.get(host_or_provider.lower(), host_or_provider)

    from pathlib import Path
    wiki_root = Path(__file__).resolve().parent.parent.parent
    provider_name = host_or_provider.lower().split('.')[0] if '.' in host_or_provider else host_or_provider
    output = sys.argv[5] if len(sys.argv) > 5 else str(wiki_root / "_sources" / f"emails-{provider_name}")

    folders = ["INBOX"]
    if "hostinger" in host:
        folders = ["INBOX", "INBOX.Sent"]
    elif "gmail" in host:
        folders = ["INBOX", "[Gmail]/Sent Mail"]

    results = export_imap(host, email_addr, password, output, days, folders)
    print(f"\nTotal: {len(results)} emails exported to {output}")
