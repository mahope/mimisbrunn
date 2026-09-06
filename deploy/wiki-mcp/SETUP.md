# Wiki MCP — your second brain on every device

`scripts/wiki-mcp-server.py` exposes the vault as MCP tools: `wiki_search`, `wiki_get`, `wiki_related`,
`wiki_recent`, `wiki_handover`, `wiki_stats`, `wiki_append`, `wiki_create` (plus resources `wiki://schema`, `wiki://index`).

## Local (stdio) — Claude Code / Claude Desktop
```bash
pip install "mcp>=1.12,<2" pyyaml
claude mcp add wiki -s user -- python /path/to/vault/scripts/wiki-mcp-server.py
# macOS with only Python 3.9: use uv
claude mcp add wiki -s user -- uv run --python 3.12 --with "mcp>=1.12,<2" --with pyyaml /path/to/vault/scripts/wiki-mcp-server.py
```

## Remote (Docker / Dokploy) — phone, claude.ai connector, other agents
1. Create a fine-grained GitHub token (this repo only, Contents: read/write) and a random token: `python -c "import secrets;print(secrets.token_urlsafe(48))"`.
2. On the Docker host create `/etc/dokploy/wiki-mcp.env` (chmod 600):
   ```
   GITHUB_TOKEN=github_pat_...
   WIKI_MCP_TOKEN=<random token>
   WIKI_REPO=you/your-vault
   WIKI_PULL_INTERVAL=300
   WIKI_MCP_DOMAIN=wiki-mcp.example.com
   ```
3. Dokploy → new Compose service → this repo, compose path `deploy/wiki-mcp/docker-compose.yml` → Deploy.
   Point DNS for `WIKI_MCP_DOMAIN` at the host (Traefik + Let's Encrypt handle TLS).
4. Verify: `curl https://WIKI_MCP_DOMAIN/health` → `{"ok":true,"pages":N}`; `/mcp` without token → 401. `/` shows a landing page (`deploy/wiki-mcp/landing.html`).
5. Clients:
   - Claude Code: `claude mcp add --transport http wiki-remote https://WIKI_MCP_DOMAIN/mcp --header "Authorization: Bearer <token>"`
   - Claude app / claude.ai: Settings → Connectors → Add custom connector → same URL + header.

## How it behaves
- Index is rebuilt from changed files on every call (cheap for a few thousand pages).
- Writes commit the single file, then `pull --rebase` + push (`WIKI_MCP_PUSH=1`). A failed rebase is aborted, never left half-done.
- Refuses to store text that looks like a password or API key.
- git subprocesses run with `stdin=DEVNULL` and `GIT_TERMINAL_PROMPT=0`, otherwise ssh prompts hijack the stdio transport.

## Security
Bearer token only. Rotate by editing the env file and redeploying. For zero public exposure, drop the Traefik labels and put the host on a private mesh (Tailscale/NetBird).
