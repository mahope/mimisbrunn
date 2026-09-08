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
import functools
import anyio
import hashlib
import hmac
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
try:  # libyaml er ~8x hurtigere: 435 ms -> 55 ms for 900 sider (issue #19)
    from yaml import CSafeLoader as _YamlLoader
except ImportError:  # pragma: no cover
    from yaml import SafeLoader as _YamlLoader
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

def _threaded(fn):
    """Kør et synkront tool paa anyio's traadpool.

    Alle tools var synkrone og kørte direkte paa event-loopet: ét langsomt kald
    (kold modelload, git, fuld FTS-genopbygning) blokerede alle andre sessioner
    imens (issue #23). De synkrone funktioner beholder deres navne, saa
    wiki-cli.py og retrieval-eval.py kan kalde dem uden en event-loop.
    """
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))
    return wrapper

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
           "place": "places", "concept": "concepts", "recipe": "recipes", "answer": "answers"}
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
    # Forudberegnet i _parse: uden dem lowercaser hver soegning 3,4 MB tekst paa ny (issue #20).
    low_ent: str = ""
    low_slug: str = ""
    low_slug_joined: str = ""
    low_alias: str = ""
    low_desc: str = ""
    low_tags: str = ""
    low_body: str = ""
    # Staleness afhaenger kun af frontmatter og dagens dato, men blev regnet ~500 gange
    # pr. soegning. Cachen nulstilles af sig selv naar datoen skifter, og en aendret fil
    # giver et nyt Page-objekt, saa den kan ikke blive forladt.
    _stale: bool = False
    _stale_on: object = None

    @property
    def entity(self) -> str:
        return str(self.fm.get("entity") or self.slug)

    @property
    def is_redirect(self) -> bool:
        return str(self.fm.get("type", "")) == "redirect"

    @property
    def is_generated(self) -> bool:
        """Hub-sider m.fl.: de matcher mange termer, men er aldrig svaret (issue #27)."""
        return bool(self.fm.get("generated"))

    def head(self) -> dict:
        return {
            "slug": self.slug, "type": self.fm.get("type", self.folder), "entity": self.entity,
            "description": self.fm.get("description", ""), "last_updated": str(self.fm.get("last_updated", "")),
            "confidence": self.fm.get("confidence", ""), "tags": self.fm.get("tags") or [],
            "path": str(self.path.relative_to(WIKI)).replace("\\", "/"), "stale": _is_stale(self),
        }


_INDEX: dict[str, Page] = {}
_ALIAS: dict[str, str] = {}   # entity/alias (lowercase) -> slug
_INDEX_TIME = 0.0
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
STALE_DEFAULT_DAYS = {"client": 180, "project": 60, "person": 365, "place": 365, "recipe": 365}
ARCHIVED_STATUS = {"archived", "arkiveret", "afsluttet", "done", "completed", "inaktiv", "inactive", "lukket", "closed", "parkeret", "paused", "tidligere-kunde", "tabt", "lost"}
STOPWORDS = {"og", "i", "på", "af", "til", "en", "et", "de", "det", "den", "der", "som", "med", "for", "fra", "er", "har", "om", "hvem", "hvad", "hvor", "the", "and", "for", "med", "ved", "kan", "skal", "vi", "jeg", "min", "mit", "sin"}
_FTS: sqlite3.Connection | None = None
_FTS_DIRTY = True
_FTS_LOCK = threading.Lock()   # sqlite-forbindelser er ikke traadsikre (issue #23)
_FTS_CHANGED: set[str] = set()   # slugs der skal genindsaettes (issue #25)
_FTS_DELETED: set[str] = set()   # slugs der skal fjernes


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
    today = dt.date.today()
    if p._stale_on == today:
        return p._stale
    p._stale, p._stale_on = _is_stale_uncached(p), today
    return p._stale


def _is_stale_uncached(p: "Page") -> bool:
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
    # check_same_thread=False: forbindelsen bruges fra traadpoolen, ikke kun fra
    # den traad der byggede den. Alle kald serialiseres af _FTS_LOCK (issue #23).
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.execute("CREATE VIRTUAL TABLE fts USING fts5(slug UNINDEXED, entity, aliases, description, tags, body, tokenize='unicode61 remove_diacritics 0')")
    con.executemany("INSERT INTO fts VALUES (?,?,?,?,?,?)", [
        (p.slug, p.entity, " ".join(str(a) for a in (p.fm.get("aliases") or [])), str(p.fm.get("description", "")),
         " ".join(str(t) for t in (p.fm.get("tags") or [])), p.body) for p in _INDEX.values() if not p.is_redirect])
    # Sektionsniveau: en kort sektion i en meget lang side taber ellers altid paa
    # BM25's laengdenormalisering, selv om det er praecis der svaret staar.
    con.execute("CREATE VIRTUAL TABLE fts_sec USING fts5(slug UNINDEXED, heading, body, "
                "tokenize='unicode61 remove_diacritics 0')")
    rows = []
    for p in _INDEX.values():
        if p.is_redirect or p.is_generated:
            continue
        for head, text in _indexable_sections(p):
            rows.append((p.slug, f"{p.entity} {head}", text))
    con.executemany("INSERT INTO fts_sec VALUES (?,?,?)", rows)
    con.commit()
    _FTS, _FTS_DIRTY = con, False


# Rene navigationssektioner er linklister. De matcher mange termer, fordi de naevner
# mange entiteter, men de indeholder aldrig svaret — samme grund til at genererede
# hub-sider holdes ude af sideindekset. "Relationer" hoerer IKKE med her: typede
# relationer (- hoster-hos:: [[hetzner]]) er fakta.
NAV_SECTIONS = {"se også", "se ogsaa", "see also"}


def _indexable_sections(p: "Page"):
    for head, text in _sections(p.body):
        if head.strip().lower() in NAV_SECTIONS:
            continue
        if len(text.strip()) > 30:
            yield head, text


def _fts_rows(p: "Page"):
    """(side-raekke, sektions-raekker) for én side."""
    page_row = (p.slug, p.entity, " ".join(str(a) for a in (p.fm.get("aliases") or [])),
                str(p.fm.get("description", "")), " ".join(str(t) for t in (p.fm.get("tags") or [])), p.body)
    sec_rows = []
    if not p.is_generated:
        for head, text in _indexable_sections(p):
            sec_rows.append((p.slug, f"{p.entity} {head}", text))
    return page_row, sec_rows


def _fts_sync() -> None:
    """Opdatér kun de sider der har aendret sig.

    En fuld genopbygning koster 317 ms for 904 sider og 5.022 sektioner, og den blev
    udloest ved hver eneste aendring. Inkrementelt er det ~1 ms pr. side (issue #25).
    Kaldes under _FTS_LOCK."""
    global _FTS_DIRTY
    if _FTS is None:
        _fts_rebuild()
        _FTS_CHANGED.clear(); _FTS_DELETED.clear()
        return
    if not (_FTS_CHANGED or _FTS_DELETED):
        _FTS_DIRTY = False
        return
    touched = (_FTS_CHANGED | _FTS_DELETED)
    for slug in touched:
        _FTS.execute("DELETE FROM fts WHERE slug = ?", (slug,))
        _FTS.execute("DELETE FROM fts_sec WHERE slug = ?", (slug,))
    for slug in _FTS_CHANGED:
        p = _INDEX.get(slug)
        if p is None or p.is_redirect:
            continue
        page_row, sec_rows = _fts_rows(p)
        _FTS.execute("INSERT INTO fts VALUES (?,?,?,?,?,?)", page_row)
        if sec_rows:
            _FTS.executemany("INSERT INTO fts_sec VALUES (?,?,?)", sec_rows)
    _FTS.commit()
    _FTS_CHANGED.clear(); _FTS_DELETED.clear()
    _FTS_DIRTY = False


def _bm25_sections(terms: list[str], limit: int = 40) -> list[tuple[str, str]]:
    """[(slug, overskrift)] rangeret paa sektionsniveau, bedste sektion pr. side beholdes."""
    q = " OR ".join('"' + t.replace('"', "") + '"*' for t in terms if t)
    out: list[tuple[str, str]] = []
    seen = set()
    with _FTS_LOCK:
        if _FTS is None or _FTS_DIRTY:
            _fts_sync()
        try:
            rows = _FTS.execute(
                "SELECT slug, heading FROM fts_sec WHERE fts_sec MATCH ? "
                "ORDER BY bm25(fts_sec, 0, 3.0, 1.0) LIMIT ?", (q, limit * 3)).fetchall()
        except sqlite3.OperationalError:
            return []
    for slug, heading in rows:
        if slug in seen:
            continue
        seen.add(slug)
        out.append((slug, heading))
        if len(out) >= limit:
            break
    return out


def _best_sections_for(slugs: list[str], terms: list[str]) -> dict[str, str]:
    """Bedste sektion pr. side for en haandfuld bestemte sider, i ét opslag.

    Sektionsbanen er en global top-N, saa en side der vinder paa de andre baner kan ende
    uden sektion — og saa maa modellen gaette hvor i en 63.000 tegn lang side svaret staar.
    Her spoerges der maalrettet, kun for de faa sider der faktisk returneres, og med én
    forespoergsel i stedet for én pr. side (otte runde ture kostede ca. 6 ms p50).

    Intro-sektionen er gemt med tom overskrift og springes over: den er ubrugelig som
    pejlemaerke, for den staar allerede oeverst paa siden."""
    q = " OR ".join('"' + t.replace('"', "") + '"*' for t in terms if t)
    if not q or not slugs:
        return {}
    huller = ",".join("?" * len(slugs))
    with _FTS_LOCK:
        if _FTS is None or _FTS_DIRTY:
            _fts_sync()
        try:
            rows = _FTS.execute(
                f"SELECT slug, heading FROM fts_sec WHERE fts_sec MATCH ? AND slug IN ({huller}) "
                "ORDER BY bm25(fts_sec, 0, 3.0, 1.0)", (q, *slugs)).fetchall()
        except sqlite3.OperationalError:
            return {}
    ud = {}
    for slug, heading in rows:
        if slug in ud:
            continue
        ent = _INDEX[slug].entity if slug in _INDEX else ""
        vis = heading[len(ent):].strip() if heading.startswith(ent) else heading.strip()
        if vis:
            ud[slug] = heading
    return ud


def _bm25(terms: list[str], limit: int = 50) -> list[str]:
    """Slugs rangeret efter BM25 med feltvægte entity 6 / aliases 5 / description 4 / tags 2 / body 1."""
    q = " OR ".join('"' + t.replace('"', "") + '"*' for t in terms if t)
    with _FTS_LOCK:
        if _FTS is None or _FTS_DIRTY:
            _fts_sync()
        con = _FTS
        try:
            rows = con.execute("SELECT slug FROM fts WHERE fts MATCH ? ORDER BY bm25(fts, 0, 6.0, 5.0, 4.0, 2.0, 1.0) LIMIT ?", (q, limit)).fetchall()
        except sqlite3.OperationalError:
            return []
    return [r[0] for r in rows]


# --------------------------------------------------------------------------- semantic lane (valgfri)
_EMB_MODEL = None
_EMB_MAT = None          # numpy-matrix (n, dim), normaliseret
_EMB_KEYS: list[tuple[str, int]] = []   # (slug, chunk_idx) pr. række
_EMB_SNAPSHOT: tuple | None = None      # (mat, keys) laest som ét hele af _semantic (issue #23)
_EMB_DIRTY = True
_EMB_LOCK = threading.Lock()
_EMB_BUILDING = False
_EMB_DISABLED = os.environ.get("WIKI_EMBED", "1") == "0"
EMBED_MODEL_NAME = os.environ.get("WIKI_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
EMB_DB = WIKI / "_index" / "embeddings.sqlite"
# Batch og traade holdes lave: en kold build med batch_size=64 toppede paa 1,16 GB RSS
# paa en 4 GB VPS med 2 vCPU (issue #21).
EMBED_BATCH = int(os.environ.get("WIKI_EMBED_BATCH", "8"))
EMBED_THREADS = int(os.environ.get("WIKI_EMBED_THREADS", "1"))


_EMB_MODEL_LOCK = threading.Lock()


def _emb_model():
    """Single-flight load af ONNX-modellen: uden laasen kan opstartstraaden og et
    tidligt request hver loade sin egen session og fordoble RSS (issue #21)."""
    global _EMB_MODEL, _EMB_DISABLED
    if _EMB_DISABLED:
        return None
    if _EMB_MODEL is not None:
        return _EMB_MODEL
    with _EMB_MODEL_LOCK:
        if _EMB_MODEL is None and not _EMB_DISABLED:
            try:
                from fastembed import TextEmbedding
                _EMB_MODEL = TextEmbedding(EMBED_MODEL_NAME, threads=EMBED_THREADS)
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
    """Inkrementel: kun sider med ændret hash re-embeddes. Indeks i _index/embeddings.sqlite (gitignored).
    Kører under _EMB_LOCK; kald den fra en baggrundstråd (start + efter pull), aldrig inde i et request."""
    global _EMB_MAT, _EMB_KEYS, _EMB_DIRTY, _EMB_BUILDING
    model = _emb_model()
    if model is None:
        return
    import numpy as np   # se _semantic: numpy kraeves kun naar embeddings er slaaet til
    if not _EMB_LOCK.acquire(blocking=False):
        return  # en anden tråd bygger allerede
    _EMB_BUILDING = True
    try:
        _emb_refresh_locked(model, np)
    finally:
        _EMB_BUILDING = False
        _EMB_LOCK.release()


def _emb_refresh_locked(model, np) -> None:
    global _EMB_MAT, _EMB_KEYS, _EMB_DIRTY, _EMB_SNAPSHOT
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
        if p.is_redirect or p.is_generated:
            continue
        for i, text in enumerate(_chunks(p)):
            h = hashlib.sha1(text.encode("utf-8")).hexdigest()
            live.add((p.slug, i))
            if have.get((p.slug, i)) != h:
                todo.append((p.slug, i, h, text))
    for key in set(have) - live:
        con.execute("DELETE FROM emb WHERE slug=? AND idx=?", key)
    if todo:
        vecs = list(model.embed([t for _, _, _, t in todo], batch_size=EMBED_BATCH))
        con.executemany("INSERT OR REPLACE INTO emb VALUES (?,?,?,?)",
                        [(sl, i, h, np.asarray(v, dtype=np.float32).tobytes()) for (sl, i, h, _), v in zip(todo, vecs)])
    con.commit()
    rows = con.execute("SELECT slug, idx, vec FROM emb").fetchall()
    con.close()
    if not rows:
        _EMB_MAT, _EMB_KEYS = None, []
        _EMB_SNAPSHOT = (_EMB_MAT, _EMB_KEYS)
    else:
        mat = np.vstack([np.frombuffer(r[2], dtype=np.float32) for r in rows])
        norms = np.linalg.norm(mat, axis=1, keepdims=True); norms[norms == 0] = 1
        _EMB_MAT, _EMB_KEYS = mat / norms, [(r[0], r[1]) for r in rows]
        _EMB_SNAPSHOT = (_EMB_MAT, _EMB_KEYS)
    _EMB_DIRTY = False


def _semantic(query: str, limit: int = 40) -> list[tuple[str, float]]:
    """[(slug, cosine)] rangeret — bedste chunk pr. side."""
    model = _emb_model()
    if model is None:
        return []
    import numpy as np   # importeres foerst her: uden embeddings er numpy ikke en afhaengighed
    snap = _EMB_SNAPSHOT      # ét konsistent (mat, keys)-par; de to maa ikke laeses hver for sig
    if snap is None:
        # Første opbygning tager et par minutter for 900 sider — kør den i baggrunden
        # og degradér til to lanes imens.
        if not _EMB_BUILDING:
            threading.Thread(target=_emb_refresh, daemon=True).start()
        return []
    if _EMB_DIRTY and not _EMB_BUILDING:
        threading.Thread(target=_emb_refresh, daemon=True).start()   # brug det gamle indeks nu, opdatér i baggrunden
    mat, keys = snap
    q = np.asarray(next(iter(model.embed([query]))), dtype=np.float32)
    q = q / (np.linalg.norm(q) or 1)
    sims = mat @ q
    best: dict[str, float] = {}
    for (slug, _), sim in zip(keys, sims):
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
            fm = yaml.load(m.group(1), Loader=_YamlLoader) or {}
        except Exception:
            fm = {}
        body = raw[m.end():]
    if not isinstance(fm, dict):
        fm = {}
    slug = path.stem
    low_ent = str(fm.get("entity") or slug).lower()
    low_slug = slug.lower()
    low_alias = " ".join(str(a) for a in (fm.get("aliases") or [])).lower()
    low_desc = str(fm.get("description", "")).lower()
    low_tags = " ".join(str(t) for t in (fm.get("tags") or [])).lower()
    low_body = body.lower()
    return Page(path=path, slug=slug, folder=path.parent.name, fm=fm,
                body=body, mtime=path.stat().st_mtime, links={l.strip().lower() for l in LINK_RE.findall(body)},
                low_ent=low_ent, low_slug=low_slug, low_slug_joined=low_slug.replace("-", ""),
                low_alias=low_alias, low_desc=low_desc, low_tags=low_tags, low_body=low_body,
)


def _refresh(force: bool = False) -> None:
    """Re-scan changed files (cheap: 900 files, stat only unless changed).

    Indekset muteres aldrig paa stedet: der bygges en ny dict som byttes ind med
    én tildeling. Laesere tager ét snapshot (`_INDEX`) og undgaar dermed
    "dictionary changed size during iteration" naar pull-loopet opdaterer
    samtidig med en soegning (issue #23)."""
    global _INDEX, _INDEX_TIME, _FTS_DIRTY, _EMB_DIRTY, _ALIAS
    # Hurtig vej uden laas: naar indekset er friskt nok, skal en soegning ikke
    # staa i koe bag en igangvaerende genindlaesning (issue #23).
    if not force and time.time() - _INDEX_TIME < 2:
        return
    if force:
        LOCK.acquire()
    elif not LOCK.acquire(blocking=False):
        # En anden traad genindlaeser allerede. En laeser skal ikke staa i koe bag
        # den; det nuvaerende snapshot er hoejst et par hundrede ms gammelt (issue #23).
        return
    try:
        if not force and time.time() - _INDEX_TIME < 2:
            return
        current = _INDEX
        fresh: dict[str, Page] = {}
        changed = False
        for path in ENTITIES.glob("*/*.md"):
            cur = current.get(path.stem)
            st = path.stat().st_mtime
            unchanged = cur is not None and cur.mtime == st
            if unchanged and not force:
                fresh[path.stem] = cur
                continue
            p = _parse(path)
            if p:
                fresh[path.stem] = p
                # En tvungen genindlaesning af en ufaendret fil maa ikke markere
                # FTS og embeddings som beskidte; ellers genopbygges de i ét vaek.
                if not unchanged:
                    changed = True
                    _FTS_CHANGED.add(path.stem)
            elif cur is not None:
                fresh[path.stem] = cur
        gone = set(current) - set(fresh)
        if gone:
            _FTS_DELETED.update(gone)
        if len(fresh) != len(current):
            changed = True
        alias: dict[str, str] = {}
        for slug, page in fresh.items():
            alias.setdefault(page.entity.lower(), slug)
            for a in (page.fm.get("aliases") or []):
                alias.setdefault(str(a).lower(), slug)
        _INDEX = fresh          # atomisk swap
        _ALIAS = alias
        if changed:
            _FTS_DIRTY = True
            _EMB_DIRTY = True
        _INDEX_TIME = time.time()
    finally:
        LOCK.release()


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
    # Alias-opslag i et map bygget i _refresh i stedet for lineaer scanning (issue #26).
    hit = _ALIAS.get(name.strip().lower())
    return _follow(_INDEX[hit]) if hit and hit in _INDEX else None


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
def _git(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    # stdin=DEVNULL + no terminal prompt: git-hooks (auto-push via ssh) må aldrig
    # arve MCP'ens stdio-transport, ellers hænger serveren.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes"}
    try:
        return subprocess.run(["git", *args], cwd=WIKI, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", stdin=subprocess.DEVNULL, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args=["git", *args], returncode=124, stdout="", stderr="timeout")


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


def wiki_search(query: str, type: str = "", limit: int = 8, mode: str = "rrf") -> list[dict]:
    """Søg i wikien. Returnerer kompakte hits (slug, type, entity, description, last_updated, path, score, snippet,
    stale) — hent detaljer med wiki_outline/wiki_get. `type` afgrænser til person|project|client|tool|place|concept|recipe.
    Ranking: BM25 (SQLite FTS5) + feltvægtet term-match fusioneret med Reciprocal Rank Fusion; forældede sider nedvægtes.
    `mode` = rrf (default, fire lanes: feltvaegtet match, BM25 pr. side, BM25 pr. sektion og semantisk) | bm25 | weighted | sections | semantic (til evaluering). Hits faar `section` = den bedste overskrift, saa naeste kald kan vaere wiki_get(slug, section=...)."""
    _refresh()
    raw_terms = [t for t in re.split(r"\s+", query.lower().strip()) if t]
    # Dansk skriver sammensatte ord med bindestreg: "dokploy-version", "wordpress-sikkerhedshullet".
    # Uden dette matcher "dokploy-version" ikke siden [[dokploy]], og navneboostet paa 10 udebliver.
    # Delene tilfoejes ud over det hele ord, saa den eksakte sammensaetning stadig vejer tungest.
    for t in list(raw_terms):
        if "-" in t:
            raw_terms += [d for d in t.split("-") if len(d) > 2 and d not in raw_terms]
    # Stopord/korte ord (i, og, på, af, en …) drukner signalet i term-match — behold dem kun hvis intet andet er tilbage.
    terms = [t for t in raw_terms if len(t) > 2 and t not in STOPWORDS] or raw_terms
    if not terms:
        return []

    def allowed(p: Page) -> bool:
        if p.is_redirect or p.is_generated:
            return False
        return not type or str(p.fm.get("type", p.folder)) == type or p.folder == FOLDERS.get(type, "")

    weighted: list[tuple[float, Page]] = []
    for p in _INDEX.values():
        if not allowed(p):
            continue
        score = 0.0
        # `alle_termer` erstatter et tidligere `all(t in p.haystack ...)`. haystack var
        # sammensat af netop entity, alias, description og body, og en term indeholder
        # aldrig mellemrum, saa de fire booleans nedenfor giver samme svar — uden at
        # scanne hele brødteksten en ekstra gang pr. term, og uden en 3,4 MB dublet.
        alle_termer = True
        for t in terms:
            e = t in p.low_ent
            if e or t in p.low_slug or (len(t) > 6 and t in p.low_slug_joined): score += 10  # sammensatte ord: tilbudsskabelon ~ tilbuds-skabelon
            a = t in p.low_alias
            if a: score += 8
            d = t in p.low_desc
            if d: score += 4
            if t in p.low_tags: score += 3
            c = p.low_body.count(t)
            if c: score += min(c, 10) * 0.6
            if not (e or a or d or c): alle_termer = False
        if alle_termer:
            score += 3
        if score > 0:
            weighted.append((score, p))
    weighted.sort(key=lambda x: (-x[0], x[1].slug))
    w_rank = {p.slug: i for i, (_, p) in enumerate(weighted)}
    b_rank = {sl: i for i, sl in enumerate(sl for sl in _bm25(terms, 60) if sl in _INDEX and allowed(_INDEX[sl]))}
    # Fjerde lane: BM25 pr. sektion. Et fakta dybt i en lang side taber ellers altid paa
    # laengdenormaliseringen, selv om sektionen omkring det er kort og praecis.
    sec_hits = [(sl, hd) for sl, hd in _bm25_sections(terms, 40) if sl in _INDEX and allowed(_INDEX[sl])]
    sec_rank = {sl: i for i, (sl, _) in enumerate(sec_hits)}
    best_section = {sl: hd for sl, hd in sec_hits}

    s_rank: dict[str, int] = {}
    if mode in ("rrf", "semantic"):
        s_rank = {sl: i for i, (sl, sim) in enumerate((sl, sim) for sl, sim in _semantic(query, 60)
                                                          if sim >= 0.35 and sl in _INDEX and allowed(_INDEX[sl]))}
    if mode == "weighted":
        fused = {sl: 1.0 / (60 + r) for sl, r in w_rank.items()}
    elif mode == "bm25":
        fused = {sl: 1.0 / (60 + r) for sl, r in b_rank.items()}
    elif mode == "sections":
        fused = {sl: 1.0 / (60 + r) for sl, r in sec_rank.items()}
    elif mode == "semantic":
        fused = {sl: 1.0 / (60 + r) for sl, r in s_rank.items()}
    else:
        # RRF k=60; den semantiske lane vægtes 0,6 — den er stærk på omskrivninger men svag på egennavne.
        fused = {}
        for lane, weight in ((w_rank, 1.0), (b_rank, 1.0), (sec_rank, 0.3), (s_rank, 0.6)):
            for sl, r in lane.items():
                fused[sl] = fused.get(sl, 0.0) + weight / (60 + r)
    scored = []
    for sl, sc in fused.items():
        p = _INDEX[sl]
        if _is_stale(p):
            sc *= 0.7
        # Et arkiveret svar er afledt viden. Det skal kunne findes, men ikke fortraenge
        # den entitet det handler om (issue #43).
        if str(p.fm.get("type", "")) == "answer":
            sc *= 0.6
        scored.append((sc, p))
    scored.sort(key=lambda x: (-x[0], x[1].slug))
    top = scored[: max(1, min(limit, 30))]

    def _sec(page: Page, hd: str | None) -> str:
        # overskriften er gemt som "<entity> <overskrift>" i indekset
        if not hd:
            return ""
        return hd[len(page.entity):].strip() if hd.startswith(page.entity) else hd.strip()

    # En side kan godt staa i best_section og alligevel mangle et brugbart pejlemaerke:
    # den globale bane kan have peget paa intro-sektionen, hvis overskrift er tom.
    mangler = [pp.slug for _, pp in top if not _sec(pp, best_section.get(pp.slug))]
    ekstra = _best_sections_for(mangler, terms) if mangler else {}
    out = []
    for sc, p in top:
        d = p.head(); d["score"] = round(sc * 1000, 2); d["snippet"] = _snippet(p.body, terms, 160)
        sec = _sec(p, best_section.get(p.slug)) or _sec(p, ekstra.get(p.slug))
        if sec:
            d["section"] = sec
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


HISTORY_RE = re.compile(r"^>\s*\[!info\]\s*Historik:\s*(.+)$", re.M)
# Noeglen kan indeholde kolon og skraastreg (fx "beloeb:timepris/time"), saa den
# laeses som alt op til det foerste anfoerselstegn.
HISTORY_ITEM_RE = re.compile(
    r"([^\";]+?)\s+\"([^\"]*)\"\s+gyldig indtil (\d{4}-\d{2}-\d{2}), derefter \"([^\"]*)\"", re.I)


def _history(body: str) -> list[dict]:
    """Historik-callouts som [{noegle, gammel vaerdi, gyldig indtil, ny vaerdi}] (issue #47)."""
    out = []
    for m in HISTORY_RE.finditer(body):
        for key, old_v, until, new_v in HISTORY_ITEM_RE.findall(m.group(1)):
            out.append({"key": key.strip().lower(), "old": old_v, "until": until, "new": new_v})
    return out


def wiki_get(slug: str, section: str = "", max_chars: int = 12000, as_of: str = "") -> dict:
    """Hent en side (eller kun én ##-sektion via `section`) ud fra slug, entitetsnavn eller alias.
    Citér som `path#heading` når du bruger indholdet.

    `as_of=YYYY-MM-DD` svarer i stedet på hvad der gjaldt på den dato: for de syv nøgler
    modsigelses-tjekket kender (e-mail, telefon, beløb, version, kontaktperson, hosting)
    udledes de tidligere værdier af historik-callouts på siden."""
    p = _resolve(slug)
    if not p:
        hits = wiki_search(slug, limit=5)
        return {"error": f"Ingen side '{slug}'", "suggestions": [h["slug"] for h in hits]}
    if as_of:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", as_of):
            return {"error": "as_of skal være YYYY-MM-DD"}
        changed = [h for h in _history(p.body) if h["until"] > as_of]
        d = p.head()
        d["as_of"] = as_of
        d["values_then"] = [{"key": h["key"], "value_then": h["old"],
                             "changed_on": h["until"], "value_now": h["new"]} for h in changed]
        d["note"] = ("Kun værdier der er ændret siden datoen. Tom liste betyder at de nuværende "
                     "værdier også gjaldt dengang, så vidt historikken rækker.")
        return d
    body = p.body
    if section:
        want = section.strip().lstrip("#").strip().lower()
        match = [(h, t) for h, t in _sections(body) if h.lower() == want or want in h.lower()]
        if not match:
            return {"error": f"Ingen sektion '{section}'", "sections": [h for h, _ in _sections(body) if h]}
        body = f"## {match[0][0]}\n\n{match[0][1]}"
    truncated = len(body) > max_chars
    out = {**p.head(), "sources": p.fm.get("sources") or [], "aliases": p.fm.get("aliases") or [],
           "resource": p.fm.get("resource"), "body": body[:max_chars], "truncated": truncated}
    if truncated:
        # Et `truncated: true` alene er ikke nok. Paa timetrack laa prisen ved tegn 20.194 af
        # 63.257: en model fik de foerste 12.000 tegn, saa ingen pris, og intet spor af at der
        # fandtes en prissektion. Naar de klippede overskrifter staar i svaret, kan den hente
        # den rigtige sektion i stedet for at gaette.
        out["omitted_chars"] = len(body) - max_chars
        out["omitted_sections"] = [mm.group(1).strip() for mm in
                                   re.finditer(r"^## (.+)$", body, re.M) if mm.start() >= max_chars]
        out["note"] = ("Siden er klippet. Staar svaret maaske i en af omitted_sections, saa hent den "
                       "med wiki_get(slug, section=...) foer du svarer.")
    return out


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


def wiki_recent(days: int = 7, limit: int = 25) -> list[dict]:
    """Sider ændret inden for N dage (efter last_updated i frontmatter). Godt til 'hvad er sket?'."""
    _refresh()
    cutoff = dt.date.today() - dt.timedelta(days=days)
    rows = []
    for p in _INDEX.values():
        if p.is_redirect or p.is_generated:
            continue
        lu = p.fm.get("last_updated")
        if isinstance(lu, str):
            try: lu = dt.date.fromisoformat(lu[:10])
            except ValueError: lu = None
        if isinstance(lu, dt.date) and lu >= cutoff:
            rows.append((lu, p))
    rows.sort(key=lambda x: (x[0], x[1].slug), reverse=True)
    return [p.head() for _, p in rows[:limit]]


def wiki_handover() -> str:
    """Seneste opgave-handover (_handovers/latest.md) — læs ved start af en session."""
    f = WIKI / "_handovers" / "latest.md"
    return f.read_text(encoding="utf-8") if f.exists() else "Ingen handover."


def wiki_stats() -> dict:
    """Antal sider pr. type, seneste ændringer og git-status for vaulten."""
    # force=True genlaeste alle 907 filer ved hvert kald og kostede 335 ms p50.
    # mtime-sweepet fanger enhver aendring alligevel, saa tallene bliver de samme.
    _refresh()
    counts: dict[str, int] = {}
    for p in _INDEX.values():
        counts[p.folder] = counts.get(p.folder, 0) + 1
    st = _git("status", "--short")
    log = _git("log", "-3", "--format=%h %ad %s", "--date=short")
    return {"pages": len(_INDEX), "by_folder": counts,
            "dirty_files": len([l for l in st.stdout.splitlines() if l.strip()]),
            "last_commits": log.stdout.strip().splitlines()}


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
    if not section and COMMIT_RE.match(text.strip().split("\n")[0]):
        section = "Aftaler"   # aftale-formatet hører altid hjemme i sin egen sektion (issue #38)
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
        # Bi-temporalt: den gamle vaerdi slettes aldrig, men faar en gyldighedsperiode,
        # saa "hvad var prisen i juli" stadig kan besvares (issue #47).
        hist = "; ".join(f"{c['key']} \"{c['old']}\" gyldig indtil {today}, derefter \"{c['new']}\""
                         for c in contradictions)
        block += f"\n> [!info] Historik: {hist}"
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


# --------------------------------------------------------------------------- elicitation (issue #44)
# Naar wiki_create er i tvivl om en dublet, er det bedre at spoerge end at gaette.
# Claude Code kan svare paa et elicitation-kald; claude.ai-connectoren kan formentlig
# ikke, og et kald der bare haenger er vaerre end intet. Derfor: spoerg kun naar
# klienten annoncerer stoette, og degradér ellers til at returnere kandidaterne.


class _DupeChoice(BaseModel):
    """Svar paa 'er det her en dublet?'"""
    opret_alligevel: bool = Field(
        default=False,
        description="Ja = de er forskellige entiteter, opret den nye side. Nej = skriv til den eksisterende.")


def _can_elicit(ctx) -> bool:
    """Annoncerer klienten stoette for elicitation?"""
    if ctx is None:
        return False
    try:
        caps = ctx.session.client_params.capabilities        # type: ignore[attr-defined]
        return getattr(caps, "elicitation", None) is not None
    except Exception:
        return False


async def _ask_about_duplicate(ctx, entity: str, best: dict) -> bool | None:
    """True/False fra brugeren, eller None hvis der ikke kunne spoerges."""
    if not _can_elicit(ctx):
        return None
    try:
        res = await ctx.elicit(
            message=(f"'{entity}' ligner den eksisterende side '{best['slug']}' "
                     f"({best['why']}, score {best['score']}). Er det en anden entitet?"),
            schema=_DupeChoice)
        if getattr(res, "action", "") == "accept" and res.data is not None:
            return bool(res.data.opret_alligevel)
        return False
    except Exception:
        return None


# --------------------------------------------------------------------------- entity resolution (issue #42)
# Auto-ingest koerer dagligt og ville ellers oprette "Anna Katrin", "anna-katrin-noergaard"
# og "Annas Hoejskole" som tre sider. Kandidaterne vises, og tvivlstilfaelde afvises,
# fremfor at en cosine-graense alene afgoer sagen.
DUPLICATE_SCORE = 0.72      # over denne: afvis oprettelse medmindre force=True.
#                             Sat over den semantiske stoej mellem to tilfaeldige personsider
#                             (maalt 0,64-0,65), saa kun rigtige dubletter blokerer.
CANDIDATE_SCORE = 0.42      # over denne: vis som kandidat


def _dup_candidates(entity: str, description: str, type_: str, aliases: list[str] | None = None) -> list[dict]:
    """Muligt eksisterende match paa navn, alias og betydning. Score 0-1, hoejeste foerst."""
    needle = " ".join(x for x in [entity, description] if x).strip()
    if not needle:
        return []
    scored: dict[str, dict] = {}

    def bump(slug: str, score: float, why: str) -> None:
        row = scored.get(slug)
        if row is None:
            page = _INDEX.get(slug)
            if page is None or page.is_redirect or page.is_generated:
                return
            row = scored[slug] = {"slug": slug, "entity": page.entity,
                                  "type": str(page.fm.get("type", page.folder)),
                                  "path": page.path.relative_to(WIKI).as_posix(),
                                  "score": 0.0, "why": []}
        if score > row["score"]:
            row["score"] = score
        if why not in row["why"]:
            row["why"].append(why)

    # 1. eksakt navn eller alias
    for name in [entity] + list(aliases or []):
        hit = _ALIAS.get(str(name).strip().lower())
        if hit:
            bump(hit, 1.0, "samme navn eller alias")

    # 2. leksikalsk: samme ord i entity/beskrivelse
    for row in wiki_search(needle, type=type_, limit=5, mode="weighted"):
        bump(row["slug"], 0.55, "ligner leksikalsk")

    # 3. semantisk, hvis lanen er varm
    for slug, sim in _semantic(needle, limit=5):
        if sim >= CANDIDATE_SCORE:
            bump(slug, float(sim), f"semantisk naerhed {sim:.2f}")

    out = sorted(scored.values(), key=lambda r: -r["score"])
    for r in out:
        r["score"] = round(r["score"], 2)
        r["why"] = ", ".join(r["why"])
    return [r for r in out if r["score"] >= CANDIDATE_SCORE][:5]


def wiki_create(type: str, slug: str, entity: str, description: str, body: str,
                tags: list[str] | None = None, aliases: list[str] | None = None,
                source: str = "", confidence: str = "medium", resource: str = "",
                force: bool = False) -> dict:
    """Opret en ny wiki-side. `type` ∈ person|project|client|tool|place|concept|recipe. `slug` = kebab-case
    filnavn uden .md. `description` = én sætning (≤180 tegn) om hvad entiteten ER. `body` = markdown der
    starter med '# Titel'.

    Siden oprettes ikke hvis der findes en side der ligner nok: svaret indeholder da `candidates`
    med slug, score og hvorfor, og forslaget er at bruge wiki_append på den bedste i stedet.
    `force=True` opretter alligevel — brug den kun når kandidaterne beviseligt er andre entiteter."""
    if type not in FOLDERS:
        return {"error": f"Ugyldig type '{type}'"}
    slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")
    if not slug:
        return {"error": "Tom slug"}
    _refresh()
    if slug in _INDEX:
        return {"error": f"'{slug}' findes allerede i {_INDEX[slug].folder}/ — brug wiki_append"}
    # _INDEX noegles paa filnavn: to filer med samme navn i hver sin mappe ville
    # skiftes til at overskrive hinanden ved hver scanning (issue #27).
    dupe = next((p for p in ENTITIES.glob(f"*/{slug}.md")), None)
    if dupe is not None:
        return {"error": f"'{slug}' findes allerede som {dupe.parent.name}/{slug}.md — vaelg et andet slug"}
    if len(description) > 220 or '"' in description or "\\" in description:
        return {"error": "description skal være ≤220 tegn uden anførselstegn/backslash"}
    candidates = _dup_candidates(entity, description, type, aliases)
    if candidates and not force:
        best = candidates[0]
        if best["score"] >= DUPLICATE_SCORE:
            return {"error": f"'{entity}' ligner en eksisterende side: {best['slug']} ({best['why']}).",
                    "candidates": candidates,
                    "suggestion": f"wiki_append('{best['slug']}', ...) — eller wiki_create(..., force=True) "
                                  f"hvis det beviseligt er en anden entitet"}
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
    path.parent.mkdir(parents=True, exist_ok=True)  # foerste side af en ny type (issue #27)
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
            # Eksakt match: startswith("/health") gav ogsaa /healthz og alt andet med
            # praefikset adgang uden auth (issue #28). Sideantallet er intern
            # information og kraever nu token.
            if path == "/health":
                _refresh()
                return JSONResponse({"ok": True})
            if request.method == "GET" and path in ("/", "/index.html"):
                if landing.exists():
                    return HTMLResponse(landing.read_text(encoding="utf-8"))
                return PlainTextResponse("wiki-mcp: MCP endpoint at /mcp (Bearer token required)")
            if request.method == "GET" and path in ("/favicon.ico", "/robots.txt"):
                return PlainTextResponse("User-agent: *\nDisallow: /mcp\n" if path == "/robots.txt" else "", status_code=200 if path == "/robots.txt" else 404)
            auth = request.headers.get("authorization", "")
            # constant-time: en almindelig streng-sammenligning laekker praefikslaengden
            # gennem svartiden (issue #28).
            if not hmac.compare_digest(auth, f"Bearer {token}"):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            if path == "/health/full":
                _refresh()
                return JSONResponse({"ok": True, "pages": len(_INDEX)})
            return await call_next(request)

    app = mcp.streamable_http_app()
    app.add_middleware(Auth)
    return app


_UVICORN_SERVER = None  # saettes naar http-transporten koerer (issue #22)


def _script_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pull_loop(interval: int) -> None:
    """Pull main periodisk. Hvis selve server-scriptet ændrer sig (ny version pushet), genstart processen,
    så deploy = git push uden redeploy af containeren.

    Hele kroppen er pakket ind: en enkelt uventet fejl må ikke kunne dræbe tråden.
    Sker det, står serveren og svarer på gamle data uden at nogen opdager det."""
    me = Path(__file__).resolve()
    my_sha = _script_sha(me)
    ticks = 0
    while True:
        time.sleep(interval)
        ticks += 1
        try:
            # LOCK holdes bevidst ikke over git-kald: et langsomt git ville ellers blokere
            # baade /health og alle soegninger og give 502 gennem Cloudflares 100 s-loft (issue #24).
            dirty = _git("status", "--short", "--untracked-files=no", timeout=20).stdout.strip()
            if dirty:
                print(f"wiki-mcp: springer pull over, {len(dirty.splitlines())} sporede filer er ændret",
                      file=sys.stderr, flush=True)
                continue
            r = _git("pull", "--rebase", "-q", "origin", "main", timeout=60)
            if r.returncode != 0:
                _git("rebase", "--abort", timeout=20)
                print(f"wiki-mcp: pull fejlede ({r.returncode}): {r.stderr.strip()[:200]}",
                      file=sys.stderr, flush=True)
                continue
            _refresh()
            if not _EMB_DISABLED:
                _emb_refresh()
            if ticks % 12 == 0:      # ca. hver time ved 5-minutters interval
                head = _git("log", "-1", "--format=%h %s", timeout=20).stdout.strip()[:80]
                print(f"wiki-mcp: pull-loop kører, HEAD {head}", file=sys.stderr, flush=True)
            new_sha = _script_sha(me)
            if new_sha != my_sha:
                # SHA i stedet for mtime, og py_compile foerst: et push med syntaksfejl
                # maa ikke give en crashloop (issue #22).
                probe = subprocess.run([sys.executable, "-m", "py_compile", str(me)],
                                       capture_output=True, text=True, timeout=60)
                if probe.returncode != 0:
                    print(f"wiki-mcp: ny version kompilerer ikke — beholder den kørende: "
                          f"{probe.stderr.strip()[:300]}", file=sys.stderr, flush=True)
                    my_sha = new_sha
                    continue
                print("wiki-mcp: server-scriptet er opdateret via git — genstarter", file=sys.stderr, flush=True)
                srv = _UVICORN_SERVER
                if srv is not None:
                    srv.should_exit = True
                    for _ in range(50):
                        if getattr(srv, "started", False) is False:
                            break
                        time.sleep(0.1)
                os.execv(sys.executable, [sys.executable, *sys.argv])
        except Exception as e:      # traaden skal overleve alt andet end en genstart
            print(f"wiki-mcp: pull-loop fejlede ({e.__class__.__name__}: {str(e)[:200]}) — prøver igen",
                  file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- aftaler (issue #38)
# Konvention, én linje pr. aftale under "## Aftaler":
#   - [ ] (aftalt 2026-09-06, forfald 2026-09-20) Mads -> [[john-tidtilro]]: sender tilbud paa destinationsmodul
# Pilen må skrives som -> eller den typografiske variant. Er der ingen pil, regnes
# aftalen som Mads' egen. [x] markerer den som indfriet.
COMMIT_RE = re.compile(
    r"^\s*-\s*\[(?P<done>[ xX])\]\s*"
    r"\((?P<meta>[^)]*)\)\s*"
    r"(?P<who>[^:]{0,80}?)\s*:\s*"
    r"(?P<what>.+?)\s*$")
_DATE_RE = re.compile(r"(aftalt|forfald)\s+(\d{4}-\d{2}-\d{2})")
_ARROW_RE = re.compile(r"\s*(?:->|\u2192|\u21d2)\s*")
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")


def _party(raw: str) -> str:
    """'[[john-tidtilro|John]]' -> 'john-tidtilro'; 'Mads' -> 'Mads'."""
    m = _WIKILINK_RE.search(raw or "")
    return (m.group(1) if m else (raw or "").strip()).strip()


def _parse_commitment(line: str, page: "Page") -> dict | None:
    m = COMMIT_RE.match(line)
    if not m:
        return None
    meta = dict((k, v) for k, v in _DATE_RE.findall(m.group("meta")))
    who = m.group("who") or ""
    parts = _ARROW_RE.split(who, maxsplit=1)
    if len(parts) == 2:
        owner, counterpart = _party(parts[0]), _party(parts[1])
    else:
        # Uden pil er 'who' den der skylder, og modparten er siden aftalen står på.
        owner, counterpart = (_party(who) or "Mads"), page.slug
    due = meta.get("forfald", "")
    overdue_days = 0
    if due:
        d = _to_date(due)
        if d:
            overdue_days = (dt.date.today() - d).days
    done = m.group("done").lower() == "x"
    if done:
        overdue_days = 0
    return {
        "slug": page.slug, "entity": page.entity, "path": page.path.relative_to(WIKI).as_posix(),
        "done": done,
        "owner": owner, "counterpart": counterpart,
        "what": m.group("what").strip(),
        "agreed": meta.get("aftalt", ""), "due": due,
        "overdue_days": overdue_days if overdue_days > 0 else 0,
        "line": line.strip(),
    }


def _all_commitments() -> list[dict]:
    """Alle aftaler fra "## Aftaler"-sektionerne. Snapshot-læsning, ingen lås."""
    out = []
    for p in _INDEX.values():
        if p.is_redirect or p.is_generated:
            continue
        for head, text in _sections(p.body):
            if head.strip().lower() != "aftaler":
                continue
            for line in text.split("\n"):
                c = _parse_commitment(line, p)
                if c:
                    out.append(c)
    return out


def wiki_commitments(person: str = "", overdue: bool = False, include_done: bool = False,
                     within_days: int = 0, limit: int = 50) -> list[dict]:
    """Aftaler og loefter fra "## Aftaler"-sektionerne paa tvaers af wikien.

    `person` filtrerer på slug eller navn i begge ender af aftalen. `overdue=True` giver kun
    dem hvis forfald er passeret. `within_days` giver dem der forfalder inden for N dage.
    Sorteret med de mest forfaldne først. Brug den til 'hvad har jeg lovet hvem'."""
    _refresh()
    rows = [c for c in _all_commitments() if include_done or not c["done"]]
    if person:
        needle = person.strip().lower()
        rows = [c for c in rows
                if needle in c["owner"].lower() or needle in c["counterpart"].lower() or needle in c["slug"].lower()]
    if overdue:
        rows = [c for c in rows if c["overdue_days"] > 0]
    if within_days:
        horizon = dt.date.today() + dt.timedelta(days=within_days)
        rows = [c for c in rows if c["due"] and (_to_date(c["due"]) or dt.date.max) <= horizon]
    rows.sort(key=lambda c: (-c["overdue_days"], c["due"] or "9999-99-99", c["slug"]))
    return rows[:limit]


def wiki_commit_add(slug: str, what: str, due: str = "", agreed: str = "",
                    owner: str = "Mads", counterpart: str = "") -> dict:
    """Tilføj en aftale til en sides "## Aftaler". `what` = hvad der er lovet, én sætning.
    `due` og `agreed` er YYYY-MM-DD (agreed defaulter til i dag). `owner` er den der skylder;
    sæt owner til personen og counterpart til 'Mads' når det er den anden vej."""
    page = _resolve(slug)
    if not page:
        return {"error": f"Ingen side '{slug}' — tjek stavning via wiki_search"}
    for label, value in (("agreed", agreed), ("due", due)):
        if value and not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return {"error": f"{label} skal være YYYY-MM-DD"}
    agreed = agreed or dt.date.today().isoformat()
    other = counterpart or f"[[{page.slug}]]"
    meta = f"aftalt {agreed}" + (f", forfald {due}" if due else "")
    line = f"- [ ] ({meta}) {owner} → {other}: {what.strip()}"
    res = wiki_append(page.slug, line, section="Aftaler")
    if isinstance(res, dict) and "error" not in res:
        res["commitment"] = line
    return res


def _recent_review_lines(limit: int = 5) -> list[str]:
    """Nyeste ubehandlede punkter i _review-queue.md (modsigelser og kandidater)."""
    rq = WIKI / "_review-queue.md"
    if not rq.exists():
        return []
    out = []
    try:
        for line in rq.read_text(encoding="utf-8-sig").replace("\r\n", "\n").split("\n"):
            t = line.strip()
            if t.startswith("- [ ]"):
                out.append(re.sub(r"\s+", " ", t[5:].strip())[:180])
    except Exception:
        return []
    return out[-limit:]


def wiki_brief(limit_per_group: int = 5) -> dict:
    """Dagens overblik i ét kald: forfaldne og nært forestående aftaler, aktive kunder og
    projekter der er blevet forældede, nyt i review-køen, og hvornår vaulten sidst blev rørt.

    Beregnet til at blive kaldt i starten af en session eller før et møde, i stedet for at
    lede flere steder. Hver gruppe er hårdt begrænset, så svaret kan læses på et skærmbillede."""
    _refresh()
    n = max(1, min(limit_per_group, 20))
    commitments = wiki_commitments(limit=200)
    overdue = [c for c in commitments if c["overdue_days"] > 0][:n]
    soon_limit = dt.date.today() + dt.timedelta(days=14)
    soon = [c for c in commitments
            if c["overdue_days"] == 0 and c["due"] and (_to_date(c["due"]) or dt.date.max) <= soon_limit][:n]

    stale = []
    for p in _INDEX.values():
        if p.is_redirect or p.is_generated or p.folder not in ("clients", "projects"):
            continue
        if str(p.fm.get("status", "")).lower() in ARCHIVED_STATUS or not _is_stale(p):
            continue
        stale.append({"slug": p.slug, "entity": p.entity, "type": str(p.fm.get("type", p.folder)),
                      "last_updated": str(p.fm.get("last_updated", ""))})
    stale.sort(key=lambda r: r["last_updated"])

    recent = [p.head() for p in sorted(
        (p for p in _INDEX.values() if not p.is_redirect and not p.is_generated),
        key=lambda p: str(p.fm.get("last_updated", "")), reverse=True)[:n]]

    return {
        "date": dt.date.today().isoformat(),
        "overdue_commitments": overdue,
        "due_soon": soon,
        "stale_active": stale[:n],
        "review_queue": _recent_review_lines(n),
        "recently_updated": recent,
        "counts": {"commitments_open": len(commitments), "overdue": len([c for c in commitments if c["overdue_days"] > 0]),
                   "stale_active": len(stale), "pages": len(_INDEX)},
    }


# --------------------------------------------------------------------------- svar-arkiv (issue #43)
# Karpathys pointe: et svar der er slidt frem af flere opslag er selv viden. Uden et sted
# at lægge det bliver det samme arbejde gjort forfra i naeste session.
ANSWER_DIR = "answers"
ANSWER_STALE_DAYS = 90
CITE_RE = re.compile(r"^([\w\-./]+\.md)(?:#(.+))?$")


def wiki_answer(question: str, answer: str, cites: list[str], stale_days: int = ANSWER_STALE_DAYS,
                confidence: str = "medium") -> dict:
    """Arkivér et svar som en side i entities/answers/ med de kilder det bygger paa.

    `cites` er stier som `entities/clients/solaris.md#Drift` — samme form som wiki_get
    returnerer i `path`. Mindst \u00e9n citation er paakraevet: et svar uden kilder er en
    paastand. Siden faar `stale_after`, saa den selv melder sig naar den boer efterproeves,
    og `wiki-lint.py` advarer hvis en kilde forsvinder."""
    q = " ".join(str(question).split())
    if len(q) < 8:
        return {"error": "Spørgsmålet er for kort til at kunne genfindes"}
    if not answer or len(answer.strip()) < 20:
        return {"error": "Svaret er for kort til at være værd at arkivere"}
    if not cites:
        return {"error": "Mindst én citation er påkrævet — et svar uden kilder er en påstand"}

    bad = []
    clean = []
    for c in cites:
        c = str(c).strip().replace("\\", "/")
        m = CITE_RE.match(c)
        if not m or not (WIKI / m.group(1)).exists():
            bad.append(c)
        else:
            clean.append(c)
    if bad:
        return {"error": f"Ukendte kilder: {', '.join(bad[:3])} — brug stien fra wiki_get"}

    today = dt.date.today()
    slug = re.sub(r"[^a-z0-9]+", "-", q.lower())[:60].strip("-")
    slug = f"{today.isoformat()}-{slug}"
    path = ENTITIES / ANSWER_DIR / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return {"error": f"'{slug}' er allerede arkiveret i dag — brug wiki_append hvis svaret er blevet bedre"}

    stale = (today + dt.timedelta(days=max(7, stale_days))).isoformat()
    desc = (q[:170] + "…") if len(q) > 170 else q
    fm = ["---", f'entity: "{q[:120]}"', "type: answer", f'description: "Arkiveret svar: {desc}"',
          f"aliases: []", "sources: []", f"confidence: {confidence if confidence in ('high','medium','low') else 'medium'}",
          f"created: {today.isoformat()}", f"last_updated: {today.isoformat()}",
          f"stale_after: {stale}", "tags: [svar, arkiv]",
          "cites:"] + [f"  - {c}" for c in clean] + ["---"]
    body = [f"# {q}", "", answer.strip(), "", "## Kilder", ""]
    body += [f"- `{c}`" for c in clean]
    body += ["", f"> Arkiveret {today.isoformat()}. Efterprøv senest {stale}: kilderne kan have ændret sig."]
    path.write_text("\n".join(fm + [""] + body) + "\n", encoding="utf-8", newline="\n")
    _refresh(force=True)
    git = _commit([path], f"wiki: arkivér svar {slug}")
    return {"ok": True, "slug": slug, "path": path.relative_to(WIKI).as_posix(),
            "stale_after": stale, "cites": clean, "git": git}


# --------------------------------------------------------------------------- typede relationer (issue #45)
# 900 sider har kun utypede [[links]], saa "hvem hoster hvad" er en soegning og ikke et opslag.
# Konvention, én linje under "## Relationer":
#   - hoster-hos:: [[hetzner]] — hovedserveren
# Lukket vokabular, saa grafen ikke bliver en synonymsuppe. Utypede linjer virker uaendret.
PREDICATES = {
    "ejer": "ejer eller driver",
    "kontakt-for": "er kontaktperson for",
    "arbejder-hos": "er ansat eller tilknyttet",
    "kunde-hos": "er kunde hos",
    "leverandoer-til": "leverer til",
    "hoster-hos": "hostes hos",
    "bruger": "bruger dette vaerktoej eller denne teknologi",
    "del-af": "er en del af",
    "erstattet-af": "er afloest af",
    "henvist-af": "kom ind via",
}
REL_RE = re.compile(r"^\s*-\s*([a-zaeoeaa\-]{3,20})::\s*(.+?)\s*$", re.I)


def _typed_relations(p: "Page") -> list[dict]:
    """[(praedikat, maal-slug, note)] fra sidens "## Relationer"-sektion."""
    out = []
    for head, text in _sections(p.body):
        if head.strip().lower() != "relationer":
            continue
        for line in text.split("\n"):
            m = REL_RE.match(line)
            if not m:
                continue
            pred = m.group(1).lower()
            if pred not in PREDICATES:
                continue
            rest = m.group(2)
            link = _WIKILINK_RE.search(rest)
            if not link:
                continue
            note = rest.split("—", 1)[1].strip() if "—" in rest else ""
            out.append({"predicate": pred, "target": link.group(1).strip().lower(), "note": note[:160]})
    return out


def wiki_graph(slug: str = "", predicates: list[str] | None = None, depth: int = 1,
               limit: int = 60) -> dict:
    """Typede relationer som en graf. Uden `slug` returneres alle kanter af de oenskede typer,
    saa man kan spoerge "hvem hoster hvad" i ét kald. Med `slug` foelges kanterne ud fra den side,
    `depth` niveauer (maks 3), i begge retninger.

    Gyldige praedikater: ejer, kontakt-for, arbejder-hos, kunde-hos, leverandoer-til, hoster-hos,
    bruger, del-af, erstattet-af, henvist-af. Se `## Relationer` i _schema.md for formatet."""
    _refresh()
    wanted = {str(p).lower() for p in (predicates or [])} & set(PREDICATES)
    edges = []
    for p in _INDEX.values():
        if p.is_redirect or p.is_generated:
            continue
        for rel in _typed_relations(p):
            if wanted and rel["predicate"] not in wanted:
                continue
            edges.append({"from": p.slug, "predicate": rel["predicate"],
                          "to": rel["target"], "note": rel["note"]})
    if not slug:
        return {"edges": edges[:limit], "count": len(edges),
                "predicates": sorted({e["predicate"] for e in edges})}

    start = _resolve(slug)
    if not start:
        return {"error": f"Ingen side '{slug}' — tjek stavning via wiki_search"}
    seen = {start.slug}
    frontier = {start.slug}
    picked = []
    for _ in range(max(1, min(depth, 3))):
        nxt = set()
        for e in edges:
            if e["from"] in frontier and e["to"] not in seen:
                picked.append(e); nxt.add(e["to"])
            elif e["to"] in frontier and e["from"] not in seen:
                picked.append({**e, "direction": "ind"}); nxt.add(e["from"])
        seen |= nxt
        frontier = nxt
        if not frontier:
            break
    return {"slug": start.slug, "edges": picked[:limit], "count": len(picked),
            "nodes": sorted(seen)}


# --------------------------------------------------------------------------- prompts (issue #41)
# Skills under /wiki-* findes kun på Mads' Windows-maskine. Prompts her virker mod
# den samme server fra Claude Code, Claude-appen på telefonen og claude.ai.


@mcp.prompt(name="daily_brief", title="Dagens overblik",
            description="Forfaldne aftaler, forældede kunder og nyt i review-køen")
def _p_daily_brief() -> str:
    return (
        "Kald wiki_brief() og skriv et kort dansk overblik ud fra svaret.\n\n"
        "Struktur: 1) forfaldne aftaler med hvem og hvor mange dage over, 2) aftaler der forfalder "
        "inden for 14 dage, 3) aktive kunder og projekter der er blevet forældede, med hvor længe siden, "
        "4) nye punkter i review-køen. Maks 15 linjer i alt.\n\n"
        "Slut med højst tre konkrete forslag til hvad Mads bør tage først, og hvorfor. "
        "Opfind intet: står der ikke noget i svaret, så skriv at der ikke er noget."
    )


@mcp.prompt(name="before_meeting", title="Før et møde",
            description="Alt wikien ved om en person eller kunde, plus åbne aftaler")
def _p_before_meeting(navn: str) -> str:
    return (
        f"Mads skal snart møde '{navn}'. Saml det wikien ved, i denne rækkefølge:\n\n"
        f"1. wiki_search('{navn}', limit=5) for at finde de rigtige sider. Er der flere kandidater, "
        "så vælg den mest specifikke og nævn de andre kort.\n"
        "2. wiki_outline(slug) og derefter wiki_get(slug, section=...) på de 2-3 sektioner der betyder noget. "
        "Hent aldrig hele siden.\n"
        f"3. wiki_commitments(person='{navn}') for åbne aftaler i begge retninger.\n\n"
        "Skriv et dansk resumé på maks 20 linjer: hvem det er, de 3 seneste daterede fakta med dato, "
        "åbne aftaler med frist, og 1-2 punkter Mads bør rejse. Citér sider som path#overskrift. "
        "Findes personen ikke i wikien, så skriv det i stedet for at gætte."
    )


@mcp.prompt(name="what_did_i_promise", title="Hvad har jeg lovet",
            description="Åbne aftaler, forfaldne først")
def _p_promises(person: str = "") -> str:
    who = f" der involverer '{person}'" if person else ""
    return (
        f"Kald wiki_commitments({'person=' + repr(person) + ', ' if person else ''}overdue=False) og vis alle åbne aftaler{who}.\n\n"
        "Grupper dem: forfaldne først med antal dage over, så dem der forfalder inden for 14 dage, "
        "så resten. Vis hvem der skylder hvem, hvad der er lovet, fristen og hvilken side det står på.\n\n"
        "Er der forfaldne aftaler hvor Mads skylder noget, så foreslå en konkret næste handling for hver."
    )


@mcp.prompt(name="ingest_source", title="Ingest en kilde",
            description="Skriv en mail, note eller samtale ind i wikien efter reglerne")
def _p_ingest(tekst: str) -> str:
    return (
        "Skriv det væsentlige fra teksten nedenfor ind i wikien.\n\n"
        "Regler: find først entiteten med wiki_search. Findes den, brug wiki_append med et dateret punkt "
        "på formen '- **D. måned YYYY — emne:** destillat' og maks to linjer. Findes den ikke, så overvej "
        "wiki_create — den afviser selv oprettelsen hvis noget ligner for meget, og viser kandidater. "
        "Er der tale om et løfte eller en aftale, brug wiki_commit_add med en frist.\n\n"
        "Skriv aldrig det samme på to sider: vælg den mest specifikke (projekt før kunde) og link fra de andre. "
        "Gem aldrig passwords, API-nøgler eller konkrete fakturabeløb. Dansk tekst, engelske fagtermer.\n\n"
        f"Tekst:\n\n{tekst}"
    )


async def _wiki_create_with_ask(ctx: Context, type: str, slug: str, entity: str, description: str,
                                body: str, tags: list[str] | None = None, aliases: list[str] | None = None,
                                source: str = "", confidence: str = "medium", resource: str = "",
                                force: bool = False) -> dict:
    """Opret en ny wiki-side. `type` ∈ person|project|client|tool|place|concept|recipe. `slug` = kebab-case
    filnavn uden .md. `description` = én sætning (≤180 tegn) om hvad entiteten ER. `body` = markdown der
    starter med '# Titel'.

    Ligner en eksisterende side for meget, spørges du — kan klienten ikke svare, returneres
    kandidaterne i stedet, og du vælger selv wiki_append eller force=True."""
    call = functools.partial(wiki_create, type, slug, entity, description, body, tags, aliases,
                             source, confidence, resource, force)
    res = await anyio.to_thread.run_sync(call)
    if not (isinstance(res, dict) and res.get("candidates")) or force:
        return res
    answer = await _ask_about_duplicate(ctx, entity, res["candidates"][0])
    if answer is True:
        again = functools.partial(wiki_create, type, slug, entity, description, body, tags, aliases,
                                  source, confidence, resource, True)
        out = await anyio.to_thread.run_sync(again)
        if isinstance(out, dict):
            out["elicited"] = "brugeren bekræftede at det er en anden entitet"
        return out
    if answer is False:
        res["elicited"] = "brugeren bekræftede at det er den samme entitet — brug wiki_append"
    else:
        res["note"] = ("Klienten understøtter ikke elicitation, så der blev ikke spurgt. "
                       "Vælg selv: wiki_append på kandidaten, eller force=True hvis det er en anden entitet.")
    return res


# --------------------------------------------------------------------------- tool-registrering
# Wrappers registreres til sidst, saa modulet stadig eksponerer de synkrone
# funktioner under deres egne navne (issue #23).
for _fn, _ann in (
    (wiki_search, RO),
    (wiki_outline, RO),
    (wiki_get, RO),
    (wiki_related, RO),
    (wiki_recent, RO),
    (wiki_handover, RO),
    (wiki_stats, RO),
    (wiki_append, RW),
    (wiki_commitments, RO),
    (wiki_commit_add, RW),
    (wiki_brief, RO),
    (wiki_graph, RO),
    (wiki_answer, RW),
):
    mcp.tool(annotations=_ann)(_threaded(_fn))

# wiki_create registreres som async under sit eget navn: den skal kunne spoerge
# brugeren ved dublet-tvivl, og det kraever request-konteksten (issue #44).
_wiki_create_with_ask.__name__ = "wiki_create"
mcp.tool(annotations=RW)(_wiki_create_with_ask)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    ap.add_argument("--pull-interval", type=int, default=0, help="sekunder mellem git pull (0 = aldrig)")
    args = ap.parse_args()
    _refresh(force=True)  # koldstart: byg indekset fuldt
    if not _EMB_DISABLED:
        threading.Thread(target=_emb_refresh, daemon=True).start()   # varm den semantiske lane op
    if args.pull_interval > 0:
        threading.Thread(target=_pull_loop, args=(args.pull_interval,), daemon=True).start()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn
        # timeout_keep_alive under Cloudflares 100 s, saa idle forbindelser lukkes af os
        # og ikke af proxyen midt i en stream (issue #24).
        config = uvicorn.Config(_http_app(), host=mcp.settings.host, port=mcp.settings.port,
                                log_level="info", timeout_keep_alive=75)
        _UVICORN_SERVER = uvicorn.Server(config)
        _UVICORN_SERVER.run()
