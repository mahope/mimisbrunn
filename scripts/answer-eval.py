#!/usr/bin/env python3
"""
Answer-quality eval (issue #48).

`retrieval-eval.py` svarer på "kom den rigtige side med i top-5". Det siger intet om
hvorvidt svaret faktisk kan hentes ud, eller om der bliver sagt fra når svaret ikke findes.
Dette script kører hele værktøjskæden som en model ville gøre det — wiki_search, derefter
wiki_outline og wiki_get på de bedste hits — og måler to ting:

  Groundedness: står den ordrette streng fra `must_contain` i den tekst kæden leverede?
                Gør den ikke det, kan et svar kun være gætværk.
  Abstention:   for spørgsmål markeret `unanswerable` skal kæden IKKE levere en side der
                ser ud til at kunne bære et svar. Gør den det, indbyder den til fabrikation.

Ingen model er involveret, så tallene er deterministiske og kan køre i CI. Til en rigtig
dom over formuleringen skriver `--emit-prompts` konteksten ud, så en judge kan score den.

Brug:
  python scripts/answer-eval.py
  python scripts/answer-eval.py --verbose
  python scripts/answer-eval.py --emit-prompts _index/answer-prompts.md
"""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("WIKI_ROOT", str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

import yaml  # noqa: E402

_spec = importlib.util.spec_from_file_location("wiki_mcp_server", ROOT / "scripts" / "wiki-mcp-server.py")
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)

TOP_PAGES = 3          # hvor mange hits kæden går videre med
MAX_SECTIONS = 3       # hvor mange sektioner pr. side den henter
PAGE_CHARS = 12000     # hvor meget af siden der laeses hvis sektionsvalget ikke raekker


def gather(question: str, section_hint: str = "") -> dict:
    """Kør værktøjskæden som en model ville, og mål to trin hver for sig.

    `sections` er hvad progressive disclosure giver: outline, vælg de sektioner der
    ser relevante ud, hent kun dem. `pages` er hvad man får hvis man giver op og
    læser hele siden. Forskellen mellem de to fortæller om outline-trinnet er godt nok.
    """
    hits = srv.wiki_search(question, limit=TOP_PAGES)
    slugs = [h["slug"] for h in hits]
    terms = [t.strip("?.,").lower() for t in question.split() if len(t) > 3]

    sec_chunks, page_chunks = [], []
    for h in hits:
        outline = srv.wiki_outline(h["slug"])
        sections = outline.get("sections") or []
        scored = []
        for s in sections:
            blob = (str(s.get("heading", "")) + " " + str(s.get("first_line", ""))).lower()
            score = sum(1 for t in terms if t in blob)
            if section_hint and str(s.get("heading", "")) == section_hint:
                score += 10
            # wiki_search peger selv paa den bedste sektion (sektions-lanen)
            if h.get("section") and str(s.get("heading", "")) == h["section"]:
                score += 5
            scored.append((score, str(s.get("heading", ""))))
        scored.sort(key=lambda x: -x[0])
        for _, head in scored[:MAX_SECTIONS]:
            got = srv.wiki_get(h["slug"], section=head, max_chars=3000)
            if isinstance(got, dict) and got.get("body"):
                sec_chunks.append(f"### {h['slug']}#{head}\n{got['body']}")
        whole = srv.wiki_get(h["slug"], max_chars=PAGE_CHARS)
        if isinstance(whole, dict) and whole.get("body"):
            page_chunks.append(f"### {h['slug']}\n{whole['body']}")

    return {"slugs": slugs,
            "sections": "\n\n".join(sec_chunks),
            "pages": "\n\n".join(page_chunks)}



def main() -> int:
    ap = argparse.ArgumentParser(description="Answer-quality eval for wikien")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--emit-prompts", default="", help="skriv spørgsmål + kontekst til en fil for en judge")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    cases = yaml.safe_load((ROOT / "scripts" / "eval" / "answers.yaml").read_text(encoding="utf-8"))
    srv._refresh(force=True)
    if not srv._EMB_DISABLED:
        srv._emb_refresh()      # deterministiske tal kræver at den semantiske lane er bygget

    grounded = grounded_total = 0
    abstain_ok = abstain_total = 0
    rows, prompts = [], []

    section_ok = 0
    for c in cases:
        got = gather(c["q"], c.get("section", ""))
        slugs, sec_text, page_text = got["slugs"], got["sections"], got["pages"]
        row = {"q": c["q"], "slugs": slugs, "chars": len(page_text)}
        if c.get("unanswerable"):
            abstain_total += 1
            # Kæden må gerne finde sider; den må bare ikke levere noget der ligner et svar.
            leak = bool(c.get("must_contain")) and c["must_contain"].lower() in page_text.lower()
            row.update({"ok": not leak, "type": "abstention"})
            abstain_ok += 1 if row["ok"] else 0
        else:
            grounded_total += 1
            needle = str(c.get("must_contain", "")).lower()
            found_page = any(s in c["expect"] for s in slugs) if c.get("expect") else True
            in_sections = needle in sec_text.lower() if needle else found_page
            in_pages = needle in page_text.lower() if needle else found_page
            row.update({"ok": bool(in_pages), "type": "groundedness", "page_ok": found_page,
                        "section_ok": bool(in_sections), "needle": c.get("must_contain", "")})
            grounded += 1 if row["ok"] else 0
            section_ok += 1 if in_sections else 0
        rows.append(row)
        if a.emit_prompts:
            prompts.append(f"## {c['q']}\n\n"
                           f"{'(wikien bør IKKE kunne svare på dette)' if c.get('unanswerable') else ''}\n\n"
                           f"{sec_text or page_text or '(ingen kontekst fundet)'}\n")

    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    g = grounded / grounded_total if grounded_total else 0
    ab = abstain_ok / abstain_total if abstain_total else 0
    sec = section_ok / grounded_total if grounded_total else 0
    print(f"groundedness {grounded}/{grounded_total} = {g:.2f}   "
          f"heraf fra sektionsvalg alene {section_ok}/{grounded_total} = {sec:.2f}   "
          f"abstention {abstain_ok}/{abstain_total} = {ab:.2f}   "
          f"({len(cases)} spørgsmål)")
    for r in rows:
        if not r["ok"] or a.verbose:
            mark = "OK  " if r["ok"] else "MISS"
            extra = ""
            if r["type"] == "groundedness" and not r["ok"]:
                extra = f" — fandt ikke {r['needle']!r}" + ("" if r["page_ok"] else " (heller ikke siden)")
            print(f"  {mark} {r['q'][:60]!r} -> {r['slugs'][:3]}{extra}")

    if a.emit_prompts:
        out = ROOT / a.emit_prompts
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("# Answer-eval: kontekst pr. spørgsmål\n\n"
                       "En judge skal for hvert spørgsmål vurdere: kan svaret skrives alene ud fra\n"
                       "konteksten (groundedness), og er det rigtige svar 'det ved jeg ikke' (abstention)?\n\n"
                       + "\n".join(prompts), encoding="utf-8", newline="\n")
        print(f"\nSkrevet kontekst til {a.emit_prompts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
