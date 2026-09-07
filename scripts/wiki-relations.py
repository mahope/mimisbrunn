#!/usr/bin/env python3
"""
Typede relationer: forslag og konvertering (issue #45).

Wikien har 3.000+ utypede `[[links]]`. De typede kanter tilføjes derfor lazily:
scriptet finder linjer under `## Relationer` hvor typen er entydig af konteksten
(linjen peger på en hosting-udbyder og siger "hosting", peger på et CMS, osv.)
og kan enten liste dem som forslag eller skrive dem om til det typede format.

Konverteringen er konservativ: den rører kun linjer hvor målet står på en kendt
liste OG linjen ikke allerede er typet. Alt andet er et forslag til et menneske.

Brug:
  python scripts/wiki-relations.py                 # vis forslag
  python scripts/wiki-relations.py --apply         # skriv de entydige om
  python scripts/wiki-relations.py --stats         # hvad findes der allerede
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

_spec = importlib.util.spec_from_file_location("wiki_mcp_server", ROOT / "scripts" / "wiki-mcp-server.py")
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)

# Mål der entydigt bestemmer prædikatet, når de optræder under ## Relationer.
HOSTING = {"hetzner", "dokploy", "hostinger", "simply", "vercel", "webdock", "one-com", "netlify"}
TOOLS = {"wordpress", "divi", "bricks-builder", "woocommerce", "nextjs", "laravel", "supabase",
         "vue", "astro", "tailwind", "sanity", "shopify"}

LINE_RE = re.compile(r"^(\s*-\s*)(\[\[[^\]]+\]\].*)$")
TYPED_RE = re.compile(r"^\s*-\s*[a-zæøå\-]{3,20}::")


def classify(target: str, line: str) -> str | None:
    low = line.lower()
    if target in HOSTING:
        if "hosting" in low or "server" in low or "platform" in low or target in ("hetzner", "dokploy"):
            return "hoster-hos"
    if target in TOOLS:
        return "bruger"
    return None


def scan():
    srv._refresh(force=True)
    found = []
    for p in srv._INDEX.values():
        if p.is_redirect or p.is_generated or p.folder not in ("clients", "projects", "people"):
            continue
        for head, text in srv._sections(p.body):
            if head.strip().lower() != "relationer":
                continue
            for line in text.split("\n"):
                if TYPED_RE.match(line):
                    continue
                m = LINE_RE.match(line)
                if not m:
                    continue
                link = re.match(r"\[\[([^\]|#]+)", m.group(2))
                if not link:
                    continue
                target = link.group(1).strip().lower()
                pred = classify(target, line)
                if pred:
                    found.append({"slug": p.slug, "path": p.path, "line": line.rstrip(),
                                  "predicate": pred, "target": target})
    return found


def apply(rows) -> int:
    by_file = {}
    for r in rows:
        by_file.setdefault(r["path"], []).append(r)
    changed = 0
    for path, items in by_file.items():
        text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        new = text
        for r in items:
            old_line = r["line"]
            indent = old_line[: len(old_line) - len(old_line.lstrip())]
            body = old_line.strip()[1:].strip()      # uden bindestregen
            typed = f"{indent}- {r['predicate']}:: {body}"
            if old_line in new:
                new = new.replace(old_line, typed, 1)
        if new != text:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed += len(items)
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="Typede relationer: forslag og konvertering")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    if a.stats:
        g = srv.wiki_graph()
        print(f"Typede kanter i wikien: {g['count']}")
        for pred in g["predicates"]:
            n = sum(1 for e in g["edges"] if e["predicate"] == pred)
            print(f"  {pred:16} {n}")
        return 0

    rows = scan()
    if not rows:
        print("Ingen entydige kandidater fundet.")
        return 0
    print(f"{len(rows)} entydige linjer kan typeses:\n")
    for r in rows:
        print(f"  [[{r['slug']}]]  {r['predicate']}:: {r['target']}")
        print(f"      {r['line'].strip()[:100]}")
    if a.apply:
        n = apply(rows)
        print(f"\nOmskrevet {n} linjer. Kør 'git diff' og commit dem du er enig i.")
    else:
        print("\nKør med --apply for at skrive dem om.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
