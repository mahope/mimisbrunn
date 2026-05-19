---
name: wiki-handover
description: Gem task-state så næste session kan fortsætte uden at miste momentum. Brug før /compact når du er midt i en opgave.
---

# /wiki-handover — Gem opgave-state før compaction

Fanger den aktuelle opgaves tilstand — hvad er prøvet, hvad virker, hvad er næste skridt — så den næste session kan fortsætte rent.

## Hvornår

- Før /compact når du er midt i en opgave
- Når en lang session har produceret taktisk detalje (fejlede forsøg, halv-færdigt arbejde)
- Når du vil pause en opgave og vende tilbage senere

## Hvornår IKKE

- Rene videns-sessioner → brug `/wiki-learn` i stedet
- Trivielt små opgaver (5 beskeder)
- Når opgaven er genuint færdig

## Procedure

### Trin 1: Identificér opgaven

Hvad arbejder brugeren på lige nu? Vælg en kort slug (kebab-case, 2-4 ord).

### Trin 2: Skriv handover-dokument

Skriv til BEGGE steder:
- `{{WIKI_PATH}}_handovers\YYYY-MM-DD-HHMM-{{slug}}.md` — arkiv
- `{{WIKI_PATH}}_handovers\latest.md` — overskrives hver gang

Struktur:
```markdown
---
type: handover
task: {{opgave-navn}}
slug: {{slug}}
created: YYYY-MM-DD HH:MM
status: in-progress
---

# Handover: {{opgave-navn}}

## Mål
Hvad vi prøver at opnå, i 1-3 sætninger.

## Kontekst
Hvorfor denne opgave er vigtig, hvad udløste den. Link til wiki-sider med [[wikilinks]].

## Hvad vi har prøvet
Kronologisk liste med resultater:
- **Tilgang 1:** hvad vi gjorde → resultat (virkede / fejlede / delvist — hvorfor)
- **Tilgang 2:** ...

## Nuværende tilstand
Situation lige nu. Hvad virker, hvad er broken, hvad er halv-færdigt.

## Næste skridt
Den vigtigste næste handling. Konkret nok til at eksekvere uden at genbeslutte.

## Åbne spørgsmål
Ting vi ikke ved endnu, beslutninger der er udskudt.

## Filer rørt
- `sti/til/fil.ext` — hvad vi ændrede og hvorfor

## Gotchas
Ting næste session vil trippe over:
- Constraints, skjult state, environment-quirks, præferencer
```

### Trin 3: Fortæl brugeren

```
Handover skrevet: _handovers/{{filnavn}}
Næste session: /wiki-resume for at genoptage.
```

## Regler
- Handover er *midlertidigt scratch*, ikke varig viden — det er `/wiki-learn`'s job
- Fejlede forsøg er SÆRLIGT værdifulde — de forhindrer næste session i at gentage dem
- Skriv "Ingen" for sektioner der er tomme — pad ikke
- Opdatér eksisterende handover (<24t gammel) i stedet for at starte forfra
