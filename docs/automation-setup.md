# Automation Setup

## Level 1: Claude Code Hooks (automatic)

These work out of the box in any Claude Code session:

- **PostToolUse (Edit/Write):** `scripts/wiki-autocommit.py` commits only the wiki file you changed (+ regenerated index). Never `git add -A`; a failed `pull --rebase` is aborted, not left half-done. Set `WIKI_AUTOPUSH=1` to push.
- **PreCompact:** Auto-runs `/wiki-learn` before context compaction
- **SessionStart:** Checks for active handover, and `scripts/wiki-context.py` prints the wiki pages that match the project folder you opened

To enable, add to your `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "prompt",
            "prompt": "Compaction is about to happen. Run /wiki-learn to preserve durable knowledge from this conversation. If mid-task, also run /wiki-handover.",
            "timeout": 120
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python {{WIKI_PATH}}/scripts/wiki-autocommit.py",
            "timeout": 30,
            "async": true
          }
        ]
      }
    ]
  }
}
```

Replace `{{WIKI_PATH}}` with your actual vault path.

## Level 2: Scheduled Remote Agents (requires Claude Pro/Max)

Create these via `/schedule` in Claude Code:

### Gmail Ingest (weekdays 08:00)
Scans recent Gmail threads and enriches wiki entities.
Requires: Gmail MCP connector on claude.ai.

### Tech Intel Scanner (Mon/Wed/Fri 08:00)
Scans tech news sources relevant to your stack.
Customize the source list and rotation for your tools.

### Weekly Digest (Mondays 07:30)
Generates a weekly summary of wiki activity.

### Weekly Lint + Calendar (Sundays 20:00)
Quality check + calendar enrichment.
Requires: Google Calendar MCP connector.

## Level 3: Dokploy/Docker Service (24/7)

For always-on automation that doesn't require your PC:

See `deploy/wiki-agent/SETUP.md` for deployment instructions.

Jobs:
- Email export from IMAP (every 4 hours)
- Git pull + send briefings (every 30 min)
- Dashboard generation (daily)
- Client website health check (weekly)

## Level 4: Email Briefings (optional)

Requires a [Resend](https://resend.com) account with a verified domain.

Set `RESEND_API_KEY` as environment variable. The `send-briefing.py` script sends new `_intel/*-briefing.md` files as emails.
