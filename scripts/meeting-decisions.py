#!/usr/bin/env python3
"""
Møde → beslutninger og aftaler (issue #46).

Et transskript er råstof, ikke viden. Scriptet finder de replikker der *ligner* en
beslutning eller et løfte, viser dem ordret med taler, og skriver kun dem du peger på
ind i wikien. Det gætter aldrig og omskriver aldrig: et citat der ikke står i
transskriptet, kan ikke ende på en side.

Hver skrevet linje bærer det ordrette citat og hvem der sagde det, og får
`confidence: stated` — altså "kilden siger det", ikke "det er verificeret".

Brug:
  python scripts/meeting-decisions.py _sources/meetings/2026-07-08-....md
  python scripts/meeting-decisions.py <fil> --apply 2,5 --slug tidtilro-univers
  python scripts/meeting-decisions.py <fil> --apply 3 --slug john-tidtilro --commitment --due 2026-10-01
"""
import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("WIKI_ROOT", str(ROOT))
os.environ.setdefault("WIKI_EMBED", "0")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

SPEAKER_RE = re.compile(r"^\*\*\[([^\]]+)\]\*\*\s*(.+)$")
TIME_RE = re.compile(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]")

# Danske vendinger der markerer en beslutning eller et loefte. Bevidst snaevre:
# hellere overse noget end at foreslaa halvdelen af samtalen.
MARKERS = [
    (re.compile(r"\bvi (?:er |blev )?enige?\b", re.I), "beslutning"),
    (re.compile(r"\bs[åa] (?:g[øo]r|tager|k[øo]rer) vi\b", re.I), "beslutning"),
    (re.compile(r"\bvi (?:v[æa]lger|dropper|udskyder|beholder)\b", re.I), "beslutning"),
    (re.compile(r"\bdet bliver (?:s[åa]|til)\b", re.I), "beslutning"),
    (re.compile(r"\bjeg (?:sender|laver|bygger|kigger p[åa]|melder tilbage|f[øo]lger op)\b", re.I), "aftale"),
    (re.compile(r"\bdu (?:sender|leverer|vender tilbage)\b", re.I), "aftale"),
    (re.compile(r"\bdeadline\b|\binden (?:udgangen af|p[åa]) \w+", re.I), "aftale"),
    (re.compile(r"\bvi aftaler\b|\baftalt at\b", re.I), "aftale"),
]


# En aftale peger fremad. Uden et fremtids- eller modtager-signal er "jeg laver
# primaert WordPress" bare en beskrivelse, og saa er kandidaten stoej.
FUTURE_RE = re.compile(
    r"(?:i morgen|i dag|n[åa]ste uge|inden|senest|s[åa] snart|deadline"
    r"|p[åa] (?:mandag|tirsdag|onsdag|torsdag|fredag|l[øo]rdag|s[øo]ndag)"
    r"|n[åa]r (?:vi|du|jeg|det|der)|til (?:dig|jer|mig)|\bdig\b|\bjer\b"
    r"|\d{1,2}\.? ?(?:januar|februar|marts|april|maj|juni|juli|august|september|oktober|november|december))",
    re.I)


def load_srv():
    spec = importlib.util.spec_from_file_location("srv", ROOT / "scripts" / "wiki-mcp-server.py")
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    return srv


def candidates(text: str):
    """[(nr, taler, tidsstempel, citat, slags)] for replikker der ligner en beslutning."""
    out = []
    for raw in text.split("\n"):
        line = raw.strip()
        m = SPEAKER_RE.match(line)
        if not m:
            continue
        speaker, said = m.group(1).strip(), m.group(2).strip()
        t = TIME_RE.search(said)
        stamp = t.group(1) if t else ""
        for pat, kind in MARKERS:
            if pat.search(said) and (kind == "beslutning" or FUTURE_RE.search(said)):
                # klip til den saetning markoeren staar i, saa citatet er til at bruge
                parts = re.split(r"(?<=[.!?])\s+", said)
                quote = next((p for p in parts if pat.search(p)), said)
                out.append((len(out) + 1, speaker, stamp, quote.strip()[:400], kind))
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Find beslutninger og aftaler i et mødetransskript")
    ap.add_argument("file")
    ap.add_argument("--apply", default="", help="kommasepareret liste over numre der skal skrives")
    ap.add_argument("--slug", default="", help="entitetsside der skal skrives til")
    ap.add_argument("--commitment", action="store_true", help="skriv som aftale under ## Aftaler")
    ap.add_argument("--due", default="", help="frist til aftaler, YYYY-MM-DD")
    a = ap.parse_args()

    path = Path(a.file)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"Findes ikke: {a.file}")
        return 1
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    rows = candidates(text)
    if not rows:
        print("Ingen replikker matchede beslutnings- eller aftale-mønstrene.")
        return 0

    date = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    date = date.group(1) if date else ""
    print(f"{len(rows)} kandidater i {path.name}:\n")
    for n, speaker, stamp, quote, kind in rows:
        mark = f" [{stamp}]" if stamp else ""
        print(f"  {n:2}. ({kind}) {speaker}{mark}: “{quote[:150]}”")

    if not a.apply:
        print("\nVælg med --apply 2,5 --slug <side>. Intet skrives uden.")
        return 0
    if not a.slug:
        print("\n--apply kræver --slug.")
        return 1

    picked = {int(x) for x in re.findall(r"\d+", a.apply)}
    srv = load_srv()
    srv._refresh(force=True)
    written = 0
    for n, speaker, stamp, quote, kind in rows:
        if n not in picked:
            continue
        mark = f" ({stamp})" if stamp else ""
        rel = path.relative_to(ROOT).as_posix()
        if a.commitment or kind == "aftale":
            what = f"{quote} — sagt af {speaker}{mark}"
            res = srv.wiki_commit_add(a.slug, what, due=a.due, agreed=date or "")
        else:
            line = (f"- **{date or 'møde'} — beslutning:** “{quote}” — {speaker}{mark}. "
                    f"`confidence: stated`\n  [kilde: {rel}]")
            res = srv.wiki_append(a.slug, line, section="Beslutninger")
        ok = isinstance(res, dict) and not res.get("error")
        print(f"  {n}: {'skrevet' if ok else res.get('error')}")
        written += 1 if ok else 0
    print(f"\n{written} skrevet til [[{a.slug}]].")
    return 0


if __name__ == "__main__":
    sys.exit(main())
