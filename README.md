<p align="center">
  <img src="https://raw.githubusercontent.com/mahope/mimisbrunn/main/docs/mark.svg" width="72" alt="">
</p>

<h1 align="center">Mimisbrunn</h1>

<p align="center"><strong>A second brain that grows itself.</strong><br>
Markdown vault + Claude Code + MCP. Your AI ingests, links, cites and answers — from every device.</p>

<p align="center">
  <a href="https://wiki-mcp.mahoje.dk">Docs &amp; demo</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#mcp-server">MCP</a> ·
  <a href="#capture-from-anywhere">Capture</a> ·
  <a href="#secrets-stay-out">Secrets</a> ·
  <a href="#why-mimisbrunn">The name</a>
</p>

<p align="center">
  <img alt="MIT" src="https://img.shields.io/badge/license-MIT-C9A054?style=flat-square">
  <img alt="Claude Code" src="https://img.shields.io/badge/Claude%20Code-skills%20%2B%20hooks-0B1220?style=flat-square">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-9%20tools-0B1220?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-0B1220?style=flat-square">
  <img alt="No database" src="https://img.shields.io/badge/databases-0-6BA98E?style=flat-square">
  <img alt="Secret scanning" src="https://img.shields.io/badge/CI-gitleaks%20%2B%20trivy-6BA98E?style=flat-square">
</p>

---

```
You:    "Just talked to Sarah from Acme about a React redesign, 40k budget, kickoff in October"

Brain:  ✓ updated [[acme-corp]] — new project: React redesign (40.000, kickoff 2026-10)
        ✓ created [[sarah-jones]] — contact at Acme, source: conversation 2026-09-06
        ✓ linked [[react]] · committed  wiki: append acme-corp

You:    /wiki-query what did we promise Acme?
Brain:  Redesign proposal by 15 Sep, staging on Vercel, weekly status mail.
        entities/clients/acme-corp.md#Aftaler · confidence: medium
```

Mimisbrunn is the [LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) taken to production: one markdown file per entity, YAML frontmatter that drives recall, `[[wikilinks]]` for relations, git as the database, and Claude Code as the librarian. It has run a real freelance business's memory since spring 2026 — 900+ pages, daily ingest, zero databases.

## Why this one

| Most "AI second brains" | Mimisbrunn |
|---|---|
| Notes app + chat window | Plain markdown you own, in Obsidian or any editor |
| Vector DB you have to run | SQLite FTS5 + optional local embeddings, rebuilt from the files |
| Facts overwrite each other | Contradictions become callouts and a review queue; nothing is deleted, merges leave redirects |
| "Trust me" search | A query set and `retrieval-eval.py` report recall@5 / MRR before and after every ranking change |
| A patch quietly deletes half the server | `selftest.py` asserts the exact tool and prompt surface on every push; a missing function is a red build, not a surprise a week later |
| Works in one app | MCP server: Claude Code, Claude app on your phone, claude.ai, any agent |
| Grows until it rots | Freshness lint by type, `stale_after`, archived status, weekly reflect pass |
| Secrets end up in git | A pre-commit hook blocks known key formats, and CI runs gitleaks and trivy on every push |

## What you get

- **Typed entities** — `people`, `clients`, `projects`, `tools`, `concepts`, `places`, `recipes`; each page has a one-sentence `description`, `sources`, `confidence`, `created`, `last_updated`, `tags`, optional `resource` and `stale_after`.
- **9 Claude Code skills** — `/wiki-save`, `/wiki-query`, `/wiki-ingest`, `/wiki-auto-ingest`, `/wiki-lint`, `/wiki-review`, `/wiki-learn`, `/wiki-handover`, `/wiki-resume` — plus `/wiki-import` for ChatGPT, Claude, LinkedIn, Facebook, Google Takeout and Notion exports.
- **MCP server** — `scripts/wiki-mcp-server.py`: search (3 lanes, RRF-fused), outline, get (per section), related (links + semantic neighbours), recent, handover, stats, append (with contradiction check), create.
- **Two hooks** — `wiki-context.py` injects critical facts and the pages matching the project you open; `wiki-autocommit.py` commits only the file you changed and never leaves a broken rebase.
- **Quality tooling** — `wiki-lint.py` (dead links, orphans, duplicate slugs), `wiki-freshness.py` (frontmatter, stale pages, undated prices/versions, missing provenance), `wiki-merge.py` (merge with redirect stub, `--candidates`), `retrieval-eval.py`, `answer-eval.py`, `selftest.py`, `completeness-score.py`, `gen-dashboard.py`, `gen-graph.py`, generated hub pages.
- **Security** — `.githooks/pre-commit` refuses staged Resend, GitHub, OpenAI, AWS, Slack, Google and Stripe keys and private key blocks; `.github/workflows/security.yml` runs gitleaks over the full history and the working tree, plus trivy for vulnerabilities and secrets, on every push and weekly.
- **Cloud routines (templates)** — email ingest, Gmail ingest, tech-intel scanner, weekly digest, lint + calendar enrichment, knowledge radar, pre-meeting brief, inbox triage, weekly reflect.
- **Deploy templates** — `deploy/wiki-agent/` (cron: email export, health checks, briefings), `deploy/wiki-mcp/` (MCP over HTTPS with a Bearer token, landing page), `deploy/wiki-inbox/` (Telegram capture bot).

## Quick start

```bash
git clone https://github.com/mahope/mimisbrunn.git my-brain
cd my-brain
git config core.hooksPath .githooks        # blocks secrets before they reach git
claude
> /wiki-setup                              # name your brain, set your role and stack, seed first entities
```

Open the folder as a vault in Obsidian (optional). From now on, any Claude Code session in this folder reads and writes the brain: mention a client, it updates; run `/wiki-learn` before `/compact`, nothing is lost.

### Serve it to Claude everywhere

```bash
pip install "mcp>=1.12,<2" pyyaml fastembed          # fastembed is optional: enables the semantic lane
claude mcp add wiki -s user -- python /path/to/my-brain/scripts/wiki-mcp-server.py
```

Remote (phone, claude.ai, other agents): deploy `deploy/wiki-mcp/` with Docker, then

```bash
claude mcp add --transport http wiki-remote https://YOUR-DOMAIN/mcp --header "Authorization: Bearer <token>"
```

See [`deploy/wiki-mcp/SETUP.md`](deploy/wiki-mcp/SETUP.md).

## How it works

```
 email · meetings · captures · conversations
                 │
                 ▼  ingest routines: classify · link · cite
        ┌──────────────────┐
        │     the vault    │  markdown · frontmatter · git
        │ _index · hubs    │  _review-queue · _inbox
        └───────┬──────────┘
                │  lint · freshness · retrieval eval · weekly reflect
                ▼
          MCP server  ──►  Claude Code · Claude app · claude.ai · any agent
```

Every fact is *timeless*, *dated* (`(as of 2026-09, source)`) or a *pointer* to the page that owns it. Conversations write back with `> Source: conversation YYYY-MM-DD`; files write back with `[source: _sources/…]`.

## MCP server

| Tool | What it does |
|---|---|
| `wiki_search(query, type?, limit?, mode?)` | BM25 (SQLite FTS5) + weighted term match + local embeddings, fused with reciprocal rank fusion. Stale pages weigh less, redirects are hidden. Compact hits with `path`. |
| `wiki_outline(slug)` | Frontmatter head + every `##` section with first line and length. |
| `wiki_get(slug, section?)` | Whole page or a single section. Cite as `path#heading`. |
| `wiki_related(slug)` | Outbound, inbound, dead links, semantic neighbours. |
| `wiki_recent(days)` | Pages by `last_updated`. |
| `wiki_handover()` | Latest task handover. |
| `wiki_stats()` | Pages per type, dirty files, last commits. |
| `wiki_append(slug, text, section?, source?)` | Add knowledge; deterministic contradiction check (email, phone, price, version, contact, hosting) → callout + `_review-queue.md`. Commits. |
| `wiki_create(type, slug, entity, description, body, …)` | New page by the schema; refuses duplicates and secrets. |

Search quality is measured, not assumed: `python scripts/retrieval-eval.py --mode rrf` runs `scripts/eval/queries.yaml` and prints recall@5 and MRR. Add a query every time a real search misses.

Speed is measured too. On a 900-page vault, single core:

| | |
|---|---|
| Full re-parse of every page | 181 ms |
| `wiki_search`, term-match lane | 7.4 ms (p50) |
| `wiki_search`, BM25 lane | 6.7 ms (p50) |
| Incremental embedding update, one changed page | 30 ms |

Frontmatter is parsed with libyaml, the lowercase fields every query needs are computed once at load, and generated hub pages are kept out of both indexes so they never crowd out a real answer.

## Capture from anywhere

- **Mail** — create an alias like `brain@yourdomain` that delivers to your inbox; the inbox-triage routine files each mail on the right page or parks it in `_review-queue.md`. It never invents new pages.
- **Telegram** — `deploy/wiki-inbox/`: text, photos and voice memos (transcribed with faster-whisper) become `_inbox/` notes, committed instantly.
- **Conversations** — `/wiki-save` and the auto-save triggers in `CLAUDE.md`.
- **Exports** — `/wiki-import` for ChatGPT, Claude, LinkedIn, Facebook, Google Takeout, Notion.

## Keeping it honest

```bash
python scripts/wiki-lint.py            # dead links, orphans, duplicate slugs/aliases
python scripts/wiki-freshness.py       # frontmatter, stale pages per type, undated values, missing sources
python scripts/retrieval-eval.py       # recall@5 / MRR of wiki_search
python scripts/answer-eval.py          # groundedness and abstention of the whole tool chain
python scripts/selftest.py             # 21 invariants of the MCP tool surface (seconds, no network)
python scripts/wiki-merge.py A B --dry-run   # merge two pages, leave a redirect stub
python scripts/regen-index.py          # _index.md + hub pages
```

The Sunday **reflect** routine rewrites only `## Resumé` sections marked `<!-- @generated -->`, proposes merges and archiving, and mails you the report. It never merges or deletes on its own.

## Repository layout

```
entities/          one folder per type, one file per entity; _hubs/ is generated
_sources/          raw inputs (gitignored except what you choose to keep)
_inbox/            captures waiting for triage
scripts/           MCP server, lint, freshness, merge, eval, index, dashboard, graph
.claude/commands/  the /wiki-* skills
deploy/            wiki-agent (cron), wiki-mcp (MCP over HTTPS), wiki-inbox (Telegram)
docs/              automation setup, landing page
_schema.md         the rules — read this first
```

## Automation

`docs/automation-setup.md` covers the Claude Code hooks, the cloud routine templates (Claude Pro/Max) and the Dokploy services. Everything is optional; the vault works with nothing but Claude Code.

## Secrets stay out

A second brain reads your mail, your invoices and your servers, so the interesting question is not what it stores but what leaks. Three layers, none of them clever:

1. **The schema forbids it.** Passwords, API keys and invoice amounts never go in a page. Pages point at the password manager instead.
2. **The pre-commit hook blocks it.** `git config core.hooksPath .githooks` once, and staged changes containing a Resend, GitHub, OpenAI, AWS, Slack, Google or Stripe key, or a private key block, are refused before they reach a commit.
3. **CI catches what slipped through.** gitleaks scans the full history and the working tree, trivy scans dependencies and files; both fail the build.

A separate `quality` workflow runs `selftest.py` on every push. It builds the index and asserts that exactly the fourteen tools and four prompts are registered, that `ctx` never leaks into `wiki_create`'s public schema, and that the write guards still refuse secrets, uncited answers and unknown sources. The content checks skip themselves in an empty vault, so the template and a real vault run the same test.

The remote MCP server matches its Bearer token in constant time, exposes only `{"ok":true}` on the unauthenticated health endpoint, and passes its git credentials through a helper that reads the environment at call time, so no token is ever written into `.git/config` inside the container.

## Why "Mimisbrunn"

In Norse myth, **Mímisbrunnr** — Mímir's well — lies beneath one of the three roots of Yggdrasil, the world tree. It is the well of wisdom and memory; Mímir, its keeper, is the wisest of all beings. Odin wanted a drink from it and paid the price the well demanded: one of his eyes. Later, when Mímir was beheaded, Odin preserved the head with herbs and spoke to it whenever he needed counsel. The head kept answering.

Almost every part of that story maps onto what this project is trying to be:

- **A well, not a warehouse.** Wisdom in the myth is something you draw from, again and again, not something you pile up. A second brain that is only written to and never queried is a warehouse. Mimisbrunn is built around the query: search lanes, an eval set, hooks that pull the right pages into every session.
- **Under the root.** The well sits at the root of the tree that holds everything else up. This vault is meant to sit under your work the same way: the place your agents, routines and future sessions all reach into before they act.
- **Mímir keeps it.** The well has a keeper who knows what is in it. Here the keeper is Claude Code with a schema and rules: it ingests, links, cites, flags contradictions and refuses to invent. The files stay yours; the keeper does the maintenance.
- **The price is real.** Odin's eye is the honest part of the myth. Every second brain that survives has a cost of upkeep. Mimisbrunn tries to make that price small and explicit — lint, freshness, review queue, a weekly reflect pass — instead of pretending it is zero.
- **The head still speaks.** Knowledge preserved with care keeps answering long after the conversation that produced it. That is why nothing is deleted, merges leave redirects, every fact carries a source and a date, and handovers let a new session pick up where the last one stopped.

Also: it is short, it is not "brain" or "wiki" or "AI", and it is a Danish developer's project — the old Norse name felt more honest than another English SaaS-sounding one.

## Credits

Built by [Mads Holst Jensen](https://mahoje.dk) with Claude Code. Inspired by Karpathy's LLM-wiki gist, [andreasvig/second-brain-starter-kit](https://github.com/andreasvig/second-brain-starter-kit), [eugeniughelbur/obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain) and [basicmachines-co/basic-memory](https://github.com/basicmachines-co/basic-memory). MIT.
