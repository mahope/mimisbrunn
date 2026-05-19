#!/usr/bin/env python3
"""Regenerate Wiki/_index.md from the entities/ filesystem."""
import re, yaml
from datetime import date
from pathlib import Path

wiki = Path(__file__).resolve().parent.parent
categories = ["clients", "people", "projects", "tools", "concepts", "places", "recipes"]
labels = {"clients":"Clients","people":"People","projects":"Projects","tools":"Tools","concepts":"Concepts","places":"Places","recipes":"Recipes"}

def extract_frontmatter(content):
    if not content.startswith("---"):
        return {}
    try:
        end = content.index("---", 3)
        return yaml.safe_load(content[3:end].strip()) or {}
    except Exception:
        return {}

def get_display_name(filename, content):
    fm = extract_frontmatter(content)
    return fm.get("entity") or filename.replace(".md", "").replace("-", " ").title()

def get_summary(content):
    lines = content.split("\n")
    past_fm = False
    past_h1 = False
    for line in lines:
        if line.strip() == "---":
            past_fm = not past_fm
            continue
        if past_fm:
            continue
        if line.startswith("> "):
            continue
        if line.startswith("# "):
            past_h1 = True
            continue
        if past_h1 and line.strip() and not line.startswith("#") and not line.startswith("**"):
            clean = re.sub(r'\[\[([^\|\]]+)(\|[^\]]+)?\]\]', lambda m: (m.group(2)[1:] if m.group(2) else m.group(1)), line.strip())
            return clean[:100] + ("..." if len(clean) > 100 else "")
    return ""

out = ["---", "title: Wiki Index", "description: Automatisk genereret indholdsfortegnelse", "---", "", "# Wiki Index", "", f"> Genereret automatisk fra `entities/`. Kør `python scripts/regen-index.py` for at opdatere.", ""]

total = 0
for cat in categories:
    catdir = wiki / "entities" / cat
    if not catdir.exists():
        continue
    files = sorted([f for f in catdir.iterdir() if f.suffix == ".md"])
    total += len(files)
    out.append(f"## {labels[cat]} ({len(files)})")
    for f in files:
        try:
            content = f.read_text(encoding="utf-8")
            name = get_display_name(f.name, content)
            summary = get_summary(content)
            stem = f.stem
            if summary and len(summary) > 10:
                out.append(f"- [[{stem}|{name}]] — {summary}")
            else:
                out.append(f"- [[{stem}|{name}]]")
        except Exception:
            out.append(f"- [[{f.stem}]]")
    out.append("")

out.append("---")
out.append("")
out.append(f"**Antal sider:** {total}")
out.append(f"**Sidst opdateret:** {date.today().isoformat()} (auto-genereret)")

(wiki / "_index.md").write_text("\n".join(out), encoding="utf-8")
print(f"Regenerated _index.md with {total} entries across {len(categories)} categories")
