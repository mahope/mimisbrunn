#!/usr/bin/env python3
"""
Målescript for wikiens varme veje.

Landing page og README har hidtil påstået tal ("7 ms median, 181 ms til at
genlæse vaulten") som stammede fra en enkelt kørsel før sektions-BM25-banen kom
til. Påstande om hastighed skal kunne genkøres, ellers rådner de. Dette script
måler de veje en model faktisk rammer, med percentiler i stedet for gennemsnit —
en median på 7 ms betyder intet hvis p95 er et sekund.

Embeddings er slået fra som standard (`WIKI_EMBED=0`), fordi den semantiske bane
kræver en model på disken og dermed ikke kan måles ens to steder. Kør med
`--embed` for at tage den med, når modellen er hentet.

Brug:
  python scripts/bench.py
  python scripts/bench.py --runs 50 --embed
  python scripts/bench.py --json          # maskinlæsbart, til at sammenligne to commits
"""
import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("WIKI_ROOT", str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

# Blandede forespørgsler: korte navneopslag, flerords-spørgsmål og noget der intet rammer.
QUERIES = [
    "hetzner",
    "hetzner server pris",
    "hvem hoster en-kunde",
    "dokploy compose redeploy bygger ikke",
    "resend api",
    "hvad aftalte jeg med john",
    "priser og ydelser",
    "wordpress plugin gdpr",
    "zzz findes slet ikke i vaulten",
]


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    i = min(len(xs) - 1, int(round((p / 100) * (len(xs) - 1))))
    return xs[i]


def timed(fn, runs: int) -> list[float]:
    out = []
    for _ in range(runs):
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return out


def report(name: str, ms: list[float], extra: str = "") -> dict:
    row = {
        "navn": name,
        "n": len(ms),
        "p50": round(statistics.median(ms), 2),
        "p95": round(pct(ms, 95), 2),
        "max": round(max(ms), 2),
    }
    print(f"  {name:<38} p50 {row['p50']:>8.2f} ms   p95 {row['p95']:>8.2f} ms   "
          f"max {row['max']:>8.2f} ms{('   ' + extra) if extra else ''}")
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=30, help="gentagelser pr. måling")
    ap.add_argument("--embed", action="store_true", help="tag den semantiske bane med")
    ap.add_argument("--json", action="store_true", help="skriv rå tal som JSON")
    args = ap.parse_args()

    os.environ["WIKI_EMBED"] = "1" if args.embed else "0"

    spec = importlib.util.spec_from_file_location("srv", ROOT / "scripts" / "wiki-mcp-server.py")
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)

    results: dict[str, object] = {"embed": args.embed, "runs": args.runs, "målinger": []}

    def add(row):
        results["målinger"].append(row)

    print("Indeksering")
    t = time.perf_counter()
    srv._refresh(force=True)
    cold = (time.perf_counter() - t) * 1000
    pages = len(srv._INDEX)
    results["sider"] = pages
    print(f"  {'koldt indeks (force)':<38} {cold:>11.2f} ms   {pages} sider")
    results["koldt_indeks_ms"] = round(cold, 2)

    # Varm refresh: intet er ændret, så den skal koste et mtime-sweep og intet andet.
    add(report("varm refresh (intet ændret)", timed(lambda: srv._refresh(), args.runs)))

    print("\nSøgning")
    # Første søgning bygger sektions-FTS dovent; hold den ude af tallene.
    srv.wiki_search("opvarmning", limit=5)
    alle: list[float] = []
    for q in QUERIES:
        ms = timed(lambda q=q: srv.wiki_search(q, limit=8), args.runs)
        alle += ms
        hits = len(srv.wiki_search(q, limit=8))
        add(report(f"wiki_search {q[:26]!r}", ms, f"{hits} hits"))
    add(report("wiki_search (alle forespørgsler)", alle))

    print("\nHentning")
    slug = sorted(srv._INDEX)[0]
    stor = max(srv._INDEX.values(), key=lambda p: len(p.body)).slug
    add(report("wiki_get (første side)", timed(lambda: srv.wiki_get(slug), args.runs)))
    add(report("wiki_get (største side)", timed(lambda: srv.wiki_get(stor), args.runs),
               f"{len(srv._INDEX[stor].body)} tegn"))
    add(report("wiki_outline (største side)", timed(lambda: srv.wiki_outline(stor), args.runs)))
    add(report("wiki_related (første side)", timed(lambda: srv.wiki_related(slug), args.runs)))

    print("\nAggregater")
    add(report("wiki_brief", timed(lambda: srv.wiki_brief(), args.runs)))
    add(report("wiki_commitments", timed(lambda: srv.wiki_commitments(), args.runs)))
    add(report("wiki_graph (hele grafen)", timed(lambda: srv.wiki_graph(), args.runs)))
    add(report("wiki_recent", timed(lambda: srv.wiki_recent(), args.runs)))
    add(report("wiki_stats", timed(lambda: srv.wiki_stats(), args.runs)))

    if args.json:
        print("\n" + json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
