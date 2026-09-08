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
REDIRECT_RE = re.compile(r"^type:\s*redirect\s*$", re.M)
REDIRECTS = {f for f in FILES if REDIRECT_RE.search(open(f, encoding="utf-8").read()[:600])}

# Tabel-escapede pipes: gør "\|" til "|" FØR vi parser links, så
# [[en-kunde\|En Kunde]] læses som [[en-kunde|En Kunde]] og target=en-kunde.
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

# Svar-sider i entities/answers/ er per definition uden indgaaende links: de arkiverer
# et svar, ikke en entitet. De skal ikke staa som orphans (issue #43).
orphans = sorted(slug(f) for f in FILES
                 if incoming[f] == 0 and f not in REDIRECTS
                 and os.sep + "answers" + os.sep not in f)

# Citater paa svar-sider skal pege paa filer der stadig findes, ellers hviler svaret
# paa en kilde der er vaek.
dead_cites = []
for f in FILES:
    if os.sep + "answers" + os.sep not in f:
        continue
    try:
        txt = open(f, encoding="utf-8-sig").read().replace("\r\n", "\n")
    except Exception:
        continue
    m = re.search(r"^cites:\n((?:  - .+\n)+)", txt, re.M)
    if not m:
        continue
    for line in m.group(1).strip().split("\n"):
        ref = line.strip()[2:].strip().split("#")[0]
        if ref and not os.path.exists(os.path.join(ROOT, ref)):
            dead_cites.append((os.path.relpath(f, ROOT), ref))

flag = sys.argv[1] if len(sys.argv) > 1 else "--all"
print(f"# Wiki Lint — {len(FILES)} sider\n")

if flag in ("--all", "--broken", "--missing"):
    print(f"## Manglende mål: {len(broken)} unikke link-mål uden side ({sum(broken.values())} refs)")
    for t, c in broken.most_common(40):
        srcs = ", ".join(sorted(broken_src[t])[:2])
        print(f"  [{c}x] [[{t}]]   <- {srcs}")
    print()

if flag in ("--all", "--cites"):
    print(f"## Døde citater på svar-sider: {len(dead_cites)}")
    for src_file, ref in dead_cites[:20]:
        print(f"  {src_file} -> {ref}")
    print()

if flag in ("--all", "--orphans"):
    print(f"## Orphans: {len(orphans)} sider uden indgående links")
    for o in orphans[:100]:
        f = file_for.get(o)
        print(f"  {os.path.relpath(f, ROOT) if f else o}")
    print()

if flag in ("--all", "--dupes"):
    dupes = {k: fs for k, fs in claims.items() if len(fs - REDIRECTS) > 1}
    print(f"## Dublet-slugs/aliases: {len(dupes)} navne gør krav på flere filer (gør [[links]] tvetydige)")
    for k, fs in sorted(dupes.items()):
        print(f"  '{k}': " + " | ".join(os.path.relpath(f, ROOT) for f in sorted(fs)))
    print()

# --------------------------------------------------------------------------- .base-visninger
# Obsidian-visningerne i `_bases/` filtrerer paa frontmatter-felter. Bliver et felt omdoebt
# eller aldrig udfyldt, staar visningen tom uden at fejle — og en tom visning ligner
# "der er ikke noget" i stedet for "det virker ikke".
#
# Kun venstresiden af en sammenligning i et `filters`-udtryk tjekkes. Et foerste forsoeg
# laeste alle identifikatorer i filen og meldte visningsnavne, mappestier og ASC som
# manglende felter. En stoejende kontrol er vaerre end ingen.
if flag in ("--all", "--bases"):
    import yaml

    FILTER_LHS = re.compile(r"(?:^|[\s(!])([a-z_][a-z0-9_]*)\s*(?:==|!=|>=|<=|>|<)")

    def _filterudtryk(node, ud):
        """Saml alle streng-udtryk under en filters-node, uanset and/or/not-indlejring."""
        if isinstance(node, str):
            ud.append(node)
        elif isinstance(node, list):
            for x in node:
                _filterudtryk(x, ud)
        elif isinstance(node, dict):
            for v in node.values():
                _filterudtryk(v, ud)

    felt_antal = collections.Counter()
    for f in FILES:
        t = open(f, encoding="utf-8", errors="replace").read().replace("\r\n", "\n")
        if not t.startswith("---"):
            continue
        slut = t.find("\n---", 3)
        if slut < 0:
            continue
        for m in re.finditer(r"^([A-Za-z_][A-Za-z0-9_]*):", t[3:slut], re.M):
            felt_antal[m.group(1)] += 1

    base_dir = os.path.join(ROOT, "_bases")
    fund = []
    # I en tom vault (skabelonen) har intet felt daekning, og tjekket ville melde alt.
    # Samme grund som selftest springer sine indholdstjek over under 100 sider.
    if len(FILES) < 100:
        print("## Base-visninger: springes over, vaulten har "
              f"{len(FILES)} sider (skabelon)\n")
        navne = []
    else:
        navne = sorted(os.listdir(base_dir)) if os.path.isdir(base_dir) else []
    for navn in navne:
        if not navn.endswith(".base"):
            continue
        raw = open(os.path.join(base_dir, navn), encoding="utf-8", errors="replace").read()
        try:
            doc = yaml.safe_load(raw) or {}
        except Exception as e:
            fund.append((navn, "(ugyldig yaml)", e.__class__.__name__))
            continue
        formler = set((doc.get("formulas") or {}).keys())
        udtryk = []
        _filterudtryk(doc.get("filters"), udtryk)
        for v in (doc.get("views") or []):
            _filterudtryk(v.get("filters"), udtryk)
        felter = set()
        for e in udtryk:
            for m in FILTER_LHS.finditer(e):
                n = m.group(1)
                if n not in formler and n != "formula":
                    felter.add(n)
        for n in sorted(felter):
            antal = felt_antal.get(n, 0)
            if antal <= 1:
                fund.append((navn, n, f"{antal} sider har feltet"))

    if len(FILES) >= 100:
        print(f"## Base-visninger der filtrerer paa et felt naesten ingen har: {len(fund)}")
        if fund:
            print("  (visningen staar tom uden at fejle)")
            for navn, felt, note in fund:
                print(f"  {navn:<22} {felt:<22} {note}")
        print()

