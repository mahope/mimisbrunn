#!/bin/bash
# wiki-inbox: klon/opdatér vaulten og kør Telegram-botten.
set -euo pipefail
: "${GITHUB_TOKEN:?GITHUB_TOKEN mangler}"
: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN mangler}"
: "${WIKI_REPO:?WIKI_REPO mangler (owner/repo)}"
REPO_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${WIKI_REPO}.git"

git config --global user.name "wiki-inbox"
git config --global user.email "wiki-inbox@example.invalid"
git config --global pull.rebase true

if [ ! -d /wiki/.git ]; then
  git clone --depth 50 "$REPO_URL" /wiki
else
  git -C /wiki remote set-url origin "$REPO_URL"
  git -C /wiki pull --rebase -q origin main || git -C /wiki rebase --abort || true
fi

exec python /app/bot.py
