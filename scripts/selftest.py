#!/usr/bin/env python3
"""
Selvtest af wikiens værktøjsflade og invarianter.

Baggrund: natten mellem 7. og 8. september slettede en patch femten funktioner fra
MCP-serveren, fordi den erstattede alt mellem to markører. Serveren startede fint,
alle scripts kompilerede, og lint var grøn — fejlen blev først opdaget, fordi
produktionen svarede med tolv værktøjer i stedet for fjorten. Den slags skal en
maskine fange med det samme, ikke et menneske en time senere.

Testen er hurtig (ingen embeddings, ingen netværk) og egner sig til CI.
Værktøjsfladen tjekkes altid; de indholdsafhængige tjek springes over i en tom
vault, så skabelon-repoet (mimisbrunn) kan køre den samme test.

Kør:  python scripts/selftest.py
"""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("WIKI_ROOT", str(ROOT))
os.environ["WIKI_EMBED"] = "0"          # testen må ikke afhænge af modellen

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

EXPECTED_TOOLS = {
    "wiki_search", "wiki_outline", "wiki_get", "wiki_related", "wiki_recent",
    "wiki_handover", "wiki_stats", "wiki_append", "wiki_create",
    "wiki_commitments", "wiki_commit_add", "wiki_brief", "wiki_graph", "wiki_answer",
}
EXPECTED_PROMPTS = {"daily_brief", "before_meeting", "what_did_i_promise", "ingest_source"}

MIN_PAGES = 100          # under dette regnes vaulten som tom (skabelon)

# Attrappen til skrive-værnet samles ved kørsel. Skrives den som ét literal,
# fanger gitleaks testens egen falske nøgle og gør CI rød af den forkerte grund.
FAKE_SECRET = "api_key" + ": " + "abcdefgh" + "12345678"

failures: list[str] = []
checks = 0
skipped = 0


def check(name: str, ok, detail: str = "") -> None:
    """`ok` må gerne være en funktion. Så fanges en manglende funktion som en fejl
    i stedet for at vælte hele testen — præcis det scenarie testen findes for."""
    global checks
    checks += 1
    if callable(ok):
        try:
            ok = ok()
        except Exception as e:
            ok, detail = False, f"{e.__class__.__name__}: {str(e)[:120]}"
    if ok:
        print(f"  OK   {name}")
    else:
        print(f"  FEJL {name}{(' — ' + detail) if detail else ''}")
        failures.append(name)


def skip(name: str, reason: str) -> None:
    global skipped
    skipped += 1
    print(f"  SPR  {name} — {reason}")


def main() -> int:
    spec = importlib.util.spec_from_file_location("srv", ROOT / "scripts" / "wiki-mcp-server.py")
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    srv._refresh(force=True)

    print("Værktøjsflade")
    tools = {t.name for t in asyncio.run(srv.mcp.list_tools())}
    check("alle forventede tools er registreret", EXPECTED_TOOLS <= tools,
          f"mangler {sorted(EXPECTED_TOOLS - tools)}")
    check("ingen uventede tools", tools <= EXPECTED_TOOLS, f"ekstra {sorted(tools - EXPECTED_TOOLS)}")
    prompts = {p.name for p in asyncio.run(srv.mcp.list_prompts())}
    check("alle forventede prompts er registreret", EXPECTED_PROMPTS <= prompts,
          f"mangler {sorted(EXPECTED_PROMPTS - prompts)}")
    create = next((t for t in asyncio.run(srv.mcp.list_tools()) if t.name == "wiki_create"), None)
    check("wiki_create skjuler ctx for kalderen",
          create is not None and "ctx" not in (create.inputSchema.get("properties") or {}))

    print("\nSvar uden indhold")
    check("wiki_commitments svarer", lambda: isinstance(srv.wiki_commitments(), list))
    check("wiki_graph svarer", lambda: "edges" in srv.wiki_graph())
    check("wiki_brief har alle grupper",
          lambda: {"overdue_commitments", "due_soon", "stale_active", "review_queue"} <= set(srv.wiki_brief()))
    check("aftale-parseren læser formatet",
          lambda: srv._parse_commitment(
              "- [ ] (aftalt 2026-09-01, forfald 2026-09-10) Mads → [[x|X]]: noget",
              type("P", (), {"slug": "p", "entity": "P", "path": ROOT / "entities/tools/x.md", "body": ""})()
          ) is not None)
    check("wiki_create afviser ugyldig type", lambda: "error" in srv.wiki_create("ugyldig", "x", "X", "d", "b"))
    check("wiki_answer kræver citater",
          lambda: "error" in srv.wiki_answer("hvad er noget her", "Et svar der er langt nok til at tælle.", []))
    check("wiki_answer afviser ukendte kilder",
          lambda: "error" in srv.wiki_answer("hvad er noget her", "Et svar der er langt nok til at tælle.",
                                             ["entities/tools/findes-ikke-xyz.md"]))

    pages = len(srv._INDEX)
    if pages < MIN_PAGES:
        print(f"\nIndhold — springes over, vaulten har {pages} sider (skabelon)")
        for name in ("indekset har sider", "alias-map er bygget", "redirects følges",
                     "sektions-indekset er bygget", "søgning giver hits", "hits bærer sti",
                     "hits peger på en sektion", "genererede hub-sider er ude af søgningen",
                     "wiki_append afviser hemmeligheder", "wiki_get afviser ugyldig as_of"):
            skip(name, "tom vault")
    else:
        # en rigtig side at teste imod, i stedet for et hårdkodet slug der kan forsvinde
        slug = sorted(srv._INDEX)[0]

        print("\nIndeks")
        check("indekset har sider", pages > MIN_PAGES, f"kun {pages}")
        check("alias-map er bygget", len(srv._ALIAS) > MIN_PAGES, f"kun {len(srv._ALIAS)}")
        check("redirects følges", lambda: srv._resolve(slug) is not None)
        print("\nSøgning")
        hits = srv.wiki_search("hetzner server", limit=5)
        check("søgning giver hits", bool(hits))
        check("hits bærer sti", all("path" in h for h in hits))
        check("hits peger på en sektion", any(h.get("section") for h in hits))
        check("genererede hub-sider er ude af søgningen",
              not any(str(h.get("type")) == "concept" and h["slug"].startswith("hub-") for h in hits))
        # FTS bygges dovent ved første søgning, så dette tjek hører hjemme her
        check("sektions-indekset er bygget",
              lambda: srv._FTS is not None
              and srv._FTS.execute("select count(*) from fts_sec").fetchone()[0] > MIN_PAGES)

        print("\nSkrive-værn")
        check("wiki_append afviser hemmeligheder",
              lambda: "error" in srv.wiki_append(slug, FAKE_SECRET))
        check("wiki_get afviser ugyldig as_of", lambda: "error" in srv.wiki_get(slug, as_of="i går"))

    tail = f" ({skipped} sprunget over)" if skipped else ""
    print(f"\n{checks - len(failures)}/{checks} tjek bestået{tail}")
    if failures:
        print("Fejlede: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
