#!/usr/bin/env python3
"""
Retrieval-eval for wiki_search (recall@k + MRR) mod scripts/eval/queries.yaml.
Kør før/efter ændringer i ranking:  python scripts/retrieval-eval.py [--mode rrf|bm25|weighted] [--k 5]
"""
import argparse, importlib.util, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("wiki_mcp_server", os.path.join(ROOT, "scripts", "wiki-mcp-server.py"))
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="rrf", choices=["rrf", "bm25", "weighted", "semantic"])
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    queries = yaml.safe_load(open(os.path.join(ROOT, "scripts", "eval", "queries.yaml"), encoding="utf-8"))
    srv._refresh(force=True)
    # Byg den semantiske lane faerdig foer foerste query, ellers svarer den [] i
    # starten og tallene bliver ikke-deterministiske (issue #27).
    if a.mode in ("rrf", "semantic") and not srv._EMB_DISABLED:
        srv._emb_refresh()
    hits = 0; rr = 0.0; misses = []
    for q in queries:
        res = srv.wiki_search(q["q"], limit=a.k, mode=a.mode)
        slugs = [r["slug"] for r in res]
        rank = next((i for i, s in enumerate(slugs) if s in q["expect"]), None)
        if rank is not None:
            hits += 1; rr += 1.0 / (rank + 1)
        else:
            misses.append((q["q"], q["expect"], slugs[:3]))
        if a.verbose:
            print(f"{'OK ' if rank is not None else 'MISS'} {q['q']!r:40} -> {slugs[:3]}")
    n = len(queries)
    print(f"mode={a.mode} k={a.k} queries={n} recall@{a.k}={hits/n:.2f} MRR={rr/n:.2f}")
    for q, exp, got in misses:
        print(f"  MISS {q!r}: forventede {exp}, fik {got}")


if __name__ == "__main__":
    main()
