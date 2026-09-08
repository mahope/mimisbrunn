#!/bin/bash
set -e

echo "=== Wiki Agent starting ==="

# Clone wiki repo if not present
if [ ! -d /wiki/.git ]; then
    echo "Cloning wiki repo..."
    git clone https://${GITHUB_TOKEN}@github.com/mahope/llm-wiki.git /wiki
    cd /wiki
    git config user.email "${GIT_AUTHOR_EMAIL:-wiki-agent@example.com}"
    git config user.name "Wiki Agent (Dokploy)"
else
    echo "Wiki repo exists, pulling latest..."
    cd /wiki
    git pull --rebase origin main || true
fi

# Write env vars to a file cron can access
printenv | grep -E '^(HOSTINGER_|RESEND_|GITHUB_|GMAIL_)' > /app/.env.cron

echo "Wiki agent ready. Starting cron..."
cron -f
