---
name: wiki-save
description: Hurtig opdatering af en wiki-entitet uden fuld ingest-flow. Til ad-hoc tilføjelser og rettelser.
---

# Wiki Save

Hurtig opdatering af LLM Wiki i `{{WIKI_PATH}}`.

## Input

`$ARGUMENTS` — en kort beskrivelse af hvad der skal gemmes, f.eks.:
- `En Kunde bruger nu WooCommerce i stedet for custom booking`
- `Ny kunde: Nordlys ApS, kontakt Anna Eksempel, WordPress site`
- `Dokploy kræver at man sætter NIXPACKS_NODE_VERSION`

## Procedure

### Trin 1: Identificér entiteten
Ud fra input, find den relevante entitet. Søg i `Wiki/entities/` med Grep.

### Trin 2: Opdatér eller opret

**Hvis entiteten findes:**
1. Læs den eksisterende side
2. Tilføj den nye information det rigtige sted
3. Opdatér `last_updated` i frontmatter
4. Tilføj `[[wiki-links]]` til evt. nye relaterede entiteter

**Hvis entiteten IKKE findes:**
1. Bestem type (client/person/project/tool/concept/recipe/place)
2. Opret ny side med korrekt frontmatter (se `Wiki/_schema.md`)
3. Skriv et kort resumé + den information du har
4. Opdatér `Wiki/_index.md` med den nye entitet under den rigtige kategori

### Trin 3: Bekræft
Giv et kort svar:
- Hvad blev opdateret/oprettet
- Link til filen: `Wiki/entities/[type]/[filnavn].md`

## Regler
- Skriv på dansk, tekniske termer på engelsk
- Brug `[[wiki-links]]`
- Aldrig slet eksisterende info — tilføj
- Ingen passwords, API keys, eller beløb
- Hold det kort — dette er en quick-save, ikke en fuld ingest
