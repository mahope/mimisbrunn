#!/usr/bin/env python3
"""
PostToolUse-hook (Edit|Write): committer KUN den wiki-fil der lige er ændret.

Erstatter det gamle `git add -A && git commit` som (1) kørte ved enhver
Edit/Write i ethvert projekt, (2) fejede fremmede filer og konfliktmarkører med,
og (3) sammen med `pull --rebase --autostash` efterlod vaulten på detached HEAD
med hængende autostashes (oprydning 2026-09-05).

Adfærd:
- Læser hook-JSON fra stdin; gør intet hvis filen ikke ligger i vaulten,
  ligger i _sources/ eller er en genereret fil.
- Regenererer _index.md når en entitet ændres.
- `git add <fil> _index.md` → commit "wiki: opdatér <slug>".
- Push kun hvis WIKI_AUTOPUSH=1 og arbejdskopien ellers er ren; ved
  rebase-konflikt: abort og log til _sync-errors.log — aldrig efterlad en rebase.
Exit 0 altid (må ikke blokere Claude).
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WIKI = Path(__file__).resolve().parent.parent
SKIP_PREFIXES = ("_sources/", "okf-out/", "strix_runs/", ".git/")
GENERATED = {"_index.md"}


def git(*args, timeout=60):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes"}
    return subprocess.run(["git", *args], cwd=WIKI, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          encoding="utf-8", errors="replace", timeout=timeout, env=env)


def log(msg: str) -> None:
    with open(WIKI / "_sync-errors.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    fp = (payload.get("tool_input") or {}).get("file_path") or (payload.get("tool_response") or {}).get("filePath")
    if not fp:
        return 0
    try:
        rel = Path(fp).resolve().relative_to(WIKI).as_posix()
    except ValueError:
        return 0  # ikke i vaulten
    if rel.startswith(SKIP_PREFIXES) or rel in GENERATED:
        return 0
    if git("rev-parse", "--verify", "REBASE_HEAD").returncode == 0 or (WIKI / ".git" / "rebase-merge").exists():
        log(f"rebase i gang — sprang commit af {rel} over")
        return 0

    paths = [rel]
    if rel.startswith("entities/"):
        subprocess.run([sys.executable, str(WIKI / "scripts" / "regen-index.py")], cwd=WIKI,
                       capture_output=True, timeout=60)
        paths.append("_index.md")
        # regen-index.py skriver ogsaa hub-siderne; uden dem her bliver arbejdskopien
        # permanent dirty, og serverens pull-loop springer pull over (issue #18).
        paths += sorted(p.relative_to(WIKI).as_posix() for p in (WIKI / "entities" / "_hubs").glob("hub-*.md"))
    git("add", "--", *[p for p in paths if (WIKI / p).exists()])
    if git("diff", "--cached", "--quiet").returncode == 0:
        return 0
    slug = Path(rel).stem
    r = git("commit", "-q", "-m", f"wiki: opdatér {slug}")
    if r.returncode != 0:
        log(f"commit fejlede for {rel}: {r.stderr.strip()[:200]}")
        return 0

    if os.environ.get("WIKI_AUTOPUSH") == "1":
        if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
            return 0  # andre lokale ændringer — lad være med at rebase
        pull = git("pull", "--rebase", "-q", "origin", "main", timeout=120)
        if pull.returncode != 0:
            git("rebase", "--abort")
            log(f"pull --rebase fejlede efter {rel}: {pull.stderr.strip()[:200]}")
            return 0
        push = git("push", "-q", "origin", "main", timeout=120)
        if push.returncode != 0:
            log(f"push fejlede efter {rel}: {push.stderr.strip()[:200]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # aldrig blokere Claude
        try:
            log(f"uventet fejl: {e!r}")
        except Exception:
            pass
        sys.exit(0)
