#!/usr/bin/env python3
"""
Progressiv opsummering af lange logsider (issue #49).

Store sider er et reelt problem, ikke et æstetisk: målt i answer-eval kunne fakta i
`timetrack.md` (60 KB) og `ovardo.md` (48 KB) hverken findes eller læses, fordi BM25
straffer lange sider og `wiki_get` afkorter. Sektions-indekset hjalp på det første;
dette script tager det andet.

Metoden er konservativ: daterede linjer ældre end en grænse flyttes uændret til
`## Historik (foldet)` nederst på siden, i kronologisk orden. Intet omskrives, intet
slettes, og alle `[kilde:]`-markører følger med. Scriptet tæller dem før og efter og
nægter at skrive hvis tallet ikke stemmer.

Brug:
  python scripts/wiki-fold.py                        # hvad ville ske
  python scripts/wiki-fold.py --min-kb 30            # kun sider over 30 KB
  python scripts/wiki-fold.py --older-than 365       # dage
  python scripts/wiki-fold.py --apply --slug timetrack
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTITIES = ROOT / "entities"
FOLD_HEADING = "## Historik (foldet)"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

MONTHS = ["januar", "februar", "marts", "april", "maj", "juni", "juli",
          "august", "september", "oktober", "november", "december"]
MONTH_NO = {m: i + 1 for i, m in enumerate(MONTHS)}
MONTH_ALT = "|".join(MONTHS)

# "- **10. august 2026 — ..." / "- **Maj 2023:** ..." / "- **2026-08-14:** ..."
PATTERNS = [
    re.compile(rf"^-\s*\*\*\s*(?P<d>\d{{1,2}})\.?\s*(?P<m>{MONTH_ALT})\s+(?P<y>\d{{4}})", re.I),
    re.compile(rf"^-\s*\*\*\s*(?P<m>{MONTH_ALT})\s+(?P<y>\d{{4}})", re.I),
    re.compile(r"^-\s*\*\*\s*(?P<y>\d{4})-(?P<mn>\d{2})-(?P<dn>\d{2})"),
]


def line_date(line: str):
    s = line.strip()
    for pat in PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        g = m.groupdict()
        try:
            if g.get("mn"):
                return dt.date(int(g["y"]), int(g["mn"]), int(g["dn"]))
            month = MONTH_NO[g["m"].lower()]
            return dt.date(int(g["y"]), month, int(g.get("d") or 1))
        except Exception:
            return None
    return None


def block_of(lines, i):
    """En logpost er linjen plus dens indrykkede fortsættelser (kilde-markører m.m.)."""
    block = [lines[i]]
    j = i + 1
    while j < len(lines) and (lines[j].startswith("  ") or lines[j].startswith("\t")
                              or (lines[j].strip().startswith(">") and lines[j].startswith(" "))):
        block.append(lines[j])
        j += 1
    return block, j


def fold(text: str, cutoff: dt.date):
    """(ny tekst, antal foldede poster) — eller (None, 0) hvis intet skal foldes."""
    if FOLD_HEADING in text:
        head, _, tail = text.partition(FOLD_HEADING)
        existing = tail.split("\n", 1)[1] if "\n" in tail else ""
        text = head.rstrip("\n")
    else:
        existing = ""

    lines = text.split("\n")
    kept, folded = [], []
    i = 0
    in_fold_section = False
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            in_fold_section = False
        d = line_date(line)
        if d is not None and d < cutoff and not in_fold_section:
            block, i = block_of(lines, i)
            folded.append((d, block))
            continue
        kept.append(line)
        i += 1

    if not folded:
        return None, 0

    folded.sort(key=lambda x: x[0])
    out = "\n".join(kept).rstrip("\n")
    out += f"\n\n{FOLD_HEADING}\n\n"
    out += ("> Daterede punkter ældre end grænsen, flyttet hertil uændret af "
            "`scripts/wiki-fold.py`. Intet er omskrevet eller slettet.\n\n")
    for _, block in folded:
        out += "\n".join(block) + "\n"
    if existing.strip():
        out += "\n" + existing.strip() + "\n"
    return out, len(folded)


def main() -> int:
    ap = argparse.ArgumentParser(description="Fold gamle logposter ned i en historik-sektion")
    ap.add_argument("--older-than", type=int, default=365, help="dage (default 365)")
    ap.add_argument("--min-kb", type=int, default=25, help="rør kun sider over denne størrelse")
    ap.add_argument("--slug", default="", help="kun denne side")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    cutoff = dt.date.today() - dt.timedelta(days=a.older_than)
    total_pages = total_blocks = 0
    for path in sorted(ENTITIES.glob("*/*.md")):
        if a.slug and path.stem != a.slug:
            continue
        raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        if len(raw) < a.min_kb * 1024:
            continue
        m = re.match(r"---\n.*?\n---\n", raw, re.S)
        fm, body = (raw[: m.end()], raw[m.end():]) if m else ("", raw)
        new_body, n = fold(body, cutoff)
        if not n:
            continue
        # Sikkerhedsnet: intet må forsvinde.
        before_src = body.count("[kilde:")
        after_src = new_body.count("[kilde:")
        before_lines = len([l for l in body.split("\n") if l.strip()])
        after_lines = len([l for l in new_body.split("\n") if l.strip()])
        ok = before_src == after_src and after_lines >= before_lines
        flag = "OK " if ok else "SPRINGER OVER"
        print(f"{flag} {path.stem:34} {n:3} poster foldet  "
              f"({len(raw)/1024:.0f} KB, kilder {before_src}->{after_src}, linjer {before_lines}->{after_lines})")
        if a.apply and ok:
            path.write_text(fm + new_body, encoding="utf-8", newline="\n")
        total_pages += 1
        total_blocks += n

    if not total_pages:
        print(f"Ingen sider over {a.min_kb} KB har poster ældre end {cutoff.isoformat()}.")
    elif not a.apply:
        print(f"\n{total_blocks} poster på {total_pages} sider. Kør med --apply for at gøre det.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
