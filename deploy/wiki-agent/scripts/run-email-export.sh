#!/bin/bash
# Export Hostinger emails via IMAP and push to wiki repo
set -e
source /app/.env.cron

echo "$(date) — Starting Hostinger email export..."

cd /wiki
git pull --rebase origin main || true

python3 /app/scripts/export-emails.py

# Check if there are new files
if git diff --quiet && git diff --cached --quiet; then
    echo "$(date) — No new emails."
else
    git add _sources/emails-hostinger/
    git commit -m "wiki-agent: email export $(date +%Y-%m-%d-%H%M)"
    git push origin main
    echo "$(date) — New emails pushed to GitHub."
fi
