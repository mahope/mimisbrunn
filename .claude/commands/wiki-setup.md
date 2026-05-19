---
name: wiki-setup
description: Interaktiv opsætning af din Second Brain. Giver den et navn, konfigurerer wiki-stier, personlig info, og tech stack.
---

# /wiki-setup — Konfigurér din Second Brain

Interaktiv opsætning der personaliserer din Second Brain til dig.

## Procedure

### Trin 1: Velkommen

Vis:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Welcome to your Second Brain setup!
  Let's make this knowledge base yours.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Trin 2: Spørg brugeren

Stil disse spørgsmål med AskUserQuestion:

1. **Brain name:** "Hvad vil du kalde din Second Brain?" (f.eks. "Atlas", "Nexus", "Vault", "Echo", dit eget navn, eller noget helt andet)
2. **Navn:** "Hvad er dit fulde navn?"
3. **Rolle:** "Hvad laver du?" (freelancer, udvikler, designer, studerende, etc.)
4. **Tech stack:** "Hvilke teknologier bruger du dagligt?" (komma-separeret, f.eks. "WordPress, React, Python")
5. **Email:** "Hvad er din primære email-adresse?"
6. **Sprog:** "Hvilket sprog skal wikien skrives på?" (dansk/english/andet)

### Trin 3: Personalisér filer

1. **`{{WIKI_PATH}}`** — erstat i alle `.claude/commands/*.md` med den faktiske vault-sti (brug `pwd` til at finde den)

2. **README.md** — erstat titlen:
   ```markdown
   # {{BRAIN_NAME}} — Second Brain
   ```

3. **CLAUDE.md** — tilføj i toppen:
   ```markdown
   # {{BRAIN_NAME}} — Second Brain for {{USER_NAME}}
   > {{USER_ROLE}} | Tech: {{TECH_STACK}}
   ```

4. **_schema.md** — opdatér sprogram:
   ```markdown
   Sprog: {{LANGUAGE}}
   ```

5. **_dashboard.md frontmatter** — tilføj brain-name

### Trin 4: Opret brugerens entity

Opret `entities/people/{{kebab-name}}.md`:
```markdown
---
entity: "{{USER_NAME}}"
type: person
aliases: [{{first_name}}]
sources: []
confidence: high
created: {{today}}
last_updated: {{today}}
tags: [mig, ejer]
---

# {{USER_NAME}}

Ejer af {{BRAIN_NAME}}. {{USER_ROLE}}.

## Tech Stack
{{TECH_STACK as bullet list}}

## Kontakt
- **Email:** {{EMAIL}}
```

### Trin 5: Opret 3 eksempel-entities

Opret korte eksempler så brugeren ser hvad "godt" ser ud:

**`entities/tools/{{first_tool}}.md`** — baseret på det første tool i tech stack
**`entities/concepts/second-brain-workflow.md`** — meta-entity om selve workflowet
**`entities/projects/getting-started.md`** — et "getting started" projekt

### Trin 6: Kør scripts

```bash
python scripts/regen-index.py
python scripts/completeness-score.py
python scripts/gen-dashboard.py
```

### Trin 7: Initialiser Git (hvis ikke allerede)

```bash
git add -A
git commit -m "{{BRAIN_NAME}}: Initial setup for {{USER_NAME}}"
```

### Trin 8: Vis velkomst

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {{BRAIN_NAME}} is ready!
  
  Entities: 4 (you + 3 examples)
  Skills: 10 available
  
  Next steps:
  1. Open this folder in Obsidian
  2. Press Ctrl+G to see the graph
  3. Try: /wiki-save "My first tool is amazing"
  4. Try: /wiki-query "What do I know?"
  
  Your brain grows automatically from
  every conversation. Just talk to Claude.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
