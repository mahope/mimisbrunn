---
name: wiki-ingest
description: Ingest en kilde ind i LLM Wiki. Tager en fil, URL, eller fritekst og opdaterer wiki-sider i Obsidian vaulten.
---

# Wiki Ingest

Du er vedligeholder af en LLM Wiki i Obsidian-vaulten `{{WIKI_PATH}}`.

## Input

Brugeren giver dig en kilde. Det kan være:
- En **filsti** til en lokal fil (markdown, txt, docx, pdf, kode)
- En **URL** der skal fetches
- **Fritekst** direkte i prompten
- En **mappe** — ingest alle relevante filer i mappen

Argumentet til denne kommando er kilden: `$ARGUMENTS`

## Procedure

### Trin 1: Læs schema
Læs `{{WIKI_PATH}}_schema.md` for at forstå regler og konventioner.

### Trin 2: Hent kilden
- Filsti: Brug Read-tool.
- URL: Brug WebFetch.
- Fritekst: Brug direkte.
- Mappe: List filerne med Glob, læs dem sekventielt.

Gem kilden i `{{WIKI_PATH}}_sources\` med format `YYYY-MM-DD-beskrivelse.md`.

### Trin 3: Forstå kilden (KRITISK)

Før du gør noget andet: **forstå hvad kilden handler om.**

**For emails — klassificér afsender/modtager-relationen:**

| Mads' rolle | Eksempel | Entity-type |
|-------------|----------|-------------|
| Mads sælger til / arbejder for X | Tilbud, faktura, support | X er **client** |
| Mads har fået et lead fra X | Ny henvendelse | X er **client** (lifecycle: lead) |
| Mads søger job HOS X | Ansøgning, samtale, afslag | X er **IKKE client** — notér i [[job-historik-mads]] |
| Mads køber fra X | Bestilling, kvittering | X er **tool** eller ignorer |
| X er en personlig kontakt | Venner, familie, spejder | X er **person** (kun hvis vedvarende) |
| X er en offentlig myndighed | SKAT, kommune, bank | Ignorer eller notér i relevant concept |

**For dokumenter — vurdér relevans:**
- Kundedokumenter (PRD, kontrakter, tilbud) → berig client/project
- Personlige dokumenter → kun fakta der beriger tidslinjer/milepæle
- Tekniske dokumenter → berig tool/project entities

**For Facebook/social media:**
- Profildata → verificér eksisterende fakta
- Venner → krydstjek, OPRET IKKE sider for alle
- Opslag → kun milepæle og fakta, ikke meninger/jokes
- Beskeder → kun verificerbar info om kendte entities

### Trin 4: Læs eksisterende wiki
```
Wiki/entities/**/*.md
```
Læs `Wiki/_index.md` for overblik. **Søg altid om en entity eksisterer FØR du opretter en ny.**

### Trin 5: Analysér kilden

Identificér entiteter med korrekte typer (se klassificering ovenfor):

**Opret KUN nye entities hvis:**
1. Entiteten har en vedvarende relation til Mads (>1 interaktion)
2. Der er nok information til en meningsfuld side (>3 sætninger)
3. Mads ville finde den nyttig om 3 måneder
4. Entity-typen er korrekt (client = BETALER Mads)

**Opret IKKE entities for:**
- Engangs-kontakter (én email, ingen opfølgning)
- Firmaer Mads har søgt job hos (det er job-historik, ikke clients)
- Firmaer Mads køber fra (det er leverandører, medmindre de er tools han bruger aktivt)
- Tilfældige Facebook-venner
- Begreber der kun nævnes i forbifarten

### Trin 6: Opdatér/opret wiki-sider

For **hver verificeret entitet**:
1. Tjek om en side allerede eksisterer (søg i entities/ MED aliases)
2. Hvis ja: Læs siden, OPDATÉR med ny information. Bevar eksisterende info.
3. Hvis nej og oprettelse er berettiget (se Trin 5): OPRET ny side.
4. Tilføj `[[wiki-links]]` til relaterede entiteter.
5. Tilføj kildehenvisning `[kilde: filnavn]`.

### Trin 7: Opdatér _index.md
Kør `python scripts/regen-index.py` eller opdatér manuelt.

### Trin 8: Log operationen
Tilføj ny indgang ØVERST i `_log.md`:

```markdown
## YYYY-MM-DD — Ingest: [kildenavn]
- **Kilde:** `_sources/YYYY-MM-DD-filnavn.md`
- **Nye sider:** [liste]
- **Opdaterede sider:** [liste]
- **Sprunget over:** [liste med begrundelse]
- **Entiteter:** N nye, M opdaterede, K sprunget over
```

### Trin 9: Rapportér
Kort resumé med:
- Hvilken kilde blev ingestet
- Entity-fordeling (nye vs. opdaterede vs. sprunget over)
- Eventuelle modsigelser med eksisterende viden
- Sprunget-over begrundelser

## Vigtige regler
- **Forstå konteksten FØRST** — klassificér kilden inden du extracter
- **Konservativ entity-oprettelse** — opdatér hellere end opret
- Skriv på **dansk** (tekniske termer på engelsk)
- Brug `[[wiki-links]]` flittigt
- Aldrig slet eksisterende information
- Hver side skal give mening alene — inkludér altid et resumé
- Aldrig gem passwords, API keys, eller præcise beløb
- Dokumentér HVORFOR du springer noget over
