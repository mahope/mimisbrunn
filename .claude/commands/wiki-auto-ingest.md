---
name: wiki-auto-ingest
description: Automatisk batch-ingest af nye kilder til LLM Wiki. Scanner _sources/ for filer nyere end seneste kørsel og beriger wikien.
---

# Wiki Auto-Ingest

Automatisk batch-ingest til LLM Wikien i `{{WIKI_PATH}}`.

## Input (valgfrit)

`$ARGUMENTS` kan specificere:
- `emails` — kun ingest nye emails
- `drive` — kun ingest nye Google Drive/rclone filer
- `facebook` — ingest Facebook-data fra _sources/facebook/
- `all` (default) — scan alle kilder
- Et tal (f.eks. `10`) — max antal filer at ingeste denne kørsel

## State-tracking

Filen `{{WIKI_PATH}}_auto-ingest-state.json` tracker seneste kørsel.
Hvis state-filen ikke eksisterer, opret den med `last_run` sat til 7 dage siden.

---

## KRITISK: Forstå kilden FØR du extracter entiteter

### Trin 0: Klassificér kilden

Før du gør noget andet, afgør hvad kilden HANDLER OM. Læs hele indholdet og besvar:

**For emails:**
1. **Hvem er afsender/modtager?** (Mads → kunde? Firma → Mads? Mads → personlig?)
2. **Hvad er formålet?** Klassificér som én af:

| Kategori | Eksempler | Wiki-handling |
|----------|-----------|---------------|
| `kunde-dialog` | Tilbud sendt, support-email, faktura-opfølgning | Opdatér client + evt. person entity |
| `kunde-lead` | Ny henvendelse, tilbudsforespørgsel | Opdatér/opret client entity som lead |
| `projekt-arbejde` | Teknisk diskussion, PRD, deploy-info | Opdatér project entity |
| `jobansøgning` | Mads søger job, modtager afslag/tilbud | **IKKE en client!** Notér i [[job-historik-mads]] eller ignorer |
| `personlig` | Familie, venner, aftaler | Opdatér relevant person/place entity KUN hvis væsentligt |
| `administrativ` | Bank, forsikring, SKAT, bolig | Opdatér kun hvis relevant for eksisterende entities |
| `newsletter/spam` | Automatiske emails, marketing | **SKIP — ingest IKKE** |
| `service-notifikation` | Hosting-advarsler, deploy-status, GitHub | Opdatér kun hvis det indeholder ny teknisk info |
| `salg-udgående` | Mads sælger et produkt, domæne, etc. | Opdatér relevant project entity |

3. **Er dette en ny relation eller en eksisterende?** Søg i wiki FØR du opretter noget nyt.

**For Facebook-data:**
| Data-type | Wiki-handling |
|-----------|---------------|
| Profil-info | Verificér/berig [[mads-holst-jensen]] |
| Venneliste | Krydstjek mod eksisterende people-entities, OPRET IKKE nye sider for alle 549 venner |
| Opslag | Kun ingest hvis det indeholder fakta (milepæle, events), IKKE meninger/jokes |
| Beskeder | Kun ingest hvis det indeholder verificerbar info om kendte entities |
| Grupper | Notér gruppemedlemskaber kun hvis relevant (spejder, professionelle) |
| Events | Tilføj til relevante entities hvis de bekræfter datoer/deltagelse |

**For Google Drive-filer:**
| Fil-type | Wiki-handling |
|----------|---------------|
| Kundedokumenter | Opdatér client/project entities |
| Personlige dokumenter | Kun ingest hvis væsentligt (kontrakter, planer) |
| Delte filer med Tea/familie | Kun ingest fakta, ikke private detaljer |

---

## Trin 1: Læs state + schema
1. Læs `_auto-ingest-state.json` for seneste kørsel-tidspunkt
2. Læs `_schema.md` for wiki-konventioner
3. Læs `_index.md` for eksisterende entiteter

## Trin 2: Find nye kilder

**Emails (højest prioritet):**
- `_sources/emails-hostinger/Inbox/` og `Sent/`
- `_sources/emails-gmail/`

**Drive/rclone:**
- `_sources/rclone-mahope-drive/`
- `_sources/gdocs-personligt/` og `gdocs-faellesmappe/`

**Facebook:**
- `_sources/facebook/`

**Skip altid:**
- `_sources/rclone-arkiv/`, `rclone-billeder/`, `rclone-personligt/` (for store)
- `_sources/claude-history/` (separat flow)
- `_sources/boliger/` (allerede ingestet)

## Trin 3: Klassificér og filtrer

For HVER fil, kør Trin 0 (klassificering) og tag beslutning:

**SKIP disse:**
- Emails fra noreply/newsletter/automated afsendere
- Emails med < 50 tegn meningsfuldt indhold
- Rene kvitteringer/ordrebekræftelser
- Jobansøgninger og -afslag (medmindre de tilføjer til [[job-historik-mads]])
- Facebook-venner der ikke allerede er i wikien (opret IKKE sider for tilfældige venner)
- Facebook-opslag der kun er jokes/memes/deling af andres indhold

**INGEST disse:**
- Kundekommunikation (ny info om eksisterende eller potentielle kunder)
- Tekniske diskussioner der beriger project/tool entities
- Personlige milepæle (bryllup, fødsel, flytning) der bekræfter tidslinjer
- Facebook-profildata der verificerer eksisterende wiki-fakta
- Nye kontaktpersoner der har en REEL relation til Mads (>3 emails, aktiv dialog)

**Batch-begrænsning:** Max 15 filer per kørsel. Kvalitet over kvantitet.

## Trin 4: Ingest med korrekt type

### Entity-type regler

**client** — KUN virksomheder/personer der BETALER Mads for arbejde eller har modtaget et tilbud:
- Mads har sendt faktura → client
- Mads har sendt tilbud → client (lifecycle: lead)
- Mads har lavet arbejde for dem → client
- Mads har søgt job HOS dem → **IKKE client** (det er job-historik)
- Mads har købt noget FRA dem → **IKKE client** (det er en leverandør/tool)

**person** — Mennesker med en vedvarende relation til Mads:
- Kunder/kontaktpersoner → person (med link til client entity)
- Familie og nære venner → person
- Engangs-kontakter → **OPRET IKKE** (notér i en eksisterende entity hvis relevant)
- Facebook-venner uden anden kontekst → **OPRET IKKE**

**project** — Noget Mads aktivt arbejder på eller har arbejdet på:
- Klient-projekter → project
- Egne projekter/side-projects → project
- Idéer der aldrig blev til noget → **OPRET IKKE** (medmindre substantiel)

**tool** — Software/services Mads bruger eller evaluerer:
- Bruger aktivt → tool
- Nævnt i én email → **OPRET IKKE** (medmindre det er en teknisk evaluering)

**concept** — Metoder, strategier, viden:
- Kun opret hvis der er SUBSTANTIEL information (>3 sætninger)
- Ikke for hvert begreb der nævnes i forbifarten

### Inden du opretter en NY entity, spørg dig selv:
1. Eksisterer den allerede? (søg med Grep, tjek aliases)
2. Er dette en VEDVARENDE relation/ting, eller bare en engangsforekomst?
3. Ville Mads finde denne side nyttig om 3 måneder?
4. Har jeg nok information til at skrive en meningsfuld side (>3 sætninger)?

Hvis svaret er NEJ på punkt 2, 3, eller 4 → **OPRET IKKE**. Tilføj i stedet en note til en eksisterende, relateret entity.

## Trin 5: Quality gates

Før du gemmer en ændring:
- [ ] Er entity-typen KORREKT? (client = betaler Mads, IKKE = Mads søger job der)
- [ ] Indeholder siden KUN fakta fra kilden? (ingen opdigtede detaljer)
- [ ] Er `confidence` sat korrekt? (low for nye auto-ingestede, medium for bekræftede)
- [ ] Er `sources:` feltet opdateret?
- [ ] Er `last_updated` sat til dags dato?
- [ ] Ingen passwords, API keys, eller specifikke fakturabeløb?
- [ ] Ville Mads være enig i entity-typen og klassificeringen?

## Trin 6: Opdatér state

Skriv til `_auto-ingest-state.json`:
```json
{
  "last_run": "[nu]",
  "last_run_files": [antal filer læst],
  "last_run_skipped": [antal filer sprunget over],
  "total_ingested": [samlet total],
  "sources_scanned": ["emails-hostinger", "emails-gmail"],
  "entities_created": ["ny-entity"],
  "entities_updated": ["eksisterende-entity"],
  "entities_skipped_reason": ["schmiedmann: jobansøgning ikke client"]
}
```

Inkludér `entities_skipped_reason` for at dokumentere HVORFOR noget blev sprunget over — det hjælper med at forbedre ingest-kvaliteten over tid.

## Trin 7: Rapportér

```
## Auto-ingest kørsel — YYYY-MM-DD HH:MM

- **Filer scannet:** N
- **Filer ingestet:** M (af max 15)
- **Filer sprunget over:** K (med begrundelse)
- **Nye entiteter:** X
- **Opdaterede entiteter:** Y
- **Type-fordeling:** clients: A, people: B, projects: C
```

## Vigtige regler

1. **Forstå konteksten FØRST** — læs hele kilden og klassificér FØR du extracter entiteter
2. **Kvalitet over kvantitet** — bedre at ingeste 3 filer godt end 15 dårligt
3. **Konservativ entity-oprettelse** — hellere opdatér en eksisterende side end opret en ny
4. **confidence: low** for alt auto-ingestet
5. **Aldrig slet** eksisterende wiki-info
6. **Aldrig opfind** — kun fakta der eksplicit fremgår af kilden
7. **Dokumentér skip-beslutninger** — skriv HVORFOR du springer noget over
