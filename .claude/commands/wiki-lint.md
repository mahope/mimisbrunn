---
name: wiki-lint
description: Sundhedstjek af LLM Wiki — finder modsigelser, forældede sider, orphans, og manglende entiteter.
---

# Wiki Lint

Du er kvalitetskontrollør af LLM Wikien i `{{WIKI_PATH}}`.

## Input (valgfrit)

Brugeren kan specificere fokus: `$ARGUMENTS`

Hvis tomt, kør fuld lint. Mulige fokusområder:
- `contradictions` — kun modsigelser
- `stale` — kun forældede sider
- `orphans` — kun sider uden links
- `missing` — kun manglende entiteter
- `quality` — kun kvalitetstjek

## Procedure

### Trin 1: Læs hele wikien
1. Læs `Wiki/_schema.md` for regler
2. Læs `Wiki/_index.md` for overblik
3. Brug Glob til at finde ALLE entity-filer: `Wiki/entities/**/*.md`
4. Læs alle entity-filer (batch i grupper hvis mange)

### Trin 2: Kør checks

#### Check 1: Modsigelser
- Sammenlign fakta på tværs af sider
- Når to sider siger noget modstridende, rapportér begge med kilder
- Alvorsgrad: `CRITICAL` (direkte modsigelse) eller `WARNING` (mulig inkonsistens)

#### Check 2: Forældede sider
- Find sider hvor `last_updated` er mere end 90 dage gammel
- Find sider der refererer til kilder der ikke længere findes i `_sources/`
- Alvorsgrad: `WARNING`

#### Check 3: Orphan-sider
- Find sider som INGEN andre sider linker til
- Find sider der linker til `[[entiteter]]` der ikke eksisterer endnu
- Alvorsgrad: `INFO` (orphans), `SUGGESTION` (manglende targets)

#### Check 4: Manglende entiteter
- Gennemgå alle `[[wiki-links]]` i alle sider
- Find links der peger på sider der ikke eksisterer
- Foreslå oprettelse af de mest refererede manglende sider
- Alvorsgrad: `SUGGESTION`

#### Check 5: Kvalitet
- Find sider uden resumé (første sektion)
- Find sider med tomt eller ufuldstændigt frontmatter
- Find sider uden kilder
- Find sider der er meget korte (< 3 linjer indhold)
- Alvorsgrad: `WARNING` (manglende frontmatter), `INFO` (korte sider)

### Trin 3: Rapportér

Format:

```markdown
# Wiki Lint Report — YYYY-MM-DD

## Oversigt
- **Sider scannet:** N
- **Kilder:** N
- **Issues fundet:** N (X critical, Y warnings, Z info)

## Critical
- [ ] [CONTRADICTION] [[side-a]] vs [[side-b]]: "beskrivelse af modsigelsen"

## Warnings
- [ ] [STALE] [[sidenavn]]: sidst opdateret YYYY-MM-DD (N dage siden)
- [ ] [QUALITY] [[sidenavn]]: mangler frontmatter felt "sources"

## Info
- [ ] [ORPHAN] [[sidenavn]]: ingen indgående links
- [ ] [SHORT] [[sidenavn]]: kun N linjer indhold

## Suggestions
- [ ] [MISSING] [[entitetsnavn]]: refereret fra N sider, men eksisterer ikke
- [ ] [LINK] [[side-a]] bør muligvis linke til [[side-b]]
```

### Trin 4: Tilbyd fikses
Spørg brugeren:
> "Vil du have mig til at fikse nogen af disse issues? Jeg kan:
> - Oprette manglende entiteter med stub-indhold
> - Tilføje manglende frontmatter
> - Tilføje manglende krydsreferencer
> - Markere modsigelser direkte på de berørte sider"

## Vigtige regler
- Ændr ALDRIG noget automatisk — rapportér kun og vent på godkendelse
- Vær specifik — angiv præcis hvad der er galt og hvor
- Prioritér: critical > warning > info > suggestion
- Brug checkliste-format så brugeren kan vælge hvad der skal fikses
