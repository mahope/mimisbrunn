#!/usr/bin/env python3
"""
Handlinger der blev skrevet ned og aldrig udført.

Baggrund: `sikkerhedsvarsler` bar tre linjer af formen "Handling: Opdatér WordPress
på …" fra august. Den 8. september kørte alle tre sites stadig de gamle versioner.
Handlingen blev noteret, aldrig udført, og intet i systemet opdagede det — en
"Handling:"-linje er ikke en aftale, den er en sætning i en log.

Dette script finder dem, daterer dem ud fra den bullet de står under, og skiller de
egentlige opgaver fra de rene råd. En linje der siger "Opdatér X" er en opgave. En
der siger "ALDRIG klon ukendte repos" er en regel, og den forældes ikke.

Brug:
  python scripts/open-actions.py                 # opgaver over 14 dage gamle
  python scripts/open-actions.py --days 0        # alle opgaver
  python scripts/open-actions.py --all           # også råd og regler
  python scripts/open-actions.py --json
  python scripts/open-actions.py --som-aftaler   # klar til at klippe ind under ## Aftaler
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WIKI_ROOT", Path(__file__).resolve().parent.parent))
ENTITIES = ROOT / "entities"
TODAY = dt.date.today()
# Hvem aftalen er med. En skabelon skal ikke skrive en fremmeds navn ind i dine aftaler.
EJER = os.environ.get("WIKI_OWNER", "<dit navn>")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

HANDLING_RE = re.compile(r"^\s*[-*]\s*Handling:\s*(.+)$", re.I)
DATO_RE = re.compile(r"^\s*[-*]\s*\*\*(\d{4}-\d{2}-\d{2})")

# En handling er en opgave hvis den beder nogen om at gøre noget bestemt. Bydeform
# i starten er signalet; dansk gør det nemt, fordi bydeformen står forrest.
OPGAVE_ORD = re.compile(
    r"^(opdat[ée]r|revok[ée]r|rot[ée]r|slet|fjern|skift|installer|aktiv[ée]r|deaktiv[ée]r"
    r"|kontroll[ée]r|verific[ée]r|identific[ée]r|tilf[øo]j|migrer|luk|geninstaller|udskift"
    r"|genstart|opgrad[ée]r|nedgrad[ée]r|flyt|opret|k[øo]r)\b", re.I)
# Markører for at det faktisk blev gjort. De skrives i praksis ind i samme linje.
LUKKET_RE = re.compile(r"\b(gjort|udf[øo]rt|l[øo]st|afklaret|done|fixed|lukket|✅|afsluttet)\b", re.I)


def find_handlinger():
    ud = []
    for p in sorted(ENTITIES.glob("*/*.md")):
        linjer = p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").split("\n")
        dato = None
        for nr, linje in enumerate(linjer, 1):
            m_dato = DATO_RE.match(linje)
            if m_dato:
                dato = m_dato.group(1)
            m = HANDLING_RE.match(linje)
            if not m:
                continue
            tekst = m.group(1).strip()
            ud.append({
                "side": p.stem,
                "sti": str(p.relative_to(ROOT)).replace("\\", "/"),
                "linje": nr,
                "dato": dato,
                "alder": (TODAY - dt.date.fromisoformat(dato)).days if dato else None,
                "opgave": bool(OPGAVE_ORD.match(tekst)),
                "lukket": bool(LUKKET_RE.search(tekst)),
                "tekst": tekst,
            })
    return ud


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14, help="kun handlinger ældre end så mange dage")
    ap.add_argument("--all", action="store_true", help="tag også råd og regler med")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--som-aftaler", action="store_true",
                    help="skriv forslagene ud som aftale-linjer, klar til at klippe ind")
    a = ap.parse_args()

    alle = find_handlinger()
    valgt = [h for h in alle
             if (a.all or h["opgave"])
             and not h["lukket"]
             and (h["alder"] is None or h["alder"] >= a.days)]
    valgt.sort(key=lambda h: -(h["alder"] or 0))

    if a.json:
        print(json.dumps(valgt, ensure_ascii=False, indent=2))
        return 0

    if a.som_aftaler:
        # En handling i en log er ikke noget nogen bliver mindet om. Som aftale under
        # `## Aftaler` fanger wiki_brief den, når fristen overskrides.
        #
        # Forfaldsdatoen står med vilje som <FORFALD>. Den er ejerens beslutning, og en
        # opfundet dato ville se ud som en aftale nogen havde indgået. `aftalt` tages
        # derimod fra den dato handlingen faktisk blev skrevet — den er kendt.
        print("# Forslag til aftale-linjer. Sæt <FORFALD> og klip ind under `## Aftaler`")
        print("# på den relevante side. Slet Handling-linjen samme sted, så den ikke")
        print("# står to steder.\n")
        for h in valgt[: a.limit]:
            aftalt = h["dato"] or "<AFTALT>"
            hvad = re.sub(r"\s+", " ", h["tekst"]).strip()
            print(f"- [ ] (aftalt {aftalt}, forfald <FORFALD>) {EJER} → [[{h['side']}]]: {hvad[:140]}")
            print(f"      # {h['sti']}:{h['linje']}"
                  + (f"  ({h['alder']} dage gammel)" if h["alder"] is not None else ""))
        return 0

    opgaver = sum(1 for h in alle if h["opgave"])
    print(f"# Handling-linjer — {len(alle)} i alt, {opgaver} er opgaver, "
          f"{sum(1 for h in alle if h['lukket'])} markeret som udført\n")
    if not valgt:
        print("Ingen åbne handlinger over grænsen.")
        return 0
    print(f"## {len(valgt)} åbne{'' if a.all else ' opgaver'} ældre end {a.days} dage\n")
    for h in valgt[: a.limit]:
        alder = f"{h['alder']:>4}d" if h["alder"] is not None else "  ?d"
        print(f" {alder}  {h['sti']}:{h['linje']}")
        print(f"        {h['tekst'][:150]}")
    if len(valgt) > a.limit:
        print(f"\n   … og {len(valgt) - a.limit} mere (--limit)")
    print("\nEn handling her er ikke en aftale. Skal nogen holdes til den, hører den hjemme")
    print("under `## Aftaler` med forfaldsdato, så wiki_brief fanger den når den overskrides.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
