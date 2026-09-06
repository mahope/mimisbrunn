#!/usr/bin/env python3
"""
Kommandolinje-adgang til de samme funktioner som MCP-serveren udstiller.

Formaal: cloud-routiner har ikke MCP-adgang til wiki-mcp, og laeste derfor hele
`_index.md` (129 KB, ~35k tokens) ved hver koersel for at finde ud af om en side
fandtes. Med dette script kan de soege og skrive praecist i stedet (issue #30).

Brug:
  python scripts/wiki-cli.py search "solaris hosting" [--type client] [--limit 5] [--json]
  python scripts/wiki-cli.py outline solaris
  python scripts/wiki-cli.py get solaris [--section "Aftaler"] [--max-chars 4000]
  python scripts/wiki-cli.py related solaris
  python scripts/wiki-cli.py recent [--days 7]
  python scripts/wiki-cli.py append solaris "- **6. september 2026:** ..." [--section Noter] [--source "samtale 2026-09-06"]
  python scripts/wiki-cli.py create tool nyt-vaerktoej "Nyt Vaerktoej" "Én saetning." "# Nyt Vaerktoej\n\nTekst."

Alle skrivninger gaar gennem de samme regler som MCP'en: hemmeligheds-tjek,
modsigelses-detektion og commit. Saet WIKI_MCP_PUSH=1 for ogsaa at pushe.
"""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("WIKI_ROOT", str(ROOT))
os.environ.setdefault("WIKI_EMBED", "0")   # CLI'en skal starte hurtigt; BM25 + termmatch raekker

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

_spec = importlib.util.spec_from_file_location("wiki_mcp_server", ROOT / "scripts" / "wiki-mcp-server.py")
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)


def _out(obj, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(obj, list):
        for row in obj:
            if isinstance(row, dict) and "slug" in row:
                stale = " [stale]" if row.get("stale") else ""
                print(f"{row['slug']}  ({row.get('type', '?')}){stale}  {str(row.get('description', ''))[:110]}")
                if row.get("snippet"):
                    print(f"    {row['snippet'][:160]}")
            else:
                print(row)
    elif isinstance(obj, dict):
        if "error" in obj:
            print("FEJL:", obj["error"])
            sys.exit(1)
        if "text" in obj:
            print(obj["text"])
        else:
            print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    else:
        print(obj)


def main() -> int:
    ap = argparse.ArgumentParser(description="CLI til LLM Wikien (samme funktioner som MCP-serveren)")
    ap.add_argument("--json", action="store_true", help="rå JSON i stedet for kompakt tekst")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--type", default=""); p.add_argument("--limit", type=int, default=8); p.add_argument("--mode", default="rrf")
    p = sub.add_parser("outline"); p.add_argument("slug")
    p = sub.add_parser("get"); p.add_argument("slug"); p.add_argument("--section", default=""); p.add_argument("--max-chars", type=int, default=6000)
    p = sub.add_parser("related"); p.add_argument("slug")
    p = sub.add_parser("recent"); p.add_argument("--days", type=int, default=7); p.add_argument("--limit", type=int, default=25)
    p = sub.add_parser("stats")
    p = sub.add_parser("append"); p.add_argument("slug"); p.add_argument("text"); p.add_argument("--section", default=""); p.add_argument("--source", default="")
    p = sub.add_parser("create")
    p.add_argument("type"); p.add_argument("slug"); p.add_argument("entity"); p.add_argument("description"); p.add_argument("body")
    p.add_argument("--tags", default=""); p.add_argument("--aliases", default=""); p.add_argument("--source", default="")
    p.add_argument("--confidence", default="medium"); p.add_argument("--resource", default="")

    for sp in sub.choices.values():   # --json virker baade foer og efter underkommandoen
        sp.add_argument("--json", action="store_true", dest="json", default=False)
    a = ap.parse_args()
    if a.cmd == "search":
        _out(srv.wiki_search(a.query, type=a.type, limit=a.limit, mode=a.mode), a.json)
    elif a.cmd == "outline":
        _out(srv.wiki_outline(a.slug), a.json)
    elif a.cmd == "get":
        _out(srv.wiki_get(a.slug, section=a.section, max_chars=a.max_chars), a.json)
    elif a.cmd == "related":
        _out(srv.wiki_related(a.slug), a.json)
    elif a.cmd == "recent":
        _out(srv.wiki_recent(days=a.days, limit=a.limit), a.json)
    elif a.cmd == "stats":
        _out(srv.wiki_stats(), a.json)
    elif a.cmd == "append":
        _out(srv.wiki_append(a.slug, a.text, section=a.section, source=a.source), a.json)
    elif a.cmd == "create":
        _out(srv.wiki_create(a.type, a.slug, a.entity, a.description, a.body,
                             tags=[t.strip() for t in a.tags.split(",") if t.strip()],
                             aliases=[t.strip() for t in a.aliases.split(",") if t.strip()],
                             source=a.source, confidence=a.confidence, resource=a.resource), a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
