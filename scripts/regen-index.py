#!/usr/bin/env python3
"""Regenerate Wiki/_index.md from the entities/ filesystem."""
import re, yaml
from datetime import date
from pathlib import Path
try:  # libyaml: ~8x hurtigere frontmatter-parsing (issue #19)
    from yaml import CSafeLoader as _YamlLoader
except ImportError:  # pragma: no cover
    from yaml import SafeLoader as _YamlLoader

wiki = Path(__file__).resolve().parent.parent
categories = ["clients", "people", "projects", "tools", "concepts", "places", "recipes"]
labels = {"clients":"Clients","people":"People","projects":"Projects","tools":"Tools","concepts":"Concepts","places":"Places","recipes":"Recipes"}

def extract_frontmatter(content):
    if not content.startswith("---"):
        return {}
    try:
        end = content.index("---", 3)
        return yaml.load(content[3:end].strip(), Loader=_YamlLoader) or {}
    except Exception:
        return {}

def is_redirect(f):
    try:
        return extract_frontmatter(f.read_text(encoding="utf-8")[:600]).get("type") == "redirect"
    except Exception:
        return False


# ---------------------------------------------------------------- hub-sider (issue #15)
# cluster -> (titel, beskrivelse, match-funktion på (kategori, frontmatter))
HUBS = {
    "aktive-kunder": ("Aktive kunder", "Kunder uden status tabt/tidligere/arkiveret.",
                      lambda cat, fm: cat == "clients" and str(fm.get("status", "")).lower() not in ("tabt", "tidligere-kunde", "archived", "afsluttet", "parkeret", "lost")),
    "tidligere-kunder-og-leads": ("Tidligere kunder og tabte leads", "Kunder med status tabt/tidligere.",
                      lambda cat, fm: cat == "clients" and str(fm.get("status", "")).lower() in ("tabt", "tidligere-kunde", "archived", "afsluttet", "lost")),
    "aktive-projekter": ("Aktive projekter", "Projekter uden status archived/parkeret.",
                      lambda cat, fm: cat == "projects" and str(fm.get("status", "")).lower() not in ("archived", "afsluttet", "parkeret", "done", "completed", "arkiveret")),
    "wordpress-stack": ("WordPress-stack", "Tools og koncepter tagget wordpress/bricks/woocommerce.",
                      lambda cat, fm: cat in ("tools", "concepts") and bool({"wordpress", "bricks", "bricks-builder", "woocommerce", "acf"} & {str(t).lower() for t in (fm.get("tags") or [])})),
    "ai-og-agenter": ("AI og agenter", "Tools og koncepter tagget ai/agents/mcp/claude-code.",
                      lambda cat, fm: cat in ("tools", "concepts") and bool({"ai", "agents", "agenter", "mcp", "claude-code", "llm", "second-brain"} & {str(t).lower() for t in (fm.get("tags") or [])})),
    "spejder": ("Spejder (DDS, KFUM, Solaris)", "Alt tagget spejder/dds/kfum/solaris.",
                      lambda cat, fm: bool({"spejder", "dds", "kfum", "solaris"} & {str(t).lower() for t in (fm.get("tags") or [])})),
    "egne-produkter": ("Egne produkter og infrastruktur", "Projekter tagget egenprodukt/saas/infrastructure eller mahope-værktøjer.",
                      lambda cat, fm: cat == "projects" and bool({"egenprodukt", "saas", "saas-potentiale", "infrastructure", "infrastruktur", "mahope", "mahoje"} & {str(t).lower() for t in (fm.get("tags") or [])})),
}
HUB_WARN = 25


def _hub_existing(path):
    """(created, body uden last_updated) for en eksisterende hub-fil, ellers (None, None)."""
    if not path.exists():
        return None, None
    txt = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    m = re.search(r"^created: (\d{4}-\d{2}-\d{2})$", txt, re.M)
    created = m.group(1) if m else None
    body = re.sub(r"^last_updated: \d{4}-\d{2}-\d{2}\n", "", txt, count=1, flags=re.M)
    return created, body


def write_hubs(pages):
    """pages: liste af (cat, stem, name, fm). Skriver entities/_hubs/<cluster>.md idempotent.

    Skriver kun naar medlemslisten faktisk aendrer sig: `created` bevares fra den
    eksisterende fil, og `last_updated` bumpes kun ved reelle aendringer. Ellers
    efterlader hver koersel vaulten dirty (issue #18).
    """
    hubdir = wiki / "entities" / "_hubs"
    hubdir.mkdir(exist_ok=True)
    today = date.today().isoformat()
    links = []
    for key, (title, desc, match) in HUBS.items():
        members = sorted((stem, name, str(fm.get("description", "") or "")) for cat, stem, name, fm in pages if match(cat, fm))
        path = hubdir / f"hub-{key}.md"
        created, prev_body = _hub_existing(path)
        head = ["---", f'entity: "Hub: {title}"', "type: concept",
                f'description: "{desc} Genereret af regen-index.py; {len(members)} medlemmer."',
                f"aliases: [hub-{key}]", "sources: []", "confidence: high",
                f"created: {created or today}"]
        tail = ["tags: [hub, generated]", "generated: true", "---", "", f"# Hub: {title}", "",
                f"> {desc} Genereres automatisk \u2014 redig\u00e9r ikke i h\u00e5nden.", "", "## Medlemmer", ""]
        for stem, name, d in members:
            tail.append(f"- [[{stem}|{name}]]" + (f" \u2014 {d[:140]}" if d else ""))
        tail += ["", "## Andre hubs", ""] + [f"- [[hub-{k2}|{t2}]]" for k2, (t2, _, _) in HUBS.items() if k2 != key] + [""]
        body_wo_stamp = "\n".join(head + tail)
        if prev_body != body_wo_stamp:
            content = "\n".join(head + [f"last_updated: {today}"] + tail)
            path.write_text(content, encoding="utf-8", newline="\n")
        links.append(f"- [[hub-{key}|{title}]] ({len(members)})")
        if len(members) > HUB_WARN:
            print(f"ADVARSEL: hub {key} har {len(members)} medlemmer (> {HUB_WARN}) \u2014 overvej split")
    return links


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

out = ["---", "title: Wiki Index", "description: Automatisk genereret indholdsfortegnelse", "---", "", "# Wiki Index", "", f"> Genereret automatisk fra `entities/`. Kør `python scripts/regen-index.py` for at opdatere.", "",
       "**Visninger i Obsidian:** [[clients.base|Kunder]] · [[stale.base|Forældede sider]] · "
       "[[commitments.base|Åbne aftaler]] · [[review.base|Til gennemgang]] (mappen `_bases/`).", ""]

total = 0
all_pages = []
for cat in categories:
    catdir = wiki / "entities" / cat
    if not catdir.exists():
        continue
    files = sorted([f for f in catdir.iterdir() if f.suffix == ".md" and not is_redirect(f)])
    total += len(files)
    out.append(f"## {labels[cat]} ({len(files)})")
    for f in files:
        try:
            content = f.read_text(encoding="utf-8")
            name = get_display_name(f.name, content)
            summary = get_summary(content)
            stem = f.stem
            all_pages.append((cat, stem, name, extract_frontmatter(content)))
            if summary and len(summary) > 10:
                out.append(f"- [[{stem}|{name}]] — {summary}")
            else:
                out.append(f"- [[{stem}|{name}]]")
        except Exception:
            out.append(f"- [[{f.stem}]]")
    out.append("")

hub_links = write_hubs(all_pages)
out.append("## Hubs (genereret)")
out.extend(hub_links)
out.append("")
out.append("---")
out.append("")
out.append(f"**Antal sider:** {total}")
out.append(f"**Sidst opdateret:** {date.today().isoformat()} (auto-genereret)")

(wiki / "_index.md").write_text("\n".join(out), encoding="utf-8")

# Kompakt cache til SessionStart-hooket: uden den laeser hooket alle 900 filer ved
# hver sessionsstart (issue #26). Ligger i _index/ som er gitignored.
def _write_pages_json():
    import json as _json
    rows = []
    for cat in categories:
        d = wiki / "entities" / cat
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            text = f.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
            fm = extract_frontmatter(text) or {}
            if not isinstance(fm, dict) or str(fm.get("type", "")) == "redirect":
                continue
            body = text.split("---\n", 2)[-1] if text.startswith("---") else text
            secs = body.split("\n## ")
            last = ""
            if len(secs) > 1:
                title, _, rest = secs[-1].partition("\n")
                last = (title.strip() + ": " + " ".join(rest.split()))[:400]
            dated = [" ".join(l.split())[:220] for l in body.splitlines()
                     if l.startswith("- **") and any(ch.isdigit() for ch in l[:14])]
            rows.append({
                "slug": f.stem, "folder": cat, "path": f.relative_to(wiki).as_posix(),
                "entity": str(fm.get("entity") or f.stem), "type": str(fm.get("type") or cat),
                "aliases": [str(a) for a in (fm.get("aliases") or [])],
                "resource": str(fm.get("resource") or ""),
                "description": str(fm.get("description") or ""),
                "last_updated": str(fm.get("last_updated") or ""),
                "confidence": str(fm.get("confidence") or ""),
                "last_section": last, "recent": dated[-3:],
            })
    outdir = wiki / "_index"
    outdir.mkdir(exist_ok=True)
    (outdir / "pages.json").write_text(_json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return len(rows)


print(f"Wrote _index/pages.json ({_write_pages_json()} pages)")
print(f"Regenerated _index.md with {total} entries across {len(categories)} categories")
