#!/bin/bash
# Pull wiki changes and send new briefings via Resend
set -e
source /app/.env.cron

cd /wiki
git pull --rebase origin main || true

# Check for new briefings and send
export RESEND_API_KEY
python3 /wiki/scripts/send-briefing.py
