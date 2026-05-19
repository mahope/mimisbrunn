---
name: wiki-setup
description: Interaktiv opsætning af din Second Brain. Konfigurerer wiki-stier, personlig info, og tech stack.
---

# /wiki-setup — Konfigurér din Second Brain

Interaktiv opsætning der personaliserer wikien til dig.

## Procedure

### Trin 1: Spørg brugeren

Stil disse spørgsmål med AskUserQuestion:
1. **Navn:** Hvad er dit fulde navn?
2. **Rolle:** Hvad laver du? (freelancer, ansat, studerende, etc.)
3. **Tech stack:** Hvilke teknologier bruger du dagligt? (komma-separeret)
4. **Email:** Hvad er din primære email?
5. **Sprog:** Hvilket sprog skal wikien skrives på? (dansk/english)

### Trin 2: Opdatér filer

1. Erstat `{{WIKI_PATH}}` i alle `.claude/commands/*.md` med den faktiske vault-sti
2. Opdatér `CLAUDE.md` med brugerens info
3. Opret en `entities/people/[brugernavn].md` entity for brugeren selv
4. Opdatér `_schema.md` med sprogvalg

### Trin 3: Initialiser Git

```bash
git init
git add -A
git commit -m "Initial commit: Second Brain setup"
```

### Trin 4: Rapportér

Vis brugeren:
- Vault-sti
- Antal skills tilgængelige
- Næste skridt (åbn i Obsidian, prøv /wiki-save)
