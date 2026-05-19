---
name: wiki-import
description: Importér data fra eksterne kilder — ChatGPT, Claude, emails, Google Drive, Notion, LinkedIn, Facebook, og mere. Auto-detekterer kildeformat.
---

# /wiki-import — Importér fra eksterne kilder

Drop en fil eller mappe, og denne skill finder ud af hvad det er og ingester det korrekt.

## Input

`$ARGUMENTS` — en filsti, mappe, eller URL. Eksempler:
- `/wiki-import ~/Downloads/chatgpt-export.zip`
- `/wiki-import ~/Downloads/conversations.json`
- `/wiki-import ~/Downloads/Basic_LinkedInDataExport.zip`
- `/wiki-import ~/Downloads/facebook-data.zip`
- `/wiki-import ~/Downloads/takeout.zip` (Google Takeout)
- `/wiki-import ~/Documents/notes/` (løse markdown-filer)

## Procedure

### Trin 1: Detect kildeformat

Læs filen/mappen og identificér typen:

| Kilde | Hvordan man kender den | Fil(er) |
|-------|----------------------|---------|
| **ChatGPT export** | ZIP med `conversations.json` | ChatGPT Settings → Data controls → Export data |
| **Claude export** | ZIP/folder med `conversations/` mappe af JSON-filer | claude.ai → Settings → Export data |
| **LinkedIn** | ZIP med `Profile.csv`, `Positions.csv` | LinkedIn Settings → Get a copy of your data |
| **Facebook** | ZIP med `your_facebook_activity/` | Facebook Settings → Download your information |
| **Google Takeout** | ZIP med `Takeout/` mappe | takeout.google.com |
| **Notion export** | ZIP med markdown + CSV-filer | Notion → Settings → Export |
| **Email (IMAP)** | Angiv `imap://user@host` | Kræver credentials |
| **Markdown filer** | `.md`-filer i en mappe | Manuelt indsamlede noter |
| **Enkeltstående fil** | `.md`, `.txt`, `.pdf`, `.docx` | Hvad som helst |

### Trin 2: Udpak og klassificér

For ZIP-filer: udpak til `_sources/[kilde-type]/`

Kør det relevante adapter-script fra `scripts/adapters/`:

#### ChatGPT (`scripts/adapters/chatgpt.py`)
- Parser `conversations.json`
- Extracter: samtale-titler, bruger-beskeder, assistant-svar
- Finder: omtalte entiteter (personer, projekter, tools, beslutninger)
- Ignorerer: korte Q&A (<5 beskeder), code-only samtaler

#### Claude (`scripts/adapters/claude.py`)
- Parser JSON-filer fra `conversations/`
- Samme logik som ChatGPT men tilpasset Claudes format
- Finder: durable knowledge, beslutninger, kontekst

#### LinkedIn (`scripts/adapters/linkedin.py`)
- Parser CSV-filer: Profile, Positions, Education, Skills, Volunteering, Recommendations
- Beriger: person-entity (brugeren selv), job-historik, uddannelse, skills
- Cross-matcher: kontakter mod eksisterende wiki-entities

#### Facebook (`scripts/adapters/facebook.py`)
- Parser JSON-filer: profile_information, friends, events, groups, posts
- Beriger: person-entity, tidslinje-verifikation, events
- Filtrerer: springer jokes/memes/link-shares over, kun milepæle og fakta

#### Google Takeout (`scripts/adapters/google-takeout.py`)
- Parser: Calendar events, Contacts, Drive filer, Chrome bookmarks
- Beriger: mødehistorik, kontakter, dokumenter

#### Notion (`scripts/adapters/notion.py`)
- Parser: markdown-filer med frontmatter
- Mapper: Notion pages → wiki entities baseret på indhold
- Bevarer: Notion links som [[wikilinks]]

#### Email IMAP (`scripts/adapters/email-imap.py`)
- Forbinder til vilkårlig IMAP-server
- Eksporterer til `_sources/emails-[provider]/`
- Filtrerer: springer newsletters/spam over
- Kræver: email + password (input via AskUserQuestion)

#### Markdown filer (`scripts/adapters/markdown.py`)
- Kopierer til `_sources/`
- Parser: frontmatter hvis det eksisterer
- Klassificerer: person/project/tool/concept baseret på indhold

### Trin 3: Kør wiki-auto-ingest

Efter adapteren har processeret filerne, kør wiki-auto-ingest med de relevante filer.

Brug klassificeringslogikken fra wiki-auto-ingest:
- Forstå kilden FØR du extracter entiteter
- Konservativ entity-oprettelse
- confidence: low for alt auto-ingestet
- Dokumentér skip-beslutninger

### Trin 4: Rapportér

```
## /wiki-import — [kildetype] YYYY-MM-DD

- **Kilde:** [filnavn/type]
- **Filer processeret:** N
- **Entities oprettet:** X
- **Entities opdateret:** Y
- **Sprunget over:** Z (med begrundelse)

Kør `/wiki-review` for at verificere nye entities.
```
