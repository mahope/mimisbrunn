#!/usr/bin/env python3
"""Wiki lint — finder REELT brudte wikilinks, orphans og manglende mål.

Resolverer links som Obsidian gør: et link [[X]] eller [[X|label]] er gyldigt
hvis X (case-insensitivt) matcher enten et filnavn (uden .md), en entity-titel
eller et alias i frontmatter. Håndterer tabel-escapede pipes (\\|) korrekt.

Brug:
    python scripts/wiki-lint.py            # fuld rapport
    python scripts/wiki-lint.py --broken   # kun brudte links
    python scripts/wiki-lint.py --orphans  # kun orphans
    python scripts/wiki-lint.py --missing  # kun manglende mål (sorteret efter refs)
    python scripts/wiki-lint.py --dupes    # kun dublet-slugs/aliases (tvetydige [[links]])
"""
import re, glob, os, sys, collections

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = glob.glob(os.path.join(ROOT, "entities", "**", "*.md"), recursive=True)

# Tabel-escapede pipes: gør "\|" til "|" FØR vi parser links, så
# [[centic\|Centic]] læses som [[centic|Centic]] og target=centic.
LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
ALIAS_RE = re.compile(r'aliases:\s*\[([^\]]*)\]')
ENTITY_RE = re.compile(r'entity:\s*"?([^"\n]+?)"?\s*$', re.M)
UPDATED_RE = re.compile(r'last_updated:\s*(\d{4}-\d{2}-\d{2})')

def slug(f):
    return os.path.splitext(os.path.basename(f))[0]

CODE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)

def parse_targets(text):
    # Obsidian linker ikke inde i code spans/blocks — strip dem før parsing.
    text = CODE_RE.sub("", text)
    return [m.strip() for m in LINK_RE.findall(text.replace(r"\|", "|"))]

# Byg resolvable-sæt (lowercase) og indgående-link-tæller
resolvable = set()
file_for = {}          # lowercase resolvable-streng -> path (primært filnavn/titel)
claims = collections.defaultdict(set)  # key -> filer der gør krav på den (dublet-detektion)
for f in FILES:
    s = slug(f)
    resolvable.add(s.lower())
    file_for.setdefault(s.lower(), f)
    claims[s.lower()].add(f)
    # Obsidian resolver også sti-links som [[people/navn]] — registrér sti-varianter (entydige, tæller ikke i claims)
    rel = os.path.relpath(f, ROOT).replace("\\", "/")[:-3].lower()   # entities/people/navn
    resolvable.update({rel, rel.split("/", 1)[1] if "/" in rel else rel})
    file_for.setdefault(rel, f)
    if "/" in rel:
        file_for.setdefault(rel.split("/", 1)[1], f)
    head = open(f, encoding="utf-8").read()[:800]
    em = ENTITY_RE.search(head)
    if em:
        resolvable.add(em.group(1).strip().lower())
        file_for.setdefault(em.group(1).strip().lower(), f)
        claims[em.group(1).strip().lower()].add(f)
    for am in ALIAS_RE.findall(head):
        for a in am.split(","):
            a = a.strip().strip('"').strip("'").lower()
            if a:
                resolvable.add(a)
                file_for.setdefault(a, f)
                claims[a].add(f)

incoming = collections.Counter()
broken = collections.Counter()       # target -> antal refs
broken_src = collections.defaultdict(set)  # target -> filer der refererer
for f in FILES:
    for t in parse_targets(open(f, encoding="utf-8").read()):
        # [[#heading]] er et samme-side-anker -> altid gyldigt.
        if t.startswith("#"):
            continue
        # [[side#heading]] / [[side^block]] resolver til "side".
        base = re.split(r"[#^]", t, maxsplit=1)[0].strip()
        key = base.lower()
        if not key:
            continue
        if key in resolvable:
            incoming[file_for[key]] += 1
        else:
            broken[t] += 1
            broken_src[t].add(os.path.relpath(f, ROOT))

orphans = sorted(slug(f) for f in FILES if incoming[f] == 0)

flag = sys.argv[1] if len(sys.argv) > 1 else "--all"
print(f"# Wiki Lint — {len(FILES)} sider\n")

if flag in ("--all", "--broken", "--missing"):
    print(f"## Manglende mål: {len(broken)} unikke link-mål uden side ({sum(broken.values())} refs)")
    for t, c in broken.most_common(40):
        srcs = ", ".join(sorted(broken_src[t])[:2])
        print(f"  [{c}x] [[{t}]]   <- {srcs}")
    print()

if flag in ("--all", "--orphans"):
    print(f"## Orphans: {len(orphans)} sider uden indgående links")
    for o in orphans[:100]:
        f = file_for.get(o)
        print(f"  {os.path.relpath(f, ROOT) if f else o}")
    print()

if flag in ("--all", "--dupes"):
    dupes = {k: fs for k, fs in claims.items() if len(fs) > 1}
    print(f"## Dublet-slugs/aliases: {len(dupes)} navne gør krav på flere filer (gør [[links]] tvetydige)")
    for k, fs in sorted(dupes.items()):
        print(f"  '{k}': " + " | ".join(os.path.relpath(f, ROOT) for f in sorted(fs)))
    print()
