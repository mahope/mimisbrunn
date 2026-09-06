#!/bin/bash
# Wiki MCP server — klon/opdatér vaulten og kør MCP'en over streamable-http.
# Busybox-fri (bash i python:slim). Kræver GITHUB_TOKEN (contents: read/write) og WIKI_MCP_TOKEN.
set -euo pipefail

: "${GITHUB_TOKEN:?GITHUB_TOKEN mangler}"
: "${WIKI_MCP_TOKEN:?WIKI_MCP_TOKEN mangler}"
REPO_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${WIKI_REPO:?WIKI_REPO missing (owner/repo)}.git"

git config --global user.name "wiki-mcp"
git config --global user.email "wiki-mcp@example.invalid"
git config --global pull.rebase true

if [ ! -d /wiki/.git ]; then
  echo "Cloning wiki repo…"
  git clone --depth 50 "$REPO_URL" /wiki
else
  echo "Wiki repo findes — pull"
  git -C /wiki remote set-url origin "$REPO_URL"
  git -C /wiki pull --rebase -q origin main || git -C /wiki rebase --abort || true
fi

echo "=== Wiki MCP starting on :${WIKI_MCP_PORT:-8765} ==="
exec python /wiki/scripts/wiki-mcp-server.py --transport streamable-http --pull-interval "${WIKI_PULL_INTERVAL:-300}"
