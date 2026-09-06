"""Foreslå aftale-kandidater til _review-queue.md (issue #38).

Finder fremadrettede formuleringer på aktive sider fra de seneste måneder og
lister dem som forslag. Konverterer intet automatisk: en aftale skal bekræftes
af et menneske, ellers fabrikerer vi forpligtelser.
"""
import datetime as dt
import importlib.util
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["WIKI_ROOT"] = str(ROOT)
os.environ["WIKI_EMBED"] = "0"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

spec = importlib.util.spec_from_file_location("srv", ROOT / "scripts" / "wiki-mcp-server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)
srv._refresh(force=True)

PROMISE = re.compile(
    r"\b(afventer|vender tilbage|jeg sender|mads sender|skal sende|skal levere|leverer|"
    r"deadline|frist|inden udgangen|lovet|aftalt at|forventer at|går i gang|næste skridt|"
    r"mangler at|skal have|følger op|opfølgning)\b", re.I)
MONTHS = "januar|februar|marts|april|maj|juni|juli|august|september|oktober|november|december"
DATED = re.compile(rf"\*\*\s*\d{{1,2}}\.?\s*(?:[-–]\s*\d{{1,2}}\.?\s*)?({MONTHS})\s*(\d{{4}})", re.I)
CUTOFF = dt.date.today() - dt.timedelta(days=120)
MONTH_NO = {m: i + 1 for i, m in enumerate(MONTHS.split("|"))}

rows = []
for p in srv._INDEX.values():
    if p.is_redirect or p.is_generated:
        continue
    if p.folder not in ("clients", "projects", "people"):
        continue
    if str(p.fm.get("status", "")).lower() in srv.ARCHIVED_STATUS:
        continue
    if "## Aftaler" in p.body:
        continue                      # har allerede aftaler, spring over
    for line in p.body.split("\n"):
        line = line.strip()
        if not line.startswith("- ") or len(line) < 40:
            continue
        m = DATED.search(line)
        if not m or not PROMISE.search(line):
            continue
        month, year = MONTH_NO[m.group(1).lower()], int(m.group(2))
        try:
            when = dt.date(year, month, 1)
        except ValueError:
            continue
        if when < CUTOFF.replace(day=1):
            continue
        rows.append((when, p.slug, re.sub(r"\s+", " ", line)[:220]))

rows.sort(key=lambda r: (-r[0].toordinal(), r[1]))
seen, out = set(), []
for when, slug, line in rows:
    if slug in seen:
        continue                      # højst ét forslag pr. side, så listen kan overskues
    seen.add(slug)
    out.append((when, slug, line))

print(f"{len(rows)} kandidatlinjer på {len(seen)} sider\n")
for when, slug, line in out[:30]:
    print(f"[[{slug}]] ({when:%Y-%m})\n    {line}\n")

if "--write" in sys.argv:
    rq = ROOT / "_review-queue.md"
    text = rq.read_text(encoding="utf-8-sig").replace("\r\n", "\n") if rq.exists() else "# Review-kø\n"
    head = "## Aftale-kandidater"
    if head in text:
        text = text[:text.index(head)].rstrip("\n") + "\n"
    block = [f"\n{head}\n",
             "Fremadrettede formuleringer fundet på aktive sider (issue #38). Bekræft eller afvis;",
             "en bekræftet linje flyttes til sidens `## Aftaler` i formatet fra `_schema.md`.",
             f"Genereret {dt.date.today().isoformat()} af `scripts/wiki-commit-candidates.py`.\n"]
    for when, slug, line in out[:30]:
        block.append(f"- [ ] [[{slug}]] ({when:%Y-%m}) {line}")
    rq.write_text(text.rstrip("\n") + "\n" + "\n".join(block) + "\n", encoding="utf-8", newline="\n")
    print(f"\nSkrevet {len(out[:30])} forslag til _review-queue.md")
