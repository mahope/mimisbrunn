#!/bin/bash
# Wiki MCP server — klon/opdatér vaulten og kør MCP'en over streamable-http.
# Busybox-fri (bash i python:slim). Kræver GITHUB_TOKEN (contents: read/write) og WIKI_MCP_TOKEN.
set -euo pipefail

: "${GITHUB_TOKEN:?GITHUB_TOKEN mangler}"
: "${WIKI_MCP_TOKEN:?WIKI_MCP_TOKEN mangler}"
REPO="${WIKI_REPO:-mahope/llm-wiki}"
REPO_URL="https://github.com/${REPO}.git"

git config --global user.name "wiki-mcp"
git config --global user.email "wiki-mcp@mahope.dk"
git config --global pull.rebase true
# Tokenet leveres af en credential-helper der laeser env-varen paa kaldstidspunktet.
# Enkeltcitationstegn er vigtige: konfigurationen gemmer teksten, ikke vaerdien, saa
# tokenet havner hverken i /root/.gitconfig eller i /wiki/.git/config paa volumen (issue #28).
git config --global credential.helper '!f() { echo username=x-access-token; echo "password=${GITHUB_TOKEN}"; }; f'

if [ ! -d /wiki/.git ]; then
  echo "Cloning wiki repo…"
  git clone --depth 50 "$REPO_URL" /wiki
else
  echo "Wiki repo findes — pull"
  # set-url rydder ogsaa en aeldre URL med indlejret token op i eksisterende volumener.
  git -C /wiki remote set-url origin "$REPO_URL"
  git -C /wiki pull --rebase -q origin main || git -C /wiki rebase --abort || true
fi

echo "=== Wiki MCP starting on :${WIKI_MCP_PORT:-8765} ==="
exec python /wiki/scripts/wiki-mcp-server.py --transport streamable-http --pull-interval "${WIKI_PULL_INTERVAL:-300}"
