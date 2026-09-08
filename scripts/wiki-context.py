#!/usr/bin/env python3
"""
SessionStart-hook: finder de wiki-sider der matcher det projekt Claude er åbnet i,
og printer et kompakt kontekst-resumé (som injiceres i sessionen).

Matching (i prioriteret rækkefølge):
1. `resource:` i frontmatter indeholder repo-navnet (e.g. github.com/you/your-app)
2. mappenavnet er lig slug, entity eller et alias
3. mappenavnet nævnes i description

Output holdes under ~40 linjer: pr. side description, last_updated, confidence,
sidste "## "-sektion (afkortet) og de nyeste 3 datolinjer. Plus handover-hint.
Kør: echo '{"cwd":"C:/Projects/Freelance/timetrack"}' | python scripts/wiki-context.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml
try:  # libyaml: ~8x hurtigere frontmatter-parsing (issue #19)
    from yaml import CSafeLoader as _YamlLoader
except ImportError:  # pragma: no cover
    from yaml import SafeLoader as _YamlLoader

try:  # hooket koeres uden PYTHONIOENCODING; uden dette bliver aeoe til mojibake
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

WIKI = Path(__file__).resolve().parent.parent
ENTITIES = WIKI / "entities"
MAX_PAGES = 4
BUDGET_CHARS = 2400       # samlet budget for injiceret kontekst (ekskl. kritiske fakta)
PER_PAGE_CHARS = 700
MIN_SCORE = 4        # var 6; de fleste projekter fik kun kritiske fakta (issue #34)
GENERIC = {"projects", "projekter", "freelance", "documents", "dokumenter", "src", "repos", "code",
           "www", "app", "apps", "wiki", "users", "dev", "git", "kunder", "arbejde", "home"}


def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    try:
        return (yaml.load(m.group(1), Loader=_YamlLoader) or {}), text[m.end():]
    except Exception:
        return {}, text[m.end():]


def candidates(cwd: Path):
    names = []
    for part in reversed(cwd.parts):
        p = part.lower()
        # Mindst tre tegn og mindst ét bogstav: ellers slipper drevbogstaver ("c"),
        # separatorer og tal ind som søgenavne og matcher på kryds og tværs.
        if (len(p) >= 3 and any(ch.isalpha() for ch in p) and p not in GENERIC
                and not re.match(r"^[a-z]:[\\/]?$", p)):
            names.append(p)
        if len(names) >= 3:      # var 2; kundenavnet ligger tit et niveau hoejere (issue #34)
            break
    try:
        # Kun hvis mappen selv er repoets rod. Ligger den inde i et faelles parent-repo
        # (fx C:/Projects), ville parentens navn ellers blive soegenavn nummer ét for
        # hver eneste undermappe og matche paa kryds og tvaers (issue #34).
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                             capture_output=True, text=True, timeout=5)
        same_root = (top.returncode == 0
                     and Path(top.stdout.strip()).resolve() == Path(cwd).resolve())
        if same_root:
            r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd,
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                repo = re.sub(r"\.git$", "", r.stdout.strip().split("/")[-1].split(":")[-1]).lower()
                names.insert(0, repo)
    except Exception:
        pass
    return list(dict.fromkeys(names))


def recent_lines(body: str, n=3):
    dated = [l.strip() for l in body.splitlines() if re.match(r"^- \*\*\d{1,2}\. \w+ \d{4}", l.strip()) or re.match(r"^- \*\*20\d\d-", l.strip())]
    return [re.sub(r"\s+", " ", l)[:220] for l in dated[-n:]]


def last_section(body: str):
    parts = re.split(r"\n## ", body)
    if len(parts) < 2:
        return ""
    title, _, rest = parts[-1].partition("\n")
    rest = re.sub(r"\s+", " ", rest.strip())
    return f"{title.strip()}: {rest[:300]}"


def load_pages():
    """Rows fra _index/pages.json naar den er nyere end den nyeste entitet, ellers fuld scanning.

    Den fulde scanning laeser 900 filer (~670 ms) ved hver sessionsstart; cachen goer
    det til et enkelt json-load (issue #26).
    """
    cache = WIKI / "_index" / "pages.json"
    try:
        newest = max(f.stat().st_mtime for f in ENTITIES.glob("*/*.md"))
        if cache.exists() and cache.stat().st_mtime >= newest:
            return json.loads(cache.read_text(encoding="utf-8"))
    except Exception:
        pass
    rows = []
    for path in ENTITIES.glob("*/*.md"):
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
        except Exception:
            continue
        fm, body = frontmatter(text)
        if not isinstance(fm, dict) or str(fm.get("type", "")) == "redirect":
            continue
        rows.append({
            "slug": path.stem, "path": path.relative_to(WIKI).as_posix(),
            "entity": str(fm.get("entity") or path.stem), "type": str(fm.get("type") or path.parent.name),
            "aliases": [str(a) for a in (fm.get("aliases") or [])],
            "resource": str(fm.get("resource") or ""), "description": str(fm.get("description") or ""),
            "last_updated": str(fm.get("last_updated") or ""), "confidence": str(fm.get("confidence") or ""),
            "last_section": last_section(body), "recent": recent_lines(body),
        })
    return rows


def commitment_lines(limit: int = 5):
    """Forfaldne og naert forestaaende aftaler fra den genererede _followup-queue.md.

    Filen er lille, saa hooket kan laese den direkte i stedet for at loade MCP-serveren
    (issue #39). Er den ikke genereret endnu, vises ingenting.
    """
    path = WIKI / "_followup-queue.md"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    except Exception:
        return []
    picked, section = [], ""
    for line in text.split("\n"):
        if line.startswith("## "):
            section = line[3:].strip().lower()
        elif line.startswith("- [ ] ") and ("forfaldne" in section or "14 dage" in section):
            picked.append("  " + re.sub(r"\s+", " ", line[6:]).strip()[:200])
    if not picked:
        return []
    return ["[wiki-aftaler] Forfaldne eller nært forestående (kilde: _followup-queue.md):"] + picked[:limit]


def log_run(cwd, names, hits, used):
    """Én linje pr. sessionsstart i _index/context-hits.jsonl (gitignored).

    Uden den kan spørgsmålet "hvor ofte finder hooket noget" ikke besvares (issue #34).
    """
    try:
        rec = {"ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
               "cwd": str(cwd), "names": names,
               "hits": [[h[1]["slug"], h[0]] for h in hits[:5]],
               "n_hits": len(hits), "budget_used": used}
        d = WIKI / "_index"
        d.mkdir(exist_ok=True)
        with open(d / "context-hits.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main():
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        payload = {}
    cwd = Path(payload.get("cwd") or os.getcwd())
    if cwd.resolve() == WIKI.resolve():
        return 0  # i selve vaulten: CLAUDE.md dækker
    names = candidates(cwd)
    if not names:
        return 0
    hits = []
    for row in load_pages():
        slug = row["slug"].lower()
        entity = str(row.get("entity", "")).lower()
        aliases = [str(a).lower() for a in (row.get("aliases") or [])]
        resource = str(row.get("resource") or "").lower()
        desc = str(row.get("description") or "").lower()
        tags = [str(t).lower() for t in (row.get("tags") or [])]
        score = 0
        for i, n in enumerate(names):
            w = max(1, 3 - i)
            if resource and n in resource: score += 10 * w
            joined = slug.replace("-", "")
            if slug == n or entity == n or n in aliases: score += 8 * w
            # "enkundeogen" skal ramme siden "en-kunde-og-en": mappenavne har sjaeldent bindestreger
            elif len(n) > 5 and (joined == n.replace("-", "") or entity.replace(" ", "") == n): score += 7 * w
            elif slug.startswith(n) or n in slug: score += 3 * w
            elif n in tags: score += 3 * w
            elif re.search(rf"\b{re.escape(n)}\b", desc): score += 2 * w
            elif len(n) > 5 and n in entity: score += 2 * w
        if score:
            hits.append((score, row))
    hits = [h for h in hits if h[0] >= MIN_SCORE]
    out = []
    for l in commitment_lines():
        out.append(l)
    crit = WIKI / "_critical-facts.md"
    if crit.exists():
        _, cbody = frontmatter(crit.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n"))
        out.append("[wiki-kritiske-fakta] " + re.sub(r"\s+", " ", cbody.replace("# Kritiske fakta (altid loaded)", "")).strip()[:900])
    if not hits:
        log_run(cwd, names, [], 0)
        if out:
            print("\n".join(out))
        return 0
    hits.sort(key=lambda h: -h[0])
    out.append("[wiki-kontekst] Sider i LLM Wikien der matcher dette projekt (hent detaljer med wiki_outline/wiki_get):")
    used = 0
    for score, row in hits[:MAX_PAGES]:
        if used >= BUDGET_CHARS:
            break
        block = []
        block.append(f"- {row['entity']} ({row['type']}, opdateret {row.get('last_updated') or '?'}, confidence {row.get('confidence') or '?'}) -> {row['path']}")
        if row.get("description"):
            block.append(f"  {row['description']}")
        if row.get("last_section"):
            block.append(f"  Seneste sektion — {row['last_section'][:300]}")
        for l in (row.get("recent") or []):
            block.append(f"  {l}")
        text = "\n".join(block)
        if len(text) > PER_PAGE_CHARS:
            text = text[:PER_PAGE_CHARS].rsplit(" ", 1)[0] + " …"
        out.append(text)
        used += len(text)
    out.append("Skriv ny varig viden tilbage (wiki_append via MCP 'wiki' eller /wiki-save) før sessionen slutter.")
    log_run(cwd, names, hits, used)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
