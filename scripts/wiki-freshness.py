#!/usr/bin/env python3
"""
Freshness- og frontmatter-lint for wikien (supplerer wiki-lint.py, som dækker links).

Tjek:
  1. Frontmatter: påkrævede felter, type/mappe-match, gyldige datoer, description-længde, YAML-fejl.
  2. Staleness pr. type: `stale_after:` i frontmatter, ellers default pr. type
     (project 60 dage, client 180, person/place/recipe 365, tool/concept aldrig; status archived/parkeret m.fl. fritager).
  3. Freshness-disciplin ("timeless / dated / pointer", jf. obsidian-second-brain/OKF):
     linjer med foranderlige værdier (kr/DKK/%, versionsnumre, "kører på", IP-adresser)
     skal have en datomarkør på samme linje: (pr. YYYY-MM), [kilde: …], **D. måned YYYY**, YYYY-MM-DD.
  4. Provenance: sider med `sources: []` og ingen inline kildemarkør (samtale/kilde) i brødteksten.

Brug:
    python scripts/wiki-freshness.py            # rapport
    python scripts/wiki-freshness.py --json     # maskinlæsbart (bruges af wiki-mcp-server til nedvægtning)
    python scripts/wiki-freshness.py --stale    # kun forældede sider
Exit 0 altid (rapport, ikke gate).
"""
import collections, datetime as dt, glob, json, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import yaml
try:  # libyaml: ~8x hurtigere frontmatter-parsing (issue #19)
    from yaml import CSafeLoader as _YamlLoader
except ImportError:  # pragma: no cover
    from yaml import SafeLoader as _YamlLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = sorted(glob.glob(os.path.join(ROOT, "entities", "*", "*.md")))
TODAY = dt.date.today()
REQ = ["entity", "type", "description", "sources", "confidence", "created", "last_updated", "tags"]
FOLDER_TYPE = {"people": "person", "projects": "project", "clients": "client", "tools": "tool",
               "places": "place", "concepts": "concept", "recipes": "recipe", "_hubs": "concept"}
STALE_DEFAULT_DAYS = {"client": 180, "project": 60, "person": 365, "place": 365, "recipe": 365}
FRESHNESS_TYPES = {"client", "project", "tool", "person"}
ARCHIVED_STATUS = {"archived", "arkiveret", "afsluttet", "done", "completed", "inaktiv", "inactive", "lukket", "closed", "parkeret", "paused", "tidligere-kunde", "tabt", "lost"}

# Foranderlige værdier
MUTABLE_RE = re.compile(
    r"(\d[\d\.\s]*\s?(kr|dkk|%|€|eur|usd|\$)\b"          # beløb/procent
    r"|\bv?\d+\.\d+(\.\d+)?\b"                            # versionsnumre
    r"|\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"           # IP
    r"|\bkører (på|hos|i)\b|\bhostes (på|hos)\b|\bnuværende\b|\bpt\.|\bp\.t\.)", re.I)
DATED_RE = re.compile(
    r"(\(pr\. ?\d{4}-\d{2}|\(pr\. ?\d{1,2}/\d{1,2}|\[kilde:|\bkilde:|\d{4}-\d{2}-\d{2}|\*\*\d{1,2}\.\s?\w+ \d{4}"
    r"|\b\d{1,2}/\d{1,2}-\d{4}|\b(jan|feb|mar|apr|maj|jun|jul|aug|sep|okt|nov|dec)\w* \d{4}|\bsamtale \d{4}|\bverificeret\b)", re.I)
SOURCE_MARK_RE = re.compile(r"(\[kilde:|> Kilde:|\bsamtale \d{4}-\d{2}-\d{2}|_sources/)", re.I)
CODE_RE = re.compile(r"```.*?```", re.S)


def parse(path):
    raw = open(path, encoding="utf-8-sig").read().replace("\r\n", "\n")
    m = re.match(r"---\n(.*?)\n---\n", raw, re.S)
    if not m:
        return None, raw, "no-frontmatter"
    try:
        fm = yaml.load(m.group(1), Loader=_YamlLoader) or {}
    except Exception as e:
        return None, raw[m.end():], f"yaml-error: {str(e).splitlines()[0][:80]}"
    return (fm if isinstance(fm, dict) else {}), raw[m.end():], None


def to_date(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v):
        return dt.date.fromisoformat(v[:10])
    return None


def check_all():
    issues = collections.defaultdict(list)
    stale = []
    freshness = []
    provenance = []
    for path in FILES:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        folder = os.path.basename(os.path.dirname(path))
        fm, body, err = parse(path)
        if err:
            issues[err.split(":")[0]].append(f"{rel}: {err}")
            continue
        if fm.get("type") == "redirect":
            continue
        for k in REQ:
            if k not in fm:
                issues[f"missing-{k}"].append(rel)
        t = fm.get("type")
        if t == "redirect":
            continue
        if t and FOLDER_TYPE.get(folder) != t:
            issues["type-folder-mismatch"].append(f"{rel}: type={t}")
        for k in ("created", "last_updated", "stale_after"):
            if k in fm and to_date(fm[k]) is None:
                issues[f"bad-date-{k}"].append(f"{rel}: {fm[k]!r}")
        if fm.get("confidence") not in ("high", "medium", "low", "stated"):
            issues["bad-confidence"].append(f"{rel}: {fm.get('confidence')!r}")
        d = fm.get("description")
        if isinstance(d, str) and len(d) > 220:
            issues["description-too-long"].append(f"{rel}: {len(d)}")
        # staleness
        lu = to_date(fm.get("last_updated"))
        limit = to_date(fm.get("stale_after"))
        status = str(fm.get("status", "")).lower()
        if status in ARCHIVED_STATUS:
            limit = None  # afsluttede/arkiverede sider forældes ikke
        elif limit is None and lu is not None and t in STALE_DEFAULT_DAYS:
            limit = lu + dt.timedelta(days=STALE_DEFAULT_DAYS[t])
        if limit is not None and TODAY > limit:
            stale.append((rel, t, str(lu), (TODAY - limit).days))
        # freshness discipline (kun prosa, ikke kode; kun brødtekst; kun typer hvor værdier reelt forældes)
        for i, line in enumerate(CODE_RE.sub("", body).split("\n"), 1) if t in FRESHNESS_TYPES else []:
            s = line.strip()
            if not s or s.startswith(("#", ">", "|", "-  [", "[kilde")):
                continue
            if MUTABLE_RE.search(s) and not DATED_RE.search(s):
                freshness.append((rel, i, s[:110]))
        # provenance. Genererede sider (hubs) har ingen kilder at have, og svar-sider
        # baerer deres kilder i `cites:` i stedet (issue #51).
        src = fm.get("sources")
        generated = bool(fm.get("generated"))
        is_answer = str(fm.get("type", "")) == "answer" and fm.get("cites")
        if (src in (None, [], "")) and not SOURCE_MARK_RE.search(body)                 and not generated and not is_answer:
            provenance.append(rel)
    return issues, stale, freshness, provenance


def main():
    flag = sys.argv[1] if len(sys.argv) > 1 else "--all"
    issues, stale, freshness, provenance = check_all()
    if flag == "--json":
        print(json.dumps({"stale": [s[0] for s in stale], "freshness_lines": len(freshness),
                          "provenance_missing": provenance,
                          "issues": {k: len(v) for k, v in issues.items()}}, ensure_ascii=False))
        return
    print(f"# Wiki freshness — {len(FILES)} sider, {TODAY}\n")
    if flag in ("--all", "--frontmatter"):
        total = sum(len(v) for v in issues.values())
        print(f"## Frontmatter: {total} problemer")
        for k, v in sorted(issues.items(), key=lambda kv: -len(kv[1])):
            print(f"  {k}: {len(v)}")
            for x in v[:8]:
                print(f"    {x}")
        print()
    if flag in ("--all", "--stale"):
        print(f"## Forældede sider (stale_after eller type-default overskredet): {len(stale)}")
        by = collections.Counter(s[1] for s in stale)
        print("  pr. type: " + ", ".join(f"{k}={v}" for k, v in by.items()))
        for rel, t, lu, over in sorted(stale, key=lambda s: -s[3])[:40]:
            print(f"  [{over:>4}d over] {rel} (last_updated {lu})")
        print()
    if flag in ("--all", "--freshness"):
        by_file = collections.Counter(f[0] for f in freshness)
        print(f"## Udaterede foranderlige værdier: {len(freshness)} linjer i {len(by_file)} sider")
        print("  (beløb/procent/versioner/IP/'kører på' uden datomarkør på linjen — skriv '(pr. YYYY-MM)' eller [kilde: …])")
        for rel, n in by_file.most_common(25):
            print(f"  {n:>3}  {rel}")
        print()
    if flag in ("--all", "--provenance"):
        print(f"## Uden kilde: {len(provenance)} sider har sources: [] og ingen kildemarkør i teksten")
        for rel in provenance[:30]:
            print(f"  {rel}")
        print()


if __name__ == "__main__":
    main()
