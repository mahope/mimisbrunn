---
title: Wiki Schema
description: Regler og konventioner for LLM-vedligeholdelse af denne wiki
---

# Wiki Schema

## Purpose

This wiki is a persistent, cumulative knowledge base maintained by an LLM. It contains structured knowledge extracted from raw sources — articles, notes, documents, code, meetings, conversations, and more.

## Entity Types

| Type | Folder | Description | Examples |
|------|--------|-------------|----------|
| `person` | `entities/people/` | People — clients, contacts, family, colleagues | A customer, a team lead |
| `project` | `entities/projects/` | Projects and initiatives | A website, a product launch |
| `client` | `entities/clients/` | Companies/people you work with (that PAY you) | Acme Corp, John's Consulting |
| `tool` | `entities/tools/` | Software, frameworks, services | Bricks Builder, Dokploy, Claude |
| `place` | `entities/places/` | Physical locations | Office, vacation spots |
| `concept` | `entities/concepts/` | Ideas, methods, knowledge | SEO strategy, Docker networking |
| `recipe` | `entities/recipes/` | Recipes, procedures, how-tos | Deployment workflow, pasta recipe |

## Frontmatter Format

All wiki pages MUST have this frontmatter:

```yaml
---
entity: "Entity Name"
type: person|project|client|tool|place|concept|recipe
aliases: [alternative names]
sources: [_sources/filename.md, ...]
confidence: high|medium|low
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
tags: [relevant, tags]
---
```

## Writing Conventions

1. **Wiki-links:** Use `[[entity-name]]` to link between pages. Link generously.
2. **Citations:** Always reference sources with `[source: filename]` notation. For conversation-derived knowledge, use: `> Source: conversation YYYY-MM-DD`
3. **Tone:** Factual and concise. No filler. Write like a reference book.
4. **Contradictions:** When sources contradict each other, note both viewpoints with sources.
5. **Sections:** Use `## Headings` to structure. Typical sections:
   - Summary (always first, 1-2 sentences)
   - Details/context
   - Relations (links to other entities)
   - Notes (extra observations)
   - Sources

## Ingest Rules

When a new source is added:
1. Copy the source to `_sources/` with format `YYYY-MM-DD-description.md`
2. Read the source thoroughly
3. Identify all entities mentioned in the source
4. For each entity: create new page OR update existing
5. Ensure cross-references between related entities
6. Update `_index.md` with new pages
7. Log the operation in `_log.md`

## Classification Rules (CRITICAL)

Before creating entities from any source, CLASSIFY the source first:

**client** — ONLY companies/people that PAY you for work:
- You sent an invoice → client
- You sent a proposal → client (lifecycle: lead)
- You applied for a job THERE → **NOT a client** (it's job history)
- You bought something FROM them → **NOT a client** (it's a vendor/tool)

**person** — People with a lasting relationship:
- 1 email exchange → **DO NOT create**
- Ongoing relationship → create

**Before creating ANY new entity, ask:**
1. Does it already exist? (search with aliases)
2. Is this a lasting relationship, or a one-off?
3. Would I find this page useful in 3 months?
4. Do I have enough info for a meaningful page (>3 sentences)?

If NO to 2, 3, or 4 → **DO NOT create**. Add a note to a related existing entity instead.

## Anti-Fabrication (CRITICAL)

LLM agents MUST NOT invent or guess:
- **Never invent dates, addresses, names, numbers, or relationships.** If it's not explicitly in the source, don't write it.
- **When uncertain: omit.** Empty is better than guesswork.
- **Mark uncertainty explicitly:** use "(uncertain)" or "approx."
- **Only add relationships if mentioned:** Two people in the same file does NOT mean they're related.
