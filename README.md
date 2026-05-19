# Second Brain Starter Kit for Claude Code

> *Give your AI a memory that grows itself.*

A self-growing, self-maintaining personal knowledge base powered by Claude Code, Obsidian, and automated pipelines. Name it whatever you want — Atlas, Nexus, Cortex, or just "My Brain."

Your Second Brain grows automatically from your conversations, emails, calendar, and tech news — while maintaining high quality through classification logic and confidence scoring.

```
You: "I just talked to Sarah from Acme Corp about a React redesign"
Brain: ✓ Updated [[acme-corp]] with new project info
       ✓ Created [[sarah-jones]] with contact details  
       ✓ Linked to [[react]] in tech stack
       (auto-committed to Git)
```

## What you get

- **Obsidian vault** with structured entity types (clients, people, projects, tools, concepts, places, recipes)
- **9 Claude Code skills** for wiki management (`/wiki-save`, `/wiki-query`, `/wiki-ingest`, `/wiki-auto-ingest`, `/wiki-lint`, `/wiki-review`, `/wiki-learn`, `/wiki-handover`, `/wiki-resume`)
- **Auto-commit + push** — every wiki change is versioned via Git
- **Auto-index regeneration** — `_index.md` always stays fresh
- **Completeness scoring** — every entity scored 0-100% on 10 quality metrics
- **Wikilink fixer** — finds plain-text mentions and converts to `[[wikilinks]]`
- **Graph analysis** — relationship mapping with interactive D3.js visualization
- **Dashboard** with health score (0-100)
- **Tech Intel Scanner** template — automated tech news briefings
- **Context continuity** — `/wiki-learn` before compact, `/wiki-handover` for task state
- **Dokploy service** template for 24/7 automation (email export, briefings, health checks)

## Quick Start

### 1. Clone and personalize

```bash
git clone https://github.com/mahope/second-brain-starter.git my-brain
cd my-brain
claude
```

Then run the interactive setup:
```
> /wiki-setup
```

This will ask you to:
- **Name your brain** (Atlas, Nexus, Vault, or anything you like)
- Set your name, role, and tech stack
- Create your first entities as examples
- Initialize Git with your personalized config

### 2. Open in Obsidian

Open the vault folder in Obsidian: File → Open Vault → select `my-brain/`

### 3. Start using it

In any Claude Code session, the wiki works automatically:
- Mention a client → wiki updates
- Learn something new → wiki captures it
- Before `/compact` → `/wiki-learn` preserves knowledge

## Architecture

```
Your conversations ──→ auto-save triggers ──→ wiki entities
Your emails ─────────→ auto-ingest ─────────→ wiki entities
Tech news ───────────→ intel scanner ───────→ tool entities + briefing email
Calendar ────────────→ calendar enrichment ──→ meeting history
                                                    │
                                              ┌─────▼─────┐
                                              │  Obsidian  │
                                              │   Vault    │
                                              │  (Git)     │
                                              └─────┬─────┘
                                                    │
                              ┌──────────────────────┼──────────────────────┐
                              │                      │                      │
                        Dashboard              Graph View           Tech Briefings
                       (health score)       (relationships)        (email to you)
```

## Entity Types

| Type | Folder | What goes here |
|------|--------|---------------|
| `client` | `entities/clients/` | Companies/people that pay you for work |
| `person` | `entities/people/` | Contacts with a lasting relationship |
| `project` | `entities/projects/` | Things you're working on or have worked on |
| `tool` | `entities/tools/` | Software, frameworks, services you use |
| `concept` | `entities/concepts/` | Ideas, methods, knowledge, strategies |
| `place` | `entities/places/` | Physical locations |
| `recipe` | `entities/recipes/` | Recipes, procedures, how-tos |

## Skills Reference

| Skill | When to use |
|-------|------------|
| `/wiki-save` | Quick ad-hoc update to an entity |
| `/wiki-query` | Ask the wiki a question |
| `/wiki-ingest` | Full ingest of a file, URL, or text |
| `/wiki-auto-ingest` | Batch-ingest new sources with classification |
| `/wiki-lint` | Quality check (orphans, dead links, stale pages) |
| `/wiki-review` | Interactive confidence graduation |
| `/wiki-learn` | **Before /compact** — distill durable knowledge |
| `/wiki-handover` | Save task state between sessions |
| `/wiki-resume` | Resume from a handover in a new session |

## Scripts

Run from the vault root:

```bash
python scripts/regen-index.py          # Regenerate _index.md
python scripts/completeness-score.py   # Score all entities 0-100%
python scripts/gen-dashboard.py        # Generate _dashboard.md with health score
python scripts/gen-graph.py            # Generate relationship graph + analysis
python scripts/fix-wikilinks.py        # Dry-run: find plain-text → [[wikilink]] opportunities
python scripts/fix-wikilinks.py --apply # Apply wikilink fixes
python scripts/send-briefing.py        # Send pending briefings via Resend
```

## Automation Setup (optional)

### Remote agents (requires Claude Pro/Max)

The kit includes templates for scheduled remote agents:
- **Email ingest** — scan Gmail for new contacts and updates
- **Tech Intel Scanner** — scan tech news sources relevant to your stack
- **Weekly Digest** — Monday morning summary of wiki activity
- **Lint + Calendar** — weekly quality check + calendar enrichment

See `docs/automation-setup.md` for configuration.

### Dokploy/Docker service (optional)

For 24/7 automation without your PC running, deploy the wiki-agent service:

See `deploy/wiki-agent/SETUP.md` for instructions.

## Importing Your Data

The `/wiki-import` skill auto-detects your data format. Just drop a file:

```
> /wiki-import ~/Downloads/chatgpt-export.zip
> /wiki-import ~/Downloads/Basic_LinkedInDataExport.zip
> /wiki-import ~/Downloads/facebook-data.zip
> /wiki-import ~/Downloads/takeout.zip
> /wiki-import ~/Downloads/notion-export.zip
```

### Supported Sources

| Source | How to get your data | What's extracted |
|--------|---------------------|-----------------|
| **ChatGPT** | Settings → Data controls → Export | Conversations → entities, decisions, knowledge |
| **Claude** | claude.ai → Settings → Export | Same as ChatGPT |
| **LinkedIn** | Settings → Get a copy of your data | Profile, positions, education, skills, volunteering |
| **Facebook** | Settings → Download your information | Profile, friends, events, posts (milestones only) |
| **Google Takeout** | takeout.google.com | Contacts, calendar events, Drive file list |
| **Notion** | Settings → Export (Markdown) | Pages → wiki entities |
| **Email (any IMAP)** | Automatic via adapter | Conversations → client/contact entities |
| **Markdown files** | Drop a folder | Direct import with classification |

### Standalone Adapters

You can also run adapters directly:

```bash
python scripts/adapters/chatgpt.py ~/Downloads/chatgpt-export.zip
python scripts/adapters/linkedin.py ~/Downloads/linkedin-export.zip
python scripts/adapters/facebook.py ~/Downloads/facebook-data.zip
python scripts/adapters/email-imap.py gmail user@gmail.com app-password 30
python scripts/adapters/notion.py ~/Downloads/notion-export.zip
python scripts/adapters/google-takeout.py ~/Downloads/takeout.zip
```

After running an adapter, use `/wiki-auto-ingest` to process the extracted data into wiki entities.

## Customization

### Adding entity types

Edit `_schema.md` to add new types. Create a template in `_templates/`. Update `scripts/regen-index.py` with the new category.

### Adding ingest sources

Edit the auto-ingest skill in `.claude/commands/wiki-auto-ingest.md` to add new source directories or classification rules.

### Adding tech intel sources

Edit the Tech Intel Scanner prompt (in your scheduled routine) to add RSS feeds, changelogs, or news sites relevant to your stack.

## Philosophy

1. **Automatic over manual** — the wiki should grow from your daily work, not require separate maintenance
2. **Quality over quantity** — better to have 50 high-confidence entities than 500 low-confidence ones
3. **Classification first** — understand what a source IS before extracting entities from it
4. **Confidence scoring** — every fact has a trust level (high/medium/low) based on its source
5. **Context continuity** — knowledge survives across sessions via `/wiki-learn` and `/wiki-handover`

## Credits

Built by [Mads Holst Jensen](https://mahoje.dk) with Claude Code. Inspired by [andreasvig/second-brain-starter-kit](https://github.com/andreasvig/second-brain-starter-kit).

## License

MIT
