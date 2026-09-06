#!/usr/bin/env python3
"""
Rapport over aftaler og løfter i wikien (issue #38).

Læser "## Aftaler"-sektionerne på alle sider gennem de samme funktioner som
MCP-serveren og skriver en oversigt: forfaldne først, derefter det der forfalder
snart, derefter aftaler uden dato.

Brug:
  python scripts/wiki-commitments.py                 # rapport i terminalen
  python scripts/wiki-commitments.py --person john   # kun aftaler der involverer john
  python scripts/wiki-commitments.py --write         # skriv ogsaa _followup-queue.md
  python scripts/wiki-commitments.py --json          # maskinlæsbart
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("WIKI_ROOT", str(ROOT))
os.environ.setdefault("WIKI_EMBED", "0")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

_spec = importlib.util.spec_from_file_location("wiki_mcp_server", ROOT / "scripts" / "wiki-mcp-server.py")
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)

HEADER = """---
title: Aftaler og opfølgning
description: "Genereret af scripts/wiki-commitments.py fra ## Aftaler-sektionerne. Redigér ikke i hånden."
generated: true
last_updated: {today}
tags: [followup, aftaler, generated]
---

# Aftaler og opfølgning

Genereret {today} af `scripts/wiki-commitments.py`. Kilden er `## Aftaler`-sektionerne
på entitetssiderne; ret dem der, ikke her. Formatet er beskrevet i `_schema.md`.
"""


def sync_frontmatter(rows) -> list[str]:
    """Skriv `open_commitments` og `next_due` i frontmatter paa de sider der har aftaler.

    Obsidian Bases kan kun filtrere paa frontmatter, ikke paa markdown-sektioner, saa uden
    de to felter kan visningen ikke skelne sider med aftaler fra resten (issue #40).
    Felterne fjernes igen naar den sidste aabne aftale paa siden er krydset af.
    """
    import re as _re
    by_slug = {}
    for c in rows:
        cur = by_slug.setdefault(c["slug"], {"path": c["path"], "n": 0, "due": []})
        cur["n"] += 1
        if c["due"]:
            cur["due"].append(c["due"])

    touched = []
    for path in sorted((ROOT / "entities").glob("*/*.md")):
        slug = path.stem
        text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        m = _re.match(r"---\n(.*?)\n---\n", text, _re.S)
        if not m:
            continue
        fm, body = m.group(1), text[m.end():]
        info = by_slug.get(slug)
        new_fm = _re.sub(r"^open_commitments:.*\n?", "", fm, flags=_re.M)
        new_fm = _re.sub(r"^next_due:.*\n?", "", new_fm, flags=_re.M).rstrip("\n")
        if info:
            new_fm += f"\nopen_commitments: {info['n']}"
            if info["due"]:
                new_fm += f"\nnext_due: {min(info['due'])}"
        if new_fm != fm:
            path.write_text("---\n" + new_fm + "\n---\n" + body, encoding="utf-8", newline="\n")
            touched.append(path.relative_to(ROOT).as_posix())
    return touched


def group(rows):
    """(forfaldne, inden for 14 dage, senere med dato, uden dato)."""
    soon = dt.date.today() + dt.timedelta(days=14)
    overdue, upcoming, later, undated = [], [], [], []
    for c in rows:
        if c["overdue_days"] > 0:
            overdue.append(c)
            continue
        d = srv._to_date(c["due"]) if c["due"] else None
        if d is None:
            undated.append(c)
        elif d <= soon:
            upcoming.append(c)
        else:
            later.append(c)
    return overdue, upcoming, later, undated


def line(c):
    who = f"{c['owner']} → {c['counterpart']}"
    when = f"forfald {c['due']}" if c["due"] else "ingen frist"
    if c["overdue_days"] > 0:
        when += f", **{c['overdue_days']} dage over**"
    return f"- [ ] {who}: {c['what']}  ({when}) — [[{c['slug']}]]"


def main() -> int:
    ap = argparse.ArgumentParser(description="Aftaler og opfølgning fra wikien")
    ap.add_argument("--person", default="", help="filtrér på navn eller slug")
    ap.add_argument("--include-done", action="store_true")
    ap.add_argument("--write", action="store_true", help="skriv _followup-queue.md")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sync-frontmatter", action="store_true",
                    help="skriv open_commitments og next_due i frontmatter (til Obsidian Bases)")
    a = ap.parse_args()

    rows = srv.wiki_commitments(person=a.person, include_done=a.include_done, limit=500)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    overdue, upcoming, later, undated = group(rows)
    today = dt.date.today().isoformat()
    out = []
    for title, items in (("Forfaldne", overdue), ("Forfalder inden for 14 dage", upcoming),
                         ("Senere", later), ("Uden frist", undated)):
        out.append(f"\n## {title} ({len(items)})\n")
        out.extend(line(c) for c in items) if items else out.append("- ingen")
    body = "\n".join(out)
    print(f"Aftaler i alt: {len(rows)}  (forfaldne {len(overdue)}, inden for 14 dage {len(upcoming)}, "
          f"senere {len(later)}, uden frist {len(undated)})")
    print(body)

    if a.sync_frontmatter:
        touched = sync_frontmatter(rows)
        print(f"\nFrontmatter opdateret paa {len(touched)} sider" + (": " + ", ".join(touched) if touched else ""))

    if a.write:
        path = ROOT / "_followup-queue.md"
        path.write_text(HEADER.format(today=today) + body + "\n", encoding="utf-8", newline="\n")
        print(f"\nSkrevet: {path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
