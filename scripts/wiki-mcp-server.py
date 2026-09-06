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
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

RO = ToolAnnotations(readOnlyHint=True, idempotentHint=True)

def _load_conflicts():
    spec = importlib.util.spec_from_file_location("wiki_conflicts", Path(__file__).resolve().parent / "wiki_conflicts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

try:
    _CONFLICTS = _load_conflicts()
except Exception:
    _CONFLICTS = None
RW = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)

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

    @property
    def is_redirect(self) -> bool:
        return str(self.fm.get("type", "")) == "redirect"

    def head(self) -> dict:
        return {
            "slug": self.slug, "type": self.fm.get("type", self.folder), "entity": self.entity,
            "description": self.fm.get("description", ""), "last_updated": str(self.fm.get("last_updated", "")),
            "confidence": self.fm.get("confidence", ""), "tags": self.fm.get("tags") or [],
            "path": str(self.path.relative_to(WIKI)).replace("\\", "/"), "stale": _is_stale(self),
        }


_INDEX: dict[str, Page] = {}
_INDEX_TIME = 0.0
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
STALE_DEFAULT_DAYS = {"client": 180, "project": 60, "person": 365, "place": 365, "recipe": 365}
ARCHIVED_STATUS = {"archived", "arkiveret", "afsluttet", "done", "completed", "inaktiv", "inactive", "lukket", "closed", "parkeret", "paused", "tidligere-kunde", "tabt", "lost"}
STOPWORDS = {"og", "i", "på", "af", "til", "en", "et", "de", "det", "den", "der", "som", "med", "for", "fra", "er", "har", "om", "hvem", "hvad", "hvor", "the", "and", "for", "med", "ved", "kan", "skal", "vi", "jeg", "min", "mit", "sin"}
_FTS: sqlite3.Connection | None = None
_FTS_DIRTY = True


def _to_date(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v):
        try:
            return dt.date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def _is_stale(p: "Page") -> bool:
    """stale_after i frontmatter, ellers type-default; tool/concept forældes ikke."""
    if str(p.fm.get("status", "")).lower() in ARCHIVED_STATUS:
        return False
    limit = _to_date(p.fm.get("stale_after"))
    if limit is None:
        lu = _to_date(p.fm.get("last_updated"))
        days = STALE_DEFAULT_DAYS.get(str(p.fm.get("type", p.folder)))
        if lu is None or days is None:
            return False
        limit = lu + dt.timedelta(days=days)
    return dt.date.today() > limit


def _fts_rebuild() -> None:
    """SQLite FTS5 (BM25) over entity/aliases/description/tags/body — i hukommelsen, genbygges ved ændringer."""
    global _FTS, _FTS_DIRTY
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE fts USING fts5(slug UNINDEXED, entity, aliases, description, tags, body, tokenize='unicode61 remove_diacritics 0')")
    con.executemany("INSERT INTO fts VALUES (?,?,?,?,?,?)", [
        (p.slug, p.entity, " ".join(str(a) for a in (p.fm.get("aliases") or [])), str(p.fm.get("description", "")),
         " ".join(str(t) for t in (p.fm.get("tags") or [])), p.body) for p in _INDEX.values() if not p.is_redirect])
    con.commit()
    _FTS, _FTS_DIRTY = con, False


def _bm25(terms: list[str], limit: int = 50) -> list[str]:
    """Slugs rangeret efter BM25 med feltvægte entity 6 / aliases 5 / description 4 / tags 2 / body 1."""
    if _FTS is None or _FTS_DIRTY:
        _fts_rebuild()
    q = " OR ".join('"' + t.replace('"', "") + '"*' for t in terms if t)
    try:
        rows = _FTS.execute("SELECT slug FROM fts WHERE fts MATCH ? ORDER BY bm25(fts, 0, 6.0, 5.0, 4.0, 2.0, 1.0) LIMIT ?", (q, limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]


# --------------------------------------------------------------------------- semantic lane (valgfri)
_EMB_MODEL = None
_EMB_MAT = None          # numpy-matrix (n, dim), normaliseret
_EMB_KEYS: list[tuple[str, int]] = []   # (slug, chunk_idx) pr. række
_EMB_DIRTY = True
_EMB_DISABLED = os.environ.get("WIKI_EMBED", "1") == "0"
EMBED_MODEL_NAME = os.environ.get("WIKI_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
EMB_DB = WIKI / "_index" / "embeddings.sqlite"


def _emb_model():
    global _EMB_MODEL, _EMB_DISABLED
    if _EMB_DISABLED:
        return None
    if _EMB_MODEL is None:
        try:
            from fastembed import TextEmbedding
            _EMB_MODEL = TextEmbedding(EMBED_MODEL_NAME)
        except Exception as e:  # fastembed mangler eller model kan ikke hentes → to lanes
            print(f"wiki-mcp: semantisk lane slået fra ({e.__class__.__name__}: {str(e)[:80]})", file=sys.stderr, flush=True)
            _EMB_DISABLED = True
            return None
    return _EMB_MODEL


def _chunks(p: "Page") -> list[str]:
    head = f"{p.entity}. {p.fm.get('description', '')}"
    body = p.body
    if len(body) <= 4000:
        return [f"{head}\n{body[:1500]}"]
    out = [f"{head}\n{body[:1200]}"]
    for h, t in _sections(body):
        if h and t:
            out.append(f"{p.entity} — {h}\n{t[:1200]}")
    return out[:12]


def _emb_refresh() -> None:
    """Inkrementel: kun sider med ændret hash re-embeddes. Indeks i _index/embeddings.sqlite (gitignored)."""
    global _EMB_MAT, _EMB_KEYS, _EMB_DIRTY
    import numpy as np
    model = _emb_model()
    if model is None:
        return
    EMB_DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(EMB_DB)
    con.execute("CREATE TABLE IF NOT EXISTS emb (slug TEXT, idx INTEGER, hash TEXT, vec BLOB, PRIMARY KEY (slug, idx))")
    con.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    if (con.execute("SELECT v FROM meta WHERE k='model'").fetchone() or [None])[0] != EMBED_MODEL_NAME:
        con.execute("DELETE FROM emb"); con.execute("INSERT OR REPLACE INTO meta VALUES ('model', ?)", (EMBED_MODEL_NAME,))
    have = {(r[0], r[1]): r[2] for r in con.execute("SELECT slug, idx, hash FROM emb")}
    todo: list[tuple[str, int, str, str]] = []
    live = set()
    for p in _INDEX.values():
        if p.is_redirect:
            continue
        for i, text in enumerate(_chunks(p)):
            h = hashlib.sha1(text.encode("utf-8")).hexdigest()
            live.add((p.slug, i))
            if have.get((p.slug, i)) != h:
                todo.append((p.slug, i, h, text))
    for key in set(have) - live:
        con.execute("DELETE FROM emb WHERE slug=? AND idx=?", key)
    if todo:
        vecs = list(model.embed([t for _, _, _, t in todo], batch_size=64))
        con.executemany("INSERT OR REPLACE INTO emb VALUES (?,?,?,?)",
                        [(sl, i, h, np.asarray(v, dtype=np.float32).tobytes()) for (sl, i, h, _), v in zip(todo, vecs)])
    con.commit()
    rows = con.execute("SELECT slug, idx, vec FROM emb").fetchall()
    con.close()
    if not rows:
        _EMB_MAT, _EMB_KEYS = None, []
    else:
        mat = np.vstack([np.frombuffer(r[2], dtype=np.float32) for r in rows])
        norms = np.linalg.norm(mat, axis=1, keepdims=True); norms[norms == 0] = 1
        _EMB_MAT, _EMB_KEYS = mat / norms, [(r[0], r[1]) for r in rows]
    _EMB_DIRTY = False


def _semantic(query: str, limit: int = 40) -> list[tuple[str, float]]:
    """[(slug, cosine)] rangeret — bedste chunk pr. side."""
    import numpy as np
    model = _emb_model()
    if model is None:
        return []
    if _EMB_DIRTY or _EMB_MAT is None:
        _emb_refresh()
    if _EMB_MAT is None:
        return []
    q = np.asarray(next(iter(model.embed([query]))), dtype=np.float32)
    q = q / (np.linalg.norm(q) or 1)
    sims = _EMB_MAT @ q
    best: dict[str, float] = {}
    for (slug, _), sim in zip(_EMB_KEYS, sims):
        if sim > best.get(slug, -1):
            best[slug] = float(sim)
    return sorted(best.items(), key=lambda x: -x[1])[:limit]


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
    global _INDEX_TIME, _FTS_DIRTY, _EMB_DIRTY
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
                    _FTS_DIRTY = True
                    _EMB_DIRTY = True
        for slug in list(_INDEX):
            if slug not in seen:
                del _INDEX[slug]
                _FTS_DIRTY = True
                _EMB_DIRTY = True
        _INDEX_TIME = time.time()


def _follow(p: "Page | None", hops: int = 0) -> "Page | None":
    """Følg redirect-stubs (type: redirect, redirect_to: slug), maks 3 hop."""
    if p is None or not p.is_redirect or hops > 3:
        return p
    target = str(p.fm.get("redirect_to", "")).strip().lower()
    return _follow(_INDEX.get(target), hops + 1) if target in _INDEX else p


def _resolve(name: str) -> Page | None:
    _refresh()
    key = name.strip().lower().replace(" ", "-")
    if key in _INDEX:
        return _follow(_INDEX[key])
    low = name.strip().lower()
    for p in _INDEX.values():
        if p.entity.lower() == low:
            return _follow(p)
        aliases = p.fm.get("aliases") or []
        if isinstance(aliases, list) and any(str(a).lower() == low for a in aliases):
            return _follow(p)
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
        "(existing page) or wiki_create (new entity). Work layered: wiki_search (compact) -> wiki_outline -> "
        "wiki_get(section=...). Cite as path#heading. Never invent facts; mark uncertainty. "
        "Never store passwords or API keys."
    ),
    host=os.environ.get("WIKI_MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("WIKI_MCP_PORT", "8765")),
)


@mcp.tool(annotations=RO)
def wiki_search(query: str, type: str = "", limit: int = 8, mode: str = "rrf") -> list[dict]:
    """Søg i wikien. Returnerer kompakte hits (slug, type, entity, description, last_updated, path, score, snippet,
    stale) — hent detaljer med wiki_outline/wiki_get. `type` afgrænser til person|project|client|tool|place|concept|recipe.
    Ranking: BM25 (SQLite FTS5) + feltvægtet term-match fusioneret med Reciprocal Rank Fusion; forældede sider nedvægtes.
    `mode` = rrf (default, tre lanes inkl. semantisk hvis embeddings findes) | bm25 | weighted | semantic (til evaluering)."""
    _refresh()
    raw_terms = [t for t in re.split(r"\s+", query.lower().strip()) if t]
    # Stopord/korte ord (i, og, på, af, en …) drukner signalet i term-match — behold dem kun hvis intet andet er tilbage.
    terms = [t for t in raw_terms if len(t) > 2 and t not in STOPWORDS] or raw_terms
    if not terms:
        return []

    def allowed(p: Page) -> bool:
        if p.is_redirect:
            return False
        return not type or str(p.fm.get("type", p.folder)) == type or p.folder == FOLDERS.get(type, "")

    weighted: list[tuple[float, Page]] = []
    for p in _INDEX.values():
        if not allowed(p):
            continue
        ent = p.entity.lower(); slug = p.slug.lower(); slug_joined = slug.replace("-", "")
        aliases = " ".join(str(a) for a in (p.fm.get("aliases") or [])).lower()
        desc = str(p.fm.get("description", "")).lower()
        tags = " ".join(str(t) for t in (p.fm.get("tags") or [])).lower()
        body = p.body.lower()
        score = 0.0
        for t in terms:
            if t in ent or t in slug or (len(t) > 6 and t in slug_joined): score += 10  # sammensatte ord: tilbudsskabelon ~ tilbuds-skabelon
            if t in aliases: score += 8
            if t in desc: score += 4
            if t in tags: score += 3
            c = body.count(t)
            if c: score += min(c, 10) * 0.6
        if all(t in (ent + " " + aliases + " " + desc + " " + body) for t in terms):
            score += 3
        if score > 0:
            weighted.append((score, p))
    weighted.sort(key=lambda x: (-x[0], x[1].slug))
    w_rank = {p.slug: i for i, (_, p) in enumerate(weighted)}
    b_rank = {sl: i for i, sl in enumerate(sl for sl in _bm25(terms, 60) if sl in _INDEX and allowed(_INDEX[sl]))}

    s_rank: dict[str, int] = {}
    if mode in ("rrf", "semantic"):
        s_rank = {sl: i for i, (sl, sim) in enumerate((sl, sim) for sl, sim in _semantic(query, 60)
                                                          if sim >= 0.35 and sl in _INDEX and allowed(_INDEX[sl]))}
    if mode == "weighted":
        fused = {sl: 1.0 / (60 + r) for sl, r in w_rank.items()}
    elif mode == "bm25":
        fused = {sl: 1.0 / (60 + r) for sl, r in b_rank.items()}
    elif mode == "semantic":
        fused = {sl: 1.0 / (60 + r) for sl, r in s_rank.items()}
    else:
        # RRF k=60; den semantiske lane vægtes 0,6 — den er stærk på omskrivninger men svag på egennavne.
        fused = {}
        for lane, weight in ((w_rank, 1.0), (b_rank, 1.0), (s_rank, 0.6)):
            for sl, r in lane.items():
                fused[sl] = fused.get(sl, 0.0) + weight / (60 + r)
    scored = []
    for sl, sc in fused.items():
        p = _INDEX[sl]
        if _is_stale(p):
            sc *= 0.7
        scored.append((sc, p))
    scored.sort(key=lambda x: (-x[0], x[1].slug))
    out = []
    for sc, p in scored[: max(1, min(limit, 30))]:
        d = p.head(); d["score"] = round(sc * 1000, 2); d["snippet"] = _snippet(p.body, terms, 160)
        out.append(d)
    return out


def _sections(body: str) -> list[tuple[str, str]]:
    """[(heading, text)] — første element er teksten før første ##-overskrift (heading '')."""
    parts = re.split(r"\n(?=## )", "\n" + body)
    out = []
    for part in parts:
        part = part.strip("\n")
        if not part:
            continue
        if part.startswith("## "):
            h, _, rest = part.partition("\n")
            out.append((h[3:].strip(), rest.strip()))
        else:
            out.append(("", part.strip()))
    return out


@mcp.tool(annotations=RO)
def wiki_outline(slug: str) -> dict:
    """Billig oversigt over en side: frontmatter-hoved + hver ##-sektion med første linje og længde.
    Brug den før wiki_get for kun at hente den sektion du har brug for."""
    p = _resolve(slug)
    if not p:
        return {"error": f"Ingen side '{slug}'", "suggestions": [h["slug"] for h in wiki_search(slug, limit=5)]}
    secs = []
    for h, text in _sections(p.body):
        first = re.sub(r"\s+", " ", text.split("\n")[0])[:140] if text else ""
        secs.append({"heading": h or "(intro)", "chars": len(text), "first_line": first})
    return {**p.head(), "sources": p.fm.get("sources") or [], "sections": secs}


@mcp.tool(annotations=RO)
def wiki_get(slug: str, section: str = "", max_chars: int = 12000) -> dict:
    """Hent en side (eller kun én ##-sektion via `section`) ud fra slug, entitetsnavn eller alias.
    Citér som `path#heading` når du bruger indholdet."""
    p = _resolve(slug)
    if not p:
        hits = wiki_search(slug, limit=5)
        return {"error": f"Ingen side '{slug}'", "suggestions": [h["slug"] for h in hits]}
    body = p.body
    if section:
        want = section.strip().lstrip("#").strip().lower()
        match = [(h, t) for h, t in _sections(body) if h.lower() == want or want in h.lower()]
        if not match:
            return {"error": f"Ingen sektion '{section}'", "sections": [h for h, _ in _sections(body) if h]}
        body = f"## {match[0][0]}\n\n{match[0][1]}"
    truncated = len(body) > max_chars
    return {**p.head(), "sources": p.fm.get("sources") or [], "aliases": p.fm.get("aliases") or [],
            "resource": p.fm.get("resource"), "body": body[:max_chars], "truncated": truncated}


@mcp.tool(annotations=RO)
def wiki_related(slug: str) -> dict:
    """Udgående og indgående [[links]] for en side — brug til at følge relationer."""
    p = _resolve(slug)
    if not p:
        return {"error": f"Ingen side '{slug}'"}
    _refresh()
    inbound = sorted(q.slug for q in _INDEX.values() if p.slug.lower() in q.links and q.slug != p.slug)
    outbound = sorted(l for l in p.links if l in _INDEX)
    missing = sorted(l for l in p.links if l not in _INDEX)
    semantic = [sl for sl, sim in _semantic(f"{p.entity}. {p.fm.get('description', '')}", 12) if sl != p.slug and sim >= 0.35][:6]
    return {"slug": p.slug, "outbound": outbound, "inbound": inbound, "dead_links": missing, "semantic": semantic}


@mcp.tool(annotations=RO)
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


@mcp.tool(annotations=RO)
def wiki_handover() -> str:
    """Seneste opgave-handover (_handovers/latest.md) — læs ved start af en session."""
    f = WIKI / "_handovers" / "latest.md"
    return f.read_text(encoding="utf-8") if f.exists() else "Ingen handover."


@mcp.tool(annotations=RO)
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


@mcp.tool(annotations=RW)
def wiki_append(slug: str, text: str, section: str = "", source: str = "") -> dict:
    """Tilføj ny viden til en eksisterende side. `text` er markdown (dansk). `section` er en ##-overskrift
    (oprettes hvis den mangler; tom = sidst på siden). `source` = fil-sti i _sources/ eller 'samtale YYYY-MM-DD'.
    Opdaterer last_updated og committer. Deterministiske modsigelser (e-mail, telefon, beløb, version, kontaktperson,
    hosting) mod eksisterende tekst tilføjes som callout, logges i _review-queue.md og returneres som `contradictions`."""
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
    contradictions = []
    if _CONFLICTS is not None:
        try:
            compare_to = body
            if section:
                sec = [t for h, t in _sections(body) if h.lower() == section.strip().lstrip('#').strip().lower()]
                compare_to = sec[0] if sec else body
            contradictions = _CONFLICTS.find_conflicts(compare_to, text)
        except Exception:
            contradictions = []
    if contradictions:
        lines = "; ".join(f"{c['key']}: ny kilde siger \"{c['new']}\", siden sagde \"{c['old']}\"" for c in contradictions)
        block += f"\n\n> [!warning] Modsigelse ({today}): {lines}"
        rq = WIKI / "_review-queue.md"
        rq_text = rq.read_text(encoding="utf-8") if rq.exists() else "# Review-kø\n"
        if "## Modsigelser" not in rq_text:
            rq_text = rq_text.rstrip("\n") + "\n\n## Modsigelser\n"
        rq_text = rq_text.rstrip("\n") + f"\n- [ ] [[{p.slug}]] {today}: {lines}" + (f" (kilde: {source})" if source else "") + "\n"
        rq.write_text(rq_text, encoding="utf-8", newline="\n")
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
    paths = [p.path] + ([WIKI / "_review-queue.md"] if contradictions else [])
    git = _commit(paths, f"wiki: append {p.slug}")
    _refresh(force=True)
    return {"ok": True, "slug": p.slug, "git": git, "contradictions": contradictions}


@mcp.tool(annotations=RW)
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
    """Pull main periodisk. Hvis selve server-scriptet ændrer sig (ny version pushet), genstart processen,
    så deploy = git push uden redeploy af containeren."""
    me = Path(__file__).resolve()
    my_mtime = me.stat().st_mtime
    while True:
        time.sleep(interval)
        with LOCK:
            if _git("status", "--short").stdout.strip():
                continue
        r = _git("pull", "--rebase", "-q", "origin", "main")
        if r.returncode != 0:
            _git("rebase", "--abort")
        _refresh(force=True)
        if me.stat().st_mtime != my_mtime:
            print("wiki-mcp: server-scriptet er opdateret via git — genstarter", file=sys.stderr, flush=True)
            os.execv(sys.executable, [sys.executable, *sys.argv])


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
