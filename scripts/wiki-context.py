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

WIKI = Path(__file__).resolve().parent.parent
ENTITIES = WIKI / "entities"
MAX_PAGES = 3
GENERIC = {"projects", "freelance", "documents", "src", "repos", "code", "www", "app", "wiki", "users", "home"}


def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    try:
        return (yaml.safe_load(m.group(1)) or {}), text[m.end():]
    except Exception:
        return {}, text[m.end():]


def candidates(cwd: Path):
    names = []
    for part in reversed(cwd.parts):
        p = part.lower()
        if p and p not in GENERIC and not re.match(r"^[a-z]:\\?$", p):
            names.append(p)
        if len(names) >= 2:
            break
    try:
        r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd, capture_output=True, text=True, timeout=5)
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
    for path in ENTITIES.glob("*/*.md"):
        text = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
        fm, body = frontmatter(text)
        if not isinstance(fm, dict):
            continue
        slug = path.stem.lower()
        entity = str(fm.get("entity", "")).lower()
        aliases = [str(a).lower() for a in (fm.get("aliases") or [])]
        resource = str(fm.get("resource") or "").lower()
        desc = str(fm.get("description") or "").lower()
        score = 0
        for i, n in enumerate(names):
            w = 3 - i
            if resource and n in resource: score += 10 * w
            if slug == n or entity == n or n in aliases: score += 8 * w
            elif slug.startswith(n) or n in slug: score += 3 * w
            elif re.search(rf"\b{re.escape(n)}\b", desc): score += 2 * w
        if score:
            hits.append((score, path, fm, body))
    if not hits:
        return 0
    hits.sort(key=lambda h: -h[0])
    out = ["[wiki-kontekst] Sider i LLM Wikien der matcher dette projekt (læs dem ved behov med Read):"]
    for score, path, fm, body in hits[:MAX_PAGES]:
        rel = path.relative_to(WIKI).as_posix()
        out.append(f"- {fm.get('entity', path.stem)} ({fm.get('type', path.parent.name)}, opdateret {fm.get('last_updated', '?')}, confidence {fm.get('confidence', '?')}) -> {rel}")
        if fm.get("description"):
            out.append(f"  {fm['description']}")
        ls = last_section(body)
        if ls:
            out.append(f"  Seneste sektion — {ls}")
        for l in recent_lines(body):
            out.append(f"  {l}")
    out.append("Skriv ny varig viden tilbage til disse sider (wiki_append via MCP 'wiki' eller /wiki-save) før sessionen slutter.")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
