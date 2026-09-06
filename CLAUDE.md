# CLAUDE.md — Second Brain (Mimisbrunn)

## LLM Wiki — Persistent Knowledge Base

This vault is a Git-versioned LLM Wiki in Obsidian.

### Auto-fetch (at session start and ongoing)
- When working with a **client, project, tool, or concept**, search the wiki first: `entities/` with Grep or Glob.
- Before asking the user something you might already know, check the wiki.
- Wiki index: `_index.md` gives an overview of all entities.
- Schema: `_schema.md` defines rules and conventions.

### Auto-save (ongoing — this is IMPORTANT)

The wiki grows primarily through conversations. Every session is an opportunity to enrich it.

**TRIGGERS — update the wiki when you encounter:**
- A new contact or client is mentioned
- A client's tech stack changes
- A project starts, ends, or changes status
- A new tool is introduced or evaluated
- Contact info (email, phone, website) is mentioned
- Relationships between entities are discovered
- Personal milestones, plans, or decisions are mentioned

**HOW to save:**
1. Search if the entity already exists: `Grep` in `entities/`
2. If yes: Read the page, add new info, update `last_updated`
3. If no: Create new page with correct frontmatter (see `_schema.md`)
4. Set `confidence: medium` on new facts from conversations
5. Add `[[wikilinks]]` to related entities
6. Add provenance: `> Source: conversation YYYY-MM-DD`

**Rules:**
- Do NOT log individual updates in `_log.md` — only bulk ingest
- NEVER store passwords, API keys, or specific invoice amounts
- Keep it factual and short — the wiki is a reference book, not a diary

### When NOT to update the wiki
- Ephemeral things: temporary debug sessions, one-off questions
- Things already in the wiki with same or better detail (read first!)
- Pure code changes (that belongs in git, not the wiki)

### Context continuity — preserve knowledge across sessions

| Skill | Captures | When |
|-------|----------|------|
| `/wiki-learn` | Durable *knowledge* → wiki | Before /compact, or when important knowledge emerged |
| `/wiki-handover` | Temporary *task state* → `_handovers/` | Before /compact when mid-task |
| `/wiki-resume` | Rehydrate from handover | Start of new session |

**Proactive suggestions — offer these skills:**
- Suggest `/wiki-learn` when: 3+ specific things from the conversation are worth saving
- Suggest `/wiki-handover` when: user is mid-task and signals pause/stop/compact
- Suggest `/wiki-resume` when: new session opens and `_handovers/latest.md` exists

### Pending ingest check
At session start, check if `_pending-ingest.json` exists. If yes, mention it briefly.

### Quick-save
Use `/wiki-save` for quick ad-hoc updates without full ingest flow.

### Wiki skills overview

| Skill | Use |
|-------|-----|
| `/wiki-save` | Quick ad-hoc update |
| `/wiki-query` | Ask the wiki something |
| `/wiki-ingest` | Full ingest of a source |
| `/wiki-auto-ingest` | Batch-ingest new sources |
| `/wiki-lint` | Quality check |
| `/wiki-review` | Interactive confidence graduation |
| `/wiki-learn` | Distill conversation knowledge before compact |
| `/wiki-handover` | Save task state before compact |
| `/wiki-resume` | Resume from handover |
| `/wiki-setup` | Initial setup (run once) |
