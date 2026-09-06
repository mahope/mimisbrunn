#!/usr/bin/env python3
"""
Flet to wiki-sider deterministisk og efterlad en redirect-stub (issue #10).

    python scripts/wiki-merge.py <kilde-slug> <mål-slug> [--dry-run] [--root DIR]
    python scripts/wiki-merge.py --candidates [--min 0.9]      # find sandsynlige dubletter

Regler:
- Frontmatter på målet: union af aliases/sources/tags; kildens slug + entity bliver aliaser; last_updated = i dag;
  confidence = laveste af de to (high > medium > stated > low).
- Brødtekst: kildens sektioner tilføjes efter målets, hver med markøren `<!-- flettet fra <kilde> YYYY-MM-DD -->`.
  Sektioner med samme heading OG samme tekst tilføjes ikke igen.
- Kildefilen bliver en redirect-stub (`type: redirect`, `redirect_to: <mål>`). Intet slettes.
Exit 1 hvis en af siderne ikke findes.
"""
import argparse, datetime as dt, difflib, glob, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import yaml

CONF_RANK = {"low": 0, "stated": 1, "medium": 2, "high": 3}


def find(root, slug):
    hits = glob.glob(os.path.join(root, "entities", "*", f"{slug}.md"))
    return hits[0] if hits else None


def parse(path):
    raw = open(path, encoding="utf-8-sig").read().replace("\r\n", "\n")
    m = re.match(r"---\n(.*?)\n---\n", raw, re.S)
    if not m:
        raise SystemExit(f"{path}: ingen frontmatter")
    fm = yaml.safe_load(m.group(1)) or {}
    return fm, m.group(1), raw[m.end():]


def sections(body):
    parts = re.split(r"\n(?=## )", "\n" + body)
    out = []
    for part in parts:
        part = part.strip("\n")
        if not part:
            continue
        if part.startswith("## "):
            h, _, rest = part.partition("\n")
            out.append((h[3:].strip(), rest.strip()))
        else:
            out.append(("", part.strip()))
    return out


def fm_set_list(fm_txt, key, values):
    """Sæt en liste-nøgle som inline-liste (aliases/tags) eller blok-liste (sources)."""
    if key == "sources":
        block = "sources:" + ("".join(f"\n  - {v}" for v in values) if values else " []")
    else:
        block = f"{key}: [{', '.join(str(v) for v in values)}]"
    pat = re.compile(rf"^{key}:.*(?:\n  - .*)*", re.M)
    if pat.search(fm_txt):
        return pat.sub(lambda m: block, fm_txt, count=1)
    return fm_txt.rstrip("\n") + "\n" + block


def fm_set(fm_txt, key, value):
    if re.search(rf"^{key}:", fm_txt, re.M):
        return re.sub(rf"^{key}:.*$", f"{key}: {value}", fm_txt, flags=re.M)
    return fm_txt.rstrip("\n") + f"\n{key}: {value}"


def uniq(seq):
    seen = set(); out = []
    for x in seq:
        k = str(x).strip().lower()
        if k and k not in seen:
            seen.add(k); out.append(str(x).strip())
    return out


def merge(root, src_slug, dst_slug, dry_run):
    today = dt.date.today().isoformat()
    src_path, dst_path = find(root, src_slug), find(root, dst_slug)
    if not src_path or not dst_path:
        raise SystemExit(f"Findes ikke: {src_slug if not src_path else dst_slug}")
    sfm, sfm_txt, sbody = parse(src_path)
    dfm, dfm_txt, dbody = parse(dst_path)
    if sfm.get("type") == "redirect":
        raise SystemExit(f"{src_slug} er allerede en redirect")

    aliases = uniq(list(dfm.get("aliases") or []) + [src_slug, str(sfm.get("entity", ""))] + list(sfm.get("aliases") or []))
    aliases = [a for a in aliases if a.lower() != dst_slug.lower() and a.lower() != str(dfm.get("entity", "")).lower()]
    sources = uniq(list(dfm.get("sources") or []) + list(sfm.get("sources") or []))
    tags = uniq(list(dfm.get("tags") or []) + list(sfm.get("tags") or []))
    conf = min([str(dfm.get("confidence", "medium")), str(sfm.get("confidence", "medium"))], key=lambda c: CONF_RANK.get(c, 1))

    new_fm = fm_set_list(dfm_txt, "aliases", aliases)
    new_fm = fm_set_list(new_fm, "sources", sources)
    new_fm = fm_set_list(new_fm, "tags", tags)
    new_fm = fm_set(new_fm, "confidence", conf)
    new_fm = fm_set(new_fm, "last_updated", today)

    existing = {(h.lower(), re.sub(r"\s+", " ", t)) for h, t in sections(dbody)}
    added = []
    for h, t in sections(sbody):
        if not t or (h.lower(), re.sub(r"\s+", " ", t)) in existing:
            continue
        if not h:
            # intro uden overskrift: drop H1-linjen, resten går under "Fra <kilde>"
            t = re.sub(r"^# .*\n?", "", t).strip()
            if not t:
                continue
            h = f"Fra {sfm.get('entity', src_slug)}"
        added.append(f"\n## {h}\n<!-- flettet fra {src_slug} {today} -->\n\n{t}\n")
    new_body = dbody.rstrip("\n") + "\n" + "".join(added) + "\n"

    stub = ("---\n"
            f'entity: "{sfm.get("entity", src_slug)}"\n'
            "type: redirect\n"
            f"redirect_to: {dst_slug}\n"
            f'description: "Flettet ind i {dst_slug} {today}. Se [[{dst_slug}]]."\n'
            f"created: {sfm.get('created', today)}\n"
            f"last_updated: {today}\n"
            "---\n\n"
            f"# {sfm.get('entity', src_slug)} → [[{dst_slug}]]\n\n"
            f"Denne side er flettet ind i [[{dst_slug}]] {today}. Indholdet er bevaret dér (sektioner markeret `flettet fra {src_slug}`).\n")

    print(f"# Flet {src_slug} -> {dst_slug} {'(dry-run)' if dry_run else ''}")
    print(f"  aliases: {aliases}")
    print(f"  sources: {len(sources)}  tags: {tags}  confidence: {conf}")
    print(f"  sektioner tilføjet: {len(added)}: " + ", ".join(re.search(r'## (.*)', a).group(1) for a in added))
    print(f"  {src_path} -> redirect-stub")
    if dry_run:
        return
    open(dst_path, "w", encoding="utf-8", newline="\n").write("---\n" + new_fm + "\n---\n" + new_body)
    open(src_path, "w", encoding="utf-8", newline="\n").write(stub)
    print("  udført. Kør scripts/regen-index.py og scripts/wiki-lint.py bagefter.")


def candidates(root, threshold):
    pages = []
    for f in glob.glob(os.path.join(root, "entities", "*", "*.md")):
        try:
            fm, _, _ = parse(f)
        except SystemExit:
            continue
        if fm.get("type") == "redirect":
            continue
        pages.append((os.path.splitext(os.path.basename(f))[0], str(fm.get("entity", "")).lower(), fm.get("type")))
    out = []
    for i in range(len(pages)):
        for j in range(i + 1, len(pages)):
            a, b = pages[i], pages[j]
            r = max(difflib.SequenceMatcher(None, a[0], b[0]).ratio(), difflib.SequenceMatcher(None, a[1], b[1]).ratio() if a[1] and b[1] else 0)
            if r >= threshold:
                out.append((round(r, 2), a[0], b[0], a[2], b[2]))
    out.sort(reverse=True)
    print(f"# Dublet-kandidater (lighed >= {threshold}): {len(out)}")
    for r, a, b, ta, tb in out[:60]:
        print(f"  {r:.2f}  {a} ({ta})  ~  {b} ({tb})   -> python scripts/wiki-merge.py {a} {b} --dry-run")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?"); ap.add_argument("dst", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--candidates", action="store_true")
    ap.add_argument("--min", type=float, default=0.9)
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    if a.candidates:
        candidates(a.root, a.min)
    elif a.src and a.dst:
        merge(a.root, a.src, a.dst, a.dry_run)
    else:
        ap.print_help()
