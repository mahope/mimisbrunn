#!/usr/bin/env python3
"""
Provenance-backfill via git blame (issue #51).

Sider uden `sources:` og uden en eneste `[kilde:]`-markør kan ikke efterprøves. Git
ved dog hvornår hvert afsnit kom ind og med hvilken commit-besked, og ingest-commits
nævner deres kilde ("wiki-agent: auto-ingest emails 2026-08-02"). Scriptet udleder
derfor en kildemarkør pr. side og skriver den ind — konservativt:

- Kan kilden udledes entydigt af commit-beskeden, bruges den.
- Ellers skrives `[kilde: git <sha> <dato>]`, som i det mindste er et spor.
- `confidence` hæves aldrig. En udledt kilde er svagere end en oplyst.

Historikken i dette repo har været igennem rebases, så resultatet er best-effort.

Brug:
  python scripts/wiki-provenance-backfill.py            # vis hvad der ville ske
  python scripts/wiki-provenance-backfill.py --apply
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

SOURCE_MARK = re.compile(r"\[kilde:|> Kilde:", re.I)
FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)

# Commit-beskeder der afsloerer hvor indholdet kom fra.
ORIGINS = [
    (re.compile(r"auto-ingest emails", re.I), "ingest af Hostinger-mail"),
    (re.compile(r"auto-ingest from Gmail", re.I), "ingest af Gmail"),
    (re.compile(r"email export", re.I), "mail-eksport"),
    (re.compile(r"inbox-triage", re.I), "capture via _inbox"),
    (re.compile(r"tech intel", re.I), "Tech Intel-scanner"),
    (re.compile(r"knowledge radar", re.I), "Knowledge Radar"),
    (re.compile(r"weekly reflect", re.I), "Weekly Reflect"),
    (re.compile(r"opkald|samtale|m\wde", re.I), "samtale"),
]

# Den oprindelige import fra Mahope Notes-vaulten. Halvdelen af de kildeloese sider
# stammer derfra, og "git <sha>" siger mindre end hvad committen faktisk var.
FIRST_IMPORT = ("0a84fd97", "oprindelig import fra Mahope Notes-vaulten")


def git(*args, cwd=ROOT):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=60)


def origin_of(rel: str):
    """(sha, dato, beskrivelse) for den commit der tilfoejede mest af siden."""
    r = git("log", "--follow", "--format=%h|%ad|%s", "--date=short", "--", rel)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
    # aeldste commit er sidst: det er der siden blev oprettet
    sha, date, subject = lines[-1].split("|", 2)
    if sha.startswith(FIRST_IMPORT[0]):
        return sha, date, FIRST_IMPORT[1]
    for pat, label in ORIGINS:
        if pat.search(subject):
            return sha, date, label
    return sha, date, ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Udled kildemarkører fra git-historikken")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=50)
    a = ap.parse_args()

    todo = []
    for path in sorted((ROOT / "entities").glob("*/*.md")):
        raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        m = FM_RE.match(raw)
        if not m:
            continue
        fm, body = m.group(1), raw[m.end():]
        if re.search(r"^generated:\s*true", fm, re.M) or re.search(r"^type:\s*answer", fm, re.M):
            continue
        has_sources = re.search(r"^sources:\s*\n\s+- \S", fm, re.M)
        if has_sources or SOURCE_MARK.search(body):
            continue
        todo.append((path, fm, body))

    if not todo:
        print("Alle sider har enten sources: eller en kildemarkør.")
        return 0

    print(f"{len(todo)} sider uden provenance:\n")
    written = 0
    for path, fm, body in todo[: a.limit]:
        rel = path.relative_to(ROOT).as_posix()
        got = origin_of(rel)
        if not got:
            print(f"  {path.stem:34} ingen git-historik — springes over")
            continue
        sha, date, label = got
        mark = f"> Kilde: {label} ({date}) [git {sha}]" if label else f"> Kilde: git {sha} ({date})"
        print(f"  {path.stem:34} {mark}")
        if a.apply:
            new_body = body.rstrip("\n") + f"\n\n{mark}\n"
            path.write_text("---\n" + fm + "\n---\n" + new_body, encoding="utf-8", newline="\n")
            written += 1

    if a.apply:
        print(f"\nSkrevet på {written} sider. `confidence` er ikke rørt: en udledt kilde er svagere "
              f"end en oplyst.")
    else:
        print("\nKør med --apply for at skrive markørerne ind.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
