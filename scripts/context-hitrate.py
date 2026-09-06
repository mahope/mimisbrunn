#!/usr/bin/env python3
"""
Hvor ofte finder SessionStart-hooket noget? (issue #34)

Læser `_index/context-hits.jsonl`, som `wiki-context.py` skriver én linje til pr.
sessionsstart. Filen er gitignored og lokal.

Brug:
  python scripts/context-hitrate.py            # sidste 4 uger
  python scripts/context-hitrate.py --weeks 12
  python scripts/context-hitrate.py --misses   # mapper der aldrig gav et hit
"""
import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "_index" / "context-hits.jsonl"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass


def load(weeks: int):
    if not LOG.exists():
        return []
    cutoff = dt.datetime.now() - dt.timedelta(weeks=weeks)
    rows = []
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
            if dt.datetime.fromisoformat(r["ts"]) >= cutoff:
                rows.append(r)
        except Exception:
            continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Hit-rate for wiki-context-hooket")
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--misses", action="store_true", help="vis mapper uden hits")
    a = ap.parse_args()

    rows = load(a.weeks)
    if not rows:
        print(f"Ingen målinger i {LOG.relative_to(ROOT).as_posix()} for de sidste {a.weeks} uger.")
        return 0

    by_week = collections.defaultdict(lambda: [0, 0, 0])   # uge -> [kørsler, med hit, stærke hit]
    misses = collections.Counter()
    for r in rows:
        week = dt.datetime.fromisoformat(r["ts"]).strftime("%G-U%V")
        by_week[week][0] += 1
        strong = bool(r.get("hits")) and r["hits"][0][1] >= 8
        if r.get("n_hits"):
            by_week[week][1] += 1
        if strong:
            by_week[week][2] += 1
        else:
            misses[Path(str(r.get("cwd", ""))).name] += 1

    print(f"Kørsler i de sidste {a.weeks} uger: {len(rows)}\n")
    print(f"{'Uge':10} {'Kørsler':>8} {'Med hit':>8} {'Stærkt':>8}  Andel stærke")
    for week in sorted(by_week):
        n, hit, strong = by_week[week]
        print(f"{week:10} {n:8} {hit:8} {strong:8}  {strong / n:.0%}")

    total = len(rows)
    strong_total = sum(v[2] for v in by_week.values())
    print(f"\nSamlet: {strong_total}/{total} kørsler ({strong_total / total:.0%}) fandt en side "
          f"med navne- eller aliasmatch.")

    if a.misses and misses:
        print("\nMapper uden stærkt hit (kandidater til et alias eller en resource-linje):")
        for name, n in misses.most_common(15):
            print(f"  {name:30} {n}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
