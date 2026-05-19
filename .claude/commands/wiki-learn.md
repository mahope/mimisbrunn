---
name: wiki-learn
description: Distiller varig viden fra den aktuelle samtale til wikien. Brug FØR /compact, eller når en samtale har produceret vigtig ny viden der ikke må tabes.
---

# /wiki-learn — Distiller samtalen til wikien

Fanger varig viden fra DENNE samtale og gemmer den i LLM Wikien (`{{WIKI_PATH}}`), så den overlever context compaction.

## Hvornår

- **Før /compact** — altid. Compaction flader detaljer ud; /wiki-learn bevarer dem først.
- Efter samtaler der producerede ny viden (kundemøder, tekniske beslutninger, personlige milepæle)
- Når noget vigtigt er dukket op og du vil fange det nu

## Procedure

### Trin 1: Scan samtalen

Gennemgå hele samtalen fra start til nu. Klassificér bevarings-kandidater:

**Wiki-entities** (`entities/`)
- Nye fakta om kunder, personer, projekter, tools
- Beslutninger med begrundelse
- Statusændringer (projekt færdigt, nyt lead, ændret tech stack)
- Kontaktinfo, datoer, relationer

**Concepts/playbooks** (`entities/concepts/`)
- Procedurer der blev artikuleret i samtalen
- Mønstre der er værd at navngive
- Standarder eller konventioner der blev aftalt

**Tasks/follow-ups**
- Ting Mads committede sig til ("jeg gør X næste uge")
- Opfølgninger der blev aftalt
- Handlinger med klar næste skridt

**Memory** (Claude Code memory, IKKE wikien)
- Mads' præferencer og korrektioner
- Feedback på arbejdsstil ("gør det sådan", "stop med at gøre X")
- Kortsigtede projekt-noter

### Trin 2: Filtrer

For hver kandidat:
- **Varigt?** Vil det betyde noget om en uge? Nej → skip.
- **Allerede fanget?** Eksisterer det allerede i wikien? Ja → opdatér, opret ikke nyt.
- **Specifikt?** Vage takeaways hører ingen steder hjemme.

### Trin 3: Skriv

- Opdatér eksisterende sider først. Opret kun nye når indholdet tydeligt fortjener sin egen side.
- Hver ændring får provenance: `> Kilde: samtale YYYY-MM-DD`
- Sæt `confidence: medium` på samtale-deriveret viden (Mads sagde det, men det er ikke kryds-verificeret)
- Brug `[[wikilinks]]` til relaterede entities
- Opdatér `last_updated` i frontmatter

### Trin 4: Log

Tilføj til `_log.md`:
```markdown
## YYYY-MM-DD — /wiki-learn
- **Opdateret:** [[side1]], [[side2]]
- **Oprettet:** [[ny-side]]
- **Memory:** N entries
- **Sprunget over:** [kort note om hvad der blev vurderet som ikke-varigt]
```

### Trin 5: Rapportér

```
## /wiki-learn — YYYY-MM-DD

**Bevaret:**
- Wiki: X opdateringer, Y nye sider
- Memory: N entries

**Sprunget over** (overvejet, ikke varigt): [kort note]

Du er klar til /compact.
```

## Regler

- Opsummér IKKE samtalen. Extrahér *varig viden* fra den.
- Link-first: forbind nyt indhold til eksisterende sider.
- Nye sider starter med `confidence: medium` (samtale-kilde).
- Hvis intet er værd at gemme: "Intet varigt. Compact frit."
- Auto-commit hooket håndterer git.
