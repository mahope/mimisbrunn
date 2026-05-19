---
name: wiki-review
description: Interaktiv gennemgang af wiki-sider med lav confidence. Guider brugeren gennem verifikation og opgraderer confidence.
---

# Wiki Review

Interaktiv confidence-graduation for LLM Wikien i `{{WIKI_PATH}}`.

## Input (valgfrit)

`$ARGUMENTS` kan specificere:
- `high-priority` — kun højprioritets-sider fra review-queue (default)
- `people` — kun person-entities
- `clients` — kun client-entities
- `all` — alle sider med confidence < high
- Et entitetsnavn — review en specifik side

## Procedure

### Trin 1: Find sider til review
1. Læs `_review-queue.md` for prioriteret liste
2. Alternativt: Grep for `confidence: low` eller `confidence: medium` i `entities/`
3. Sortér efter prioritet: høj > medium > lav
4. Vælg de næste 5 uverificerede sider

### Trin 2: For hver side — interaktiv review
Vis siden i dette format:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REVIEW 1/5: [[mads-holst-jensen]]
Type: person | Confidence: low | Ord: 450
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Følgende fakta er markeret som usikre:

1. Fødselsdato: 1. december 1994
2. Karaktergennemsnit: 11,3
3. Teamleder fra januar 2026

For hvert punkt, svar:
  ✅ Korrekt
  ❌ Forkert (giv korrekt info)
  🤷 Ved ikke (behold markering)
```

Brug `AskUserQuestion` med multiSelect for at lade brugeren markere alle korrekte fakta på én gang.

### Trin 3: Opdatér baseret på svar
For hvert fakta-punkt:
- **✅ Korrekt:** Behold fakta. Markér som verificeret.
- **❌ Forkert:** Spørg om den korrekte information. Opdatér wiki-siden.
- **🤷 Ved ikke:** Behold markering. Sænk prioritet i review-queue.

### Trin 4: Opgradér confidence
Baseret på review-resultatet:
- Alle fakta verificeret → `confidence: high`
- De fleste verificeret, nogle ukendte → `confidence: medium`
- Flere fejl fundet → ret og sæt `confidence: medium`
- Opdatér `last_updated` til dags dato

### Trin 5: Fjern fra review-queue
1. Fjern advarselsbanneret fra sides indhold (linjer der starter med `> ⚠️`)
2. Markér siden som gennemgået i `_review-queue.md` (sæt ✅ foran)

### Trin 6: Progress og næste
Vis progress:
```
━━━━ Progress ━━━━
Verificeret: 3/5 sider
Confidence opgraderet: 2 (low→medium: 1, medium→high: 1)
Fejl rettet: 1
━━━━━━━━━━━━━━━━━━

Fortsæt med næste side? (ja/nej/spring over)
```

## Regler
- Vis KUN fakta der er markeret som usikre — ikke hele siden
- Gør det hurtigt og fokuseret — brugeren skal ikke læse lange tekster
- Gem ændringer løbende (auto-commit hook klarer git)
- Skriv på dansk
- Ved tvivl: behold lav confidence hellere end at opgradere forkert
