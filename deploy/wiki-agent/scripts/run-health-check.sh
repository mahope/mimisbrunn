#!/bin/bash
# Weekly client website health check
set -e
source /app/.env.cron

cd /wiki
git pull --rebase origin main || true

python3 /app/scripts/check-client-sites.py

if git diff --quiet && git diff --cached --quiet; then
    echo "$(date) — No health changes."
else
    git add -A
    git commit -m "wiki-agent: weekly health check $(date +%Y-%m-%d)"
    git push origin main
fi
