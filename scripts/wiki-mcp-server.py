#!/usr/bin/env python3
"""
Wiki MCP server — giver enhver MCP-klient (Claude Code, Claude Desktop, claude.ai
custom connector, OpenClaw, Hermes ...) struktureret adgang til LLM Wikien.

Transports:
  stdio            (default) — lokal brug fra Claude Code / Claude Desktop
  streamable-http  — fjernadgang fra alle enheder; kræver WIKI_MCP_TOKEN (Bearer)

Env:
  WIKI_ROOT        sti til vaulten (default: mappen over scripts/)
  WIKI_MCP_TOKEN   bearer-token for HTTP-transport (obligatorisk ved http)
  WIKI_MCP_PUSH    "1" → git commit + pull --rebase + push efter hver skrivning
  WIKI_MCP_HOST / WIKI_MCP_PORT   (default 0.0.0.0:8765)

Brug:
  python scripts/wiki-mcp-server.py                       # stdio
  python scripts/wiki-mcp-server.py --transport streamable-http
"""

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP

WIKI = Path(os.environ.get("WIKI_ROOT") or Path(__file__).resolve().parent.parent)
ENTITIES = WIKI / "entities"
FOLDERS = {"person": "people", "project": "projects", "client": "clients", "tool": "tools",
           "place": "places", "concept": "concepts", "recipe": "recipes"}
LOCK = threading.Lock()


# --------------------------------------------------------------------------- index
@dataclass
class Page:
    path: Path
    slug: str
    folder: str
    fm: dict
    body: str
    mtime: float
    links: set = field(default_factory=set)

    @property
    def entity(self) -> str:
        return str(self.fm.get("entity") or self.slug)

    def head(self) -> dict:
        return {
            "slug": self.slug, "type": self.fm.get("type", self.folder), "entity": self.entity,
            "description": self.fm.get("description", ""), "last_updated": str(self.fm.get("last_updated", "")),
            "confidence": self.fm.get("confidence", ""), "tags": self.fm.get("tags") or [],
        }


_INDEX: dict[str, Page] = {}
_INDEX_TIME = 0.0
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


def _parse(path: Path) -> Page | None:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except Exception:
        return None
    raw = raw.replace("\r\n", "\n")
    fm: dict = {}
    body = raw
    m = re.match(r"---\n(.*?)\n---\n", raw, re.S)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except Exception:
            fm = {}
        body = raw[m.end():]
    return Page(path=path, slug=path.stem, folder=path.parent.name, fm=fm if isinstance(fm, dict) else {},
                body=body, mtime=path.stat().st_mtime, links={l.strip().lower() for l in LINK_RE.findall(body)})


def _refresh(force: bool = False) -> None:
    """Re-scan changed files (cheap: 900 files, stat only unless changed)."""
    global _INDEX_TIME
    with LOCK:
        if not force and time.time() - _INDEX_TIME < 2:
            return
        seen = set()
        for path in ENTITIES.glob("*/*.md"):
            seen.add(path.stem)
            cur = _INDEX.get(path.stem)
            st = path.stat().st_mtime
            if cur is None or cur.mtime != st or force:
                p = _parse(path)
                if p:
                    _INDEX[path.stem] = p
        for slug in list(_INDEX):
            if slug not in seen:
                del _INDEX[slug]
        _INDEX_TIME = time.time()


def _resolve(name: str) -> Page | None:
    _refresh()
    key = name.strip().lower().replace(" ", "-")
    if key in _INDEX:
        return _INDEX[key]
    low = name.strip().lower()
    for p in _INDEX.values():
        if p.entity.lower() == low:
            return p
        aliases = p.fm.get("aliases") or []
        if isinstance(aliases, list) and any(str(a).lower() == low for a in aliases):
            return p
    return None


def _snippet(body: str, terms: list[str], width: int = 220) -> str:
    low = body.lower()
    pos = min((low.find(t) for t in terms if low.find(t) >= 0), default=-1)
    if pos < 0:
        text = body.strip()[:width]
    else:
        start = max(0, pos - width // 3)
        text = body[start:start + width]
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- git
def _git(*args: str) -> subprocess.CompletedProcess:
    # stdin=DEVNULL + no terminal prompt: git-hooks (auto-push via ssh) må aldrig
    # arve MCP'ens stdio-transport, ellers hænger serveren.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes"}
    return subprocess.run(["git", *args], cwd=WIKI, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL, env=env, timeout=120)


def _commit(paths: list[Path], message: str) -> str:
    rel = [str(p.relative_to(WIKI)).replace("\\", "/") for p in paths]
    _git("add", "--", *rel)
    r = _git("commit", "-q", "-m", message, "--", *rel)
    status = "committed" if r.returncode == 0 else "nothing to commit"
    if os.environ.get("WIKI_MCP_PUSH") == "1" and r.returncode == 0:
        pull = _git("pull", "--rebase", "-q", "origin", "main")
        if pull.returncode != 0:
            _git("rebase", "--abort")
            return f"{status}; pull --rebase failed (aborted, left local): {pull.stderr.strip()[:200]}"
        push = _git("push", "-q", "origin", "main")
        status += "; pushed" if push.returncode == 0 else f"; push failed: {push.stderr.strip()[:200]}"
    return status


# --------------------------------------------------------------------------- server
mcp = FastMCP(
    "wiki",
    instructions=(
        "Personal LLM wiki (Obsidian vault). Call wiki_search before assuming anything about clients, "
        "people, projects, tools or concepts. Write durable new knowledge back with wiki_append "
        "(existing page) or wiki_create (new entity). Never invent facts; mark uncertainty. "
        "Never store passwords or API keys."
    ),
    host=os.environ.get("WIKI_MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("WIKI_MCP_PORT", "8765")),
)


@mcp.tool()
def wiki_search(query: str, type: str = "", limit: int = 8) -> list[dict]:
    """Fuldtekst-søgning i wikien. Returnerer de bedste sider med slug, type, beskrivelse og et uddrag.
    `type` kan afgrænse til person|project|client|tool|place|concept|recipe."""
    _refresh()
    terms = [t for t in re.split(r"\s+", query.lower().strip()) if t]
    if not terms:
        return []
    scored = []
    for p in _INDEX.values():
        if type and str(p.fm.get("type", p.folder)) != type and p.folder != FOLDERS.get(type, ""):
            continue
        ent = p.entity.lower(); slug = p.slug.lower()
        aliases = " ".join(str(a) for a in (p.fm.get("aliases") or [])).lower()
        desc = str(p.fm.get("description", "")).lower()
        tags = " ".join(str(t) for t in (p.fm.get("tags") or [])).lower()
        body = p.body.lower()
        score = 0.0
        for t in terms:
            if t in ent or t in slug: score += 10
            if t in aliases: score += 8
            if t in desc: score += 4
            if t in tags: score += 3
            c = body.count(t)
            if c: score += min(c, 10) * 0.6
        if all(t in (ent + " " + aliases + " " + desc + " " + body) for t in terms):
            score += 3
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], x[1].slug))
    out = []
    for score, p in scored[: max(1, min(limit, 30))]:
        d = p.head(); d["score"] = round(score, 1); d["snippet"] = _snippet(p.body, terms)
        out.append(d)
    return out


@mcp.tool()
def wiki_get(slug: str, max_chars: int = 12000) -> dict:
    """Hent en hel wiki-side (frontmatter + brødtekst) ud fra slug, entitetsnavn eller alias."""
    p = _resolve(slug)
    if not p:
        hits = wiki_search(slug, limit=5)
        return {"error": f"Ingen side '{slug}'", "suggestions": [h["slug"] for h in hits]}
    body = p.body
    truncated = len(body) > max_chars
    return {**p.head(), "path": str(p.path.relative_to(WIKI)).replace("\\", "/"),
            "sources": p.fm.get("sources") or [], "aliases": p.fm.get("aliases") or [],
            "resource": p.fm.get("resource"), "body": body[:max_chars], "truncated": truncated}


@mcp.tool()
def wiki_related(slug: str) -> dict:
    """Udgående og indgående [[links]] for en side — brug til at følge relationer."""
    p = _resolve(slug)
    if not p:
        return {"error": f"Ingen side '{slug}'"}
    _refresh()
    inbound = sorted(q.slug for q in _INDEX.values() if p.slug.lower() in q.links and q.slug != p.slug)
    outbound = sorted(l for l in p.links if l in _INDEX)
    missing = sorted(l for l in p.links if l not in _INDEX)
    return {"slug": p.slug, "outbound": outbound, "inbound": inbound, "dead_links": missing}


@mcp.tool()
def wiki_recent(days: int = 7, limit: int = 25) -> list[dict]:
    """Sider ændret inden for N dage (efter last_updated i frontmatter). Godt til 'hvad er sket?'."""
    _refresh()
    cutoff = dt.date.today() - dt.timedelta(days=days)
    rows = []
    for p in _INDEX.values():
        lu = p.fm.get("last_updated")
        if isinstance(lu, str):
            try: lu = dt.date.fromisoformat(lu[:10])
            except ValueError: lu = None
        if isinstance(lu, dt.date) and lu >= cutoff:
            rows.append((lu, p))
    rows.sort(key=lambda x: (x[0], x[1].slug), reverse=True)
    return [p.head() for _, p in rows[:limit]]


@mcp.tool()
def wiki_handover() -> str:
    """Seneste opgave-handover (_handovers/latest.md) — læs ved start af en session."""
    f = WIKI / "_handovers" / "latest.md"
    return f.read_text(encoding="utf-8") if f.exists() else "Ingen handover."


@mcp.tool()
def wiki_stats() -> dict:
    """Antal sider pr. type, seneste ændringer og git-status for vaulten."""
    _refresh(force=True)
    counts: dict[str, int] = {}
    for p in _INDEX.values():
        counts[p.folder] = counts.get(p.folder, 0) + 1
    st = _git("status", "--short")
    log = _git("log", "-3", "--format=%h %ad %s", "--date=short")
    return {"pages": len(_INDEX), "by_folder": counts,
            "dirty_files": len([l for l in st.stdout.splitlines() if l.strip()]),
            "last_commits": log.stdout.strip().splitlines()}


@mcp.tool()
def wiki_append(slug: str, text: str, section: str = "", source: str = "") -> dict:
    """Tilføj ny viden til en eksisterende side. `text` er markdown (dansk). `section` er en ##-overskrift
    (oprettes hvis den mangler; tom = sidst på siden). `source` = fil-sti i _sources/ eller 'samtale YYYY-MM-DD'.
    Opdaterer last_updated og committer."""
    p = _resolve(slug)
    if not p:
        return {"error": f"Ingen side '{slug}' — brug wiki_create eller tjek stavning via wiki_search"}
    if re.search(r"(api[_-]?key|password|secret|token)\s*[:=]\s*\S{8,}", text, re.I):
        return {"error": "Afvist: teksten ligner en hemmelighed (password/API-nøgle). Gem den i Bitwarden."}
    raw = p.path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    m = re.match(r"---\n(.*?)\n---\n", raw, re.S)
    if not m:
        return {"error": "Siden mangler frontmatter"}
    fm_txt, body = m.group(1), raw[m.end():]
    today = dt.date.today().isoformat()
    if re.search(r"^last_updated:", fm_txt, re.M):
        fm_txt = re.sub(r"^last_updated:.*$", f"last_updated: {today}", fm_txt, flags=re.M)
    else:
        fm_txt += f"\nlast_updated: {today}"
    block = text.strip()
    if source:
        block += f"\n\n> Kilde: {source}" if not source.startswith("_sources/") else f"\n  [kilde: {source}]"
        if source.startswith("_sources/") and re.search(r"^sources:\s*\[\]\s*$", fm_txt, re.M):
            fm_txt = re.sub(r"^sources:\s*\[\]\s*$", f"sources:\n  - {source}", fm_txt, flags=re.M)
        elif source.startswith("_sources/") and f"- {source}" not in fm_txt and re.search(r"^sources:\s*$", fm_txt, re.M):
            fm_txt = re.sub(r"^sources:\s*$", f"sources:\n  - {source}", fm_txt, flags=re.M)
    if section:
        header = f"## {section.strip().lstrip('#').strip()}"
        idx = body.find(header + "\n")
        if idx >= 0:
            nxt = re.search(r"\n## ", body[idx + len(header):])
            end = idx + len(header) + (nxt.start() if nxt else len(body[idx + len(header):]))
            body = body[:end].rstrip("\n") + "\n\n" + block + "\n" + body[end:]
        else:
            body = body.rstrip("\n") + f"\n\n{header}\n\n{block}\n"
    else:
        body = body.rstrip("\n") + "\n\n" + block + "\n"
    p.path.write_text("---\n" + fm_txt + "\n---\n" + body, encoding="utf-8", newline="\n")
    git = _commit([p.path], f"wiki: append {p.slug}")
    _refresh(force=True)
    return {"ok": True, "slug": p.slug, "git": git}


@mcp.tool()
def wiki_create(type: str, slug: str, entity: str, description: str, body: str,
                tags: list[str] | None = None, aliases: list[str] | None = None,
                source: str = "", confidence: str = "medium", resource: str = "") -> dict:
    """Opret en ny wiki-side. `type` ∈ person|project|client|tool|place|concept|recipe. `slug` = kebab-case
    filnavn uden .md. `description` = én sætning (≤180 tegn) om hvad entiteten ER. `body` = markdown der
    starter med '# Titel'. Tjek FØRST med wiki_search at entiteten ikke findes."""
    if type not in FOLDERS:
        return {"error": f"Ugyldig type '{type}'"}
    slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")
    if not slug:
        return {"error": "Tom slug"}
    _refresh()
    if slug in _INDEX:
        return {"error": f"'{slug}' findes allerede i {_INDEX[slug].folder}/ — brug wiki_append"}
    if len(description) > 220 or '"' in description or "\\" in description:
        return {"error": "description skal være ≤220 tegn uden anførselstegn/backslash"}
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"
    today = dt.date.today().isoformat()
    fm = [f'entity: "{entity}"', f"type: {type}", f'description: "{description}"',
          f"aliases: [{', '.join(aliases or [])}]"]
    fm.append(f"sources:\n  - {source}" if source.startswith("_sources/") else "sources: []")
    fm += [f"confidence: {confidence}", f"created: {today}", f"last_updated: {today}",
           f"tags: [{', '.join(tags or [])}]"]
    if resource:
        fm.append(f"resource: {resource}")
    text = body.strip()
    if not text.startswith("# "):
        text = f"# {entity}\n\n{text}"
    if source and not source.startswith("_sources/"):
        text += f"\n\n> Kilde: {source}"
    path = ENTITIES / FOLDERS[type] / f"{slug}.md"
    path.write_text("---\n" + "\n".join(fm) + "\n---\n\n" + text + "\n", encoding="utf-8", newline="\n")
    git = _commit([path], f"wiki: opret {slug}")
    _refresh(force=True)
    return {"ok": True, "slug": slug, "path": str(path.relative_to(WIKI)).replace("\\", "/"), "git": git}


@mcp.resource("wiki://schema")
def schema() -> str:
    """Wikiens regler og konventioner (_schema.md)."""
    return (WIKI / "_schema.md").read_text(encoding="utf-8")


@mcp.resource("wiki://index")
def index() -> str:
    """Indholdsfortegnelse (_index.md)."""
    return (WIKI / "_index.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- http auth
def _http_app():
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    token = os.environ.get("WIKI_MCP_TOKEN")
    if not token or len(token) < 24:
        sys.exit("WIKI_MCP_TOKEN (≥24 tegn) er påkrævet for streamable-http")

    from starlette.responses import HTMLResponse, PlainTextResponse

    landing = WIKI / "deploy" / "wiki-mcp" / "landing.html"

    class Auth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path
            if path.startswith("/health"):
                _refresh()
                return JSONResponse({"ok": True, "pages": len(_INDEX)})
            if request.method == "GET" and path in ("/", "/index.html"):
                if landing.exists():
                    return HTMLResponse(landing.read_text(encoding="utf-8"))
                return PlainTextResponse("wiki-mcp: MCP endpoint at /mcp (Bearer token required)")
            if request.method == "GET" and path in ("/favicon.ico", "/robots.txt"):
                return PlainTextResponse("User-agent: *\nDisallow: /mcp\n" if path == "/robots.txt" else "", status_code=200 if path == "/robots.txt" else 404)
            auth = request.headers.get("authorization", "")
            if auth != f"Bearer {token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app = mcp.streamable_http_app()
    app.add_middleware(Auth)
    return app


def _pull_loop(interval: int) -> None:
    while True:
        time.sleep(interval)
        with LOCK:
            if _git("status", "--short").stdout.strip():
                continue
        r = _git("pull", "--rebase", "-q", "origin", "main")
        if r.returncode != 0:
            _git("rebase", "--abort")
        _refresh(force=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    ap.add_argument("--pull-interval", type=int, default=0, help="sekunder mellem git pull (0 = aldrig)")
    args = ap.parse_args()
    _refresh(force=True)
    if args.pull_interval > 0:
        threading.Thread(target=_pull_loop, args=(args.pull_interval,), daemon=True).start()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn
        uvicorn.run(_http_app(), host=mcp.settings.host, port=mcp.settings.port, log_level="info")
