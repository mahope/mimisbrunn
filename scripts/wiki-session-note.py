#!/usr/bin/env python3
"""
Stop-hook: skriv en kort sessionsstatus tilbage til wikien (issue #35).

Baggrund: på 30 dage blev der lavet 3 rigtige `wiki: append`-commits mod et mål om
20 om ugen. Skrivning afhang af at modellen huskede instruksen i CLAUDE.md. Dette
hook gør det til en default i stedet for en hensigt.

Sådan afgøres det:
  1. Hvilken side handlede sessionen om? Den bedste match fra SessionStart-hookets
     log (`_index/context-hits.jsonl`), og kun hvis scoren er en rigtig navnematch.
  2. Var der noget at fortælle? Kun hvis sessionen faktisk ændrede filer i projektet
     (git-status i den mappe), og sessionen varede over MIN_MINUTES.
  3. Er det allerede skrevet? Højst én note pr. side pr. dag.

Noten er to linjer og skrives med wiki_append, så modsigelsestjek og commit følger med.
Hooket skriver aldrig nye sider og fejler altid stille — det må ikke blokere Claude.

Test manuelt (--dry-run siger hvilken port der lukkede, hvis den ikke skriver):
  echo '{"cwd":"C:/Projects/Egne/et-projekt"}' | python scripts/wiki-session-note.py --dry-run
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

WIKI = Path(__file__).resolve().parent.parent
LOG = WIKI / "_index" / "context-hits.jsonl"
STAMP = WIKI / "_index" / "session-notes.json"
MIN_SCORE = 8          # navne- eller aliasmatch, ikke bare et beskrivelses-hit
MIN_MINUTES = 10
MAX_FILES = 12

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass


def latest_hit(cwd: str):
    """Den seneste kørsel fra dette projekt, hvis den fandt en rigtig side."""
    if not LOG.exists():
        return None
    best = None
    try:
        for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if Path(str(r.get("cwd", ""))).resolve() != Path(cwd).resolve():
                continue
            if not r.get("hits"):
                continue
            slug, score = r["hits"][0]
            if score >= MIN_SCORE:
                best = (r, slug)
    except Exception:
        return None
    return best


def changed_files(cwd: str) -> list[str]:
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=cwd,
                           capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            return []
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                             capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        root = Path(top.stdout.strip()) if top.returncode == 0 else Path(cwd)
        here = Path(cwd).resolve()
        out = []
        for line in r.stdout.splitlines():
            rel = line[3:].strip().strip('"')
            if not rel:
                continue
            # I et faelles parent-repo ville alle andre projekters aendringer ellers
            # blive talt med her og give en note om en side sessionen aldrig roerte.
            try:
                if (root / rel).resolve().is_relative_to(here):
                    out.append(rel)
            except Exception:
                continue
        return out[:MAX_FILES]
    except Exception:
        return []


def already_written(slug: str) -> bool:
    today = dt.date.today().isoformat()
    try:
        data = json.loads(STAMP.read_text(encoding="utf-8")) if STAMP.exists() else {}
    except Exception:
        data = {}
    if data.get(slug) == today:
        return True
    data[slug] = today
    try:
        STAMP.parent.mkdir(exist_ok=True)
        STAMP.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return False


def main() -> int:
    dry = "--dry-run" in sys.argv
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()

    def stop(hvorfor: str) -> int:
        # Hooket skal fejle stille i drift, men et --dry-run uden begrundelse er
        # umuligt at skelne fra et hook der er gaaet i stykker. Fem tavse returns
        # gav praecis den tvivl, saa dry-run siger nu hvilken port der lukkede.
        if dry:
            print(f"[dry-run] skriver ikke: {hvorfor}")
        return 0

    if Path(cwd).resolve() == WIKI.resolve():
        return stop("kaldt inde i selve vaulten — der skrives direkte")

    hit = latest_hit(cwd)
    if not hit:
        return stop(f"ingen navnematch for {Path(cwd).name!r} i {LOG.name} "
                    f"(kraever score >= {MIN_SCORE})")
    rec, slug = hit

    started = dt.datetime.fromisoformat(rec["ts"])
    minutes = (dt.datetime.now() - started).total_seconds() / 60
    if minutes < MIN_MINUTES and not dry:
        return stop(f"sessionen varede {minutes:.0f} min, graensen er {MIN_MINUTES}")

    files = changed_files(cwd)
    if not files:
        return stop(f"ingen aendrede filer i {Path(cwd).name} — intet at fortaelle")

    if already_written(slug) and not dry:
        return stop(f"der er allerede skrevet en note til [[{slug}]] i dag")

    today = dt.date.today()
    months = ["januar", "februar", "marts", "april", "maj", "juni", "juli",
              "august", "september", "oktober", "november", "december"]
    shown = ", ".join(f"`{f}`" for f in files[:4])
    more = f" (+{len(files) - 4} flere)" if len(files) > 4 else ""
    note = (f"- **{today.day}. {months[today.month - 1]} {today.year} — arbejdssession:** "
            f"{len(files)} filer ændret i {Path(cwd).name}: {shown}{more}.\n"
            f"  Noteret automatisk ved sessionens afslutning; uddyb hvis der blev truffet en beslutning.")

    if dry:
        print(f"[dry-run] ville skrive til [[{slug}]] efter {minutes:.0f} min:\n{note}")
        return 0

    try:
        import importlib.util
        os.environ.setdefault("WIKI_ROOT", str(WIKI))
        os.environ.setdefault("WIKI_EMBED", "0")
        spec = importlib.util.spec_from_file_location("srv", WIKI / "scripts" / "wiki-mcp-server.py")
        srv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(srv)
        res = srv.wiki_append(slug, note, section="Aktivitet", source=f"session {today.isoformat()}")
        if isinstance(res, dict) and res.get("ok"):
            print(json.dumps({"systemMessage": f"Sessionsnote skrevet til wikien: {slug}"}))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
