#!/usr/bin/env python3
"""
Opgørelse over de påstande i wikien der kan efterprøves maskinelt.

Baggrund: en side om en deployment-platform skrev "opdatér fra v0.30.2" mens instansen kørte v0.29.13.
Forskellen indeholdt to sikkerhedsfix, og fejlen stod i uger. `wiki-freshness.py`
finder allerede kandidatlinjerne — 881 udaterede foranderlige værdier i 269 sider —
men en udifferentieret bunke er ikke til at handle på. Dette script klassificerer dem,
så versioner kan holdes op mod Dokploy og Hostinger, IP'er mod serverne, domæner mod
DNS, mens beløb og procenter forbliver et menneskeanliggende.

Scriptet efterprøver ikke selv noget og retter aldrig en side. En automatisk
overskrivning ville bare flytte tilliden ét led: peger kilden på den forkerte instans,
skriver den forkerte tal ind med høj konfidens.

Brug:
  python scripts/claims.py                     # oversigt pr. art
  python scripts/claims.py --kind version      # kun versionspåstande
  python scripts/claims.py --kind ip --undated # kun dem uden datomarkør
  python scripts/claims.py --json              # maskinlæsbart
  python scripts/claims.py --page dokploy      # alt på én side
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(os.environ.get("WIKI_ROOT", Path(__file__).resolve().parent.parent))
ENTITIES = ROOT / "entities"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

CODE_RE = re.compile(r"```.*?```", re.S)
DATED_RE = re.compile(
    r"(\(pr\. ?\d{4}-\d{2}|\(pr\. ?\d{1,2}/\d{1,2}|\[kilde:|\bkilde:|\d{4}-\d{2}-\d{2}"
    r"|\*\*\d{1,2}\.\s?\w+ \d{4}|\b\d{1,2}/\d{1,2}-\d{4}"
    r"|\b(jan|feb|mar|apr|maj|jun|jul|aug|sep|okt|nov|dec)\w* \d{4}|\bsamtale \d{4}|\bverificeret\b)", re.I)

# Arterne er ordnet efter hvor let de er at efterprøve. En IP eller et domæne har præcis
# ét rigtigt svar, en version har ét pr. instans, et beløb har ingen maskinel facitliste.
# Rækkefølgen afgør klassificeringen: "1.550 kr" er et beløb, ikke version 1.550,
# så beløb skal prøves før versioner.
KINDS = [
    ("ip",      re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("amount",  re.compile(r"\d[\d\.\s]*\s?(?:kr|dkk|%|€|eur|usd|\$)\b", re.I)),
    ("port",    re.compile(r"\bport(?:en)?\s*:?\s*(\d{2,5})\b", re.I)),
    # Kun noget der faktisk ligner et versionsnummer: v-præfiks eller tre led. Bare
    # "2.0" i en sætning om en model er ikke en påstand nogen kan slå efter.
    ("version", re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b|\b\d+\.\d+\.\d+\b")),
    ("domain",  re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:dk|com|net|org|io|dev|app|eu|se|no|de)\b", re.I)),
]
# Linjer der lover noget om driften uden at nævne et tal er stadig påstande.
RUNS_RE = re.compile(r"\b(kører (?:på|hos|i)|hostes (?:på|hos)|peger på|ligger på)\b", re.I)

# Domænenavne optræder overalt i kilde-stier og mail-adresser; dem gider vi ikke.
STØJ_RE = re.compile(r"(_sources/|@|https?://(?:github|gitlab)\.com)", re.I)


def sider():
    for p in sorted(ENTITIES.glob("*/*.md")):
        raw = p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        # Genererede hub-sider gentager andre siders påstande. Tæller man dem med, ser
        # den samme forkerte version ud som to problemer.
        if p.parent.name == "_hubs" or "\ngenerated: true" in raw[:600]:
            continue
        fm_slut = raw.find("\n---", 4) if raw.startswith("---") else -1
        body = raw[fm_slut + 4:] if fm_slut > 0 else raw
        yield p, CODE_RE.sub("", body)


def find_paastande():
    ud = []
    for p, body in sider():
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        for nr, linje in enumerate(body.split("\n"), 1):
            s = linje.strip()
            if not s or s.startswith(("#", ">", "|", "[kilde")):
                continue
            dateret = bool(DATED_RE.search(s))
            for art, rx in KINDS:
                m = rx.search(s)
                if not m:
                    continue
                if art == "domain" and STØJ_RE.search(s):
                    continue
                ud.append({"side": p.stem, "sti": rel, "linje": nr, "art": art,
                           "vaerdi": m.group(0), "dateret": dateret, "tekst": s[:160]})
                break
            else:
                if RUNS_RE.search(s):
                    ud.append({"side": p.stem, "sti": rel, "linje": nr, "art": "runs-on",
                               "vaerdi": "", "dateret": dateret, "tekst": s[:160]})
    return ud


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="", choices=[""] + [k for k, _ in KINDS] + ["runs-on"])
    ap.add_argument("--page", default="", help="kun denne side (slug)")
    ap.add_argument("--undated", action="store_true", help="kun påstande uden datomarkør")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    alle = find_paastande()
    valgt = [c for c in alle
             if (not a.kind or c["art"] == a.kind)
             and (not a.page or c["side"] == a.page)
             and (not a.undated or not c["dateret"])]

    if a.json:
        print(json.dumps(valgt, ensure_ascii=False, indent=2))
        return 0

    tael = Counter(c["art"] for c in alle)
    udateret = Counter(c["art"] for c in alle if not c["dateret"])
    print(f"# Efterprøvelige påstande — {len(alle)} i alt\n")
    print(f"  {'art':<10} {'i alt':>7} {'udateret':>9}   efterprøves mod")
    kilder = {"ip": "Hetzner/Hostinger, DNS", "domain": "DNS, Dokploy-domæner",
              "version": "Dokploy, Hostinger, package.json", "port": "Dokploy, compose-filer",
              "amount": "ingen maskinel kilde — menneske", "runs-on": "Dokploy, Hostinger"}
    for art in [k for k, _ in KINDS] + ["runs-on"]:
        if tael[art]:
            print(f"  {art:<10} {tael[art]:>7} {udateret[art]:>9}   {kilder.get(art, '')}")

    if a.kind or a.page:
        print(f"\n## {len(valgt)} udvalgte\n")
        for c in valgt[: a.limit]:
            mark = " " if c["dateret"] else "!"
            print(f" {mark} {c['sti']}:{c['linje']}  [{c['vaerdi']}]  {c['tekst'][:100]}")
        if len(valgt) > a.limit:
            print(f"   … og {len(valgt) - a.limit} mere (--limit)")
    else:
        print("\nVælg en art for at se linjerne, fx: python scripts/claims.py --kind version --undated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
