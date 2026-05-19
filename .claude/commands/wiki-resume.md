---
name: wiki-resume
description: Genoptag en opgave fra en tidligere session ved at læse den seneste handover. Brug i starten af en ny session for at fortsætte hvor du slap.
---

# /wiki-resume — Genoptag fra handover

Rehydrerer opgave-state fra den seneste handover og giver et klart overblik til at fortsætte.

## Procedure

### Trin 1: Find handover

Læs `{{WIKI_PATH}}_handovers\latest.md`.

Hvis den ikke eksisterer: "Ingen aktiv handover fundet. Start frisk eller brug /wiki-handover i slutningen af denne session."

### Trin 2: Præsentér

Vis handoveren i et kompakt format:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GENOPTAGER: {{opgave-navn}}
Handover fra: {{dato}}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Mål: {{mål}}

Status: {{nuværende tilstand — 1-2 sætninger}}

Næste skridt: {{den vigtigste handling}}

Gotchas: {{ting at passe på}}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Trin 3: Spørg

"Skal jeg fortsætte med '{{næste skridt}}', eller vil du justere retningen?"

### Trin 4: Kør

Fortsæt arbejdet baseret på handoverens kontekst. Brug wiki-entities som kontekst (slå op via Grep).
