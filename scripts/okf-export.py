#!/usr/bin/env python3
"""
OKF-eksport (additiv) — genererer en Open Knowledge Format-konform kopi af wikien
uden at røre kilden. Obsidian-wikien forbliver kanonisk; okf-out/ er derived.

Mapping (jf. _schema.md):
  type       -> type        (OKF's eneste påkrævede felt)
  entity     -> title
  last_updated (el. created) -> timestamp (ISO-8601)
  resource   -> resource
  tags       -> tags
  [[wikilink]] / [[maal|vis]] -> [vis](/entities/kat/maal.md)

Output:
  okf-out/entities/<kat>/<navn>.md   OKF-konforme filer
  okf-out/**/index.md                progressive-disclosure navigation
  okf-out/graph.json                 {nodes, edges}
  okf-out/graph.html                 selvstændig visualizer (ingen backend/CDN)

Kør:  python scripts/okf-export.py
"""
import os, re, json, sys, argparse

# --- visibility og redaction (issue #50) -----------------------------------
# Wikien indeholder kundedata. Uden et filter er "eksportér" og "offentliggør"
# samme knap, og det er ikke en knap man skal kunne trykke paa ved et uheld.
VISIBILITY_ORDER = {"private": 0, "team": 1, "public": 2}

REDACTIONS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}"), "[e-mail fjernet]"),
    (re.compile(r"(?:\+45[\s.]?)?(?:\d{2}[\s.]?){3}\d{2}\b"), "[telefon fjernet]"),
    (re.compile(r"\b\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?\s?(?:kr\.?|DKK|EUR|USD)\b", re.I), "[beløb fjernet]"),
    (re.compile(r"\b\d{4,6}\s?(?:kr\.?|DKK)\b", re.I), "[beløb fjernet]"),
]


def redact(text):
    """Fjerner kontaktoplysninger og beloeb. Fanger IKKE navne — det staar i dokumentationen,
    saa ingen tror en redigeret eksport er anonymiseret."""
    n = 0
    for pat, repl in REDACTIONS:
        text, k = pat.subn(repl, text)
        n += k
    return text, n

_ap = argparse.ArgumentParser(description="OKF-eksport med visibility-filter og redaction")
_ap.add_argument("--visibility", default="private", choices=["private", "team", "public"],
                 help="eksportér kun sider med mindst dette niveau (default private = alt)")
_ap.add_argument("--redact", action="store_true", help="fjern e-mail, telefon og beløb i output")
_ap.add_argument("--out", default="okf-out")
ARGS = _ap.parse_args()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "entities")
OUT = os.path.join(ROOT, ARGS.out)

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def field(fm, name):
    m = re.search(r"^%s:\s*(.+)$" % re.escape(name), fm, re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip().strip('"').strip("'")


def aliases_of(fm):
    m = re.search(r"^aliases:\s*\[(.*?)\]", fm, re.MULTILINE | re.DOTALL)
    if not m:
        return []
    return [a.strip().strip('"').strip("'") for a in m.group(1).split(",") if a.strip()]


def iso(datestr):
    if not datestr:
        return None
    d = datestr.strip().strip('"').strip("'")
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", d)
    return m.group(1) + "T00:00:00Z" if m else None


def norm_keys(s):
    """Kandidat-nøgler for link-opslag (case/space/hyphen-tolerant)."""
    s = s.strip().lower()
    return {s, s.replace(" ", "-"), s.replace("-", " "), s.replace("_", "-")}


# --- 1. Scan alle entiteter, byg opslags-map ---
docs = []          # dicts pr. fil
lookup = {}        # nøgle -> rootrel path

for dirpath, _, files in os.walk(SRC):
    for fn in files:
        if not fn.endswith(".md") or fn.startswith("_"):
            continue
        full = os.path.join(dirpath, fn)
        raw = open(full, encoding="utf-8").read()
        m = FM_RE.match(raw)
        fm = m.group(1) if m else ""
        body = raw[m.end():] if m else raw
        rel = os.path.relpath(full, ROOT).replace(os.sep, "/")     # entities/kat/navn.md
        rootrel = "/" + rel
        stem = fn[:-3]
        title = field(fm, "entity") or stem
        vis = (field(fm, "visibility") or "private").strip().lower()
        if VISIBILITY_ORDER.get(vis, 0) < VISIBILITY_ORDER[ARGS.visibility]:
            continue      # siden er mere privat end det oenskede niveau
        doc = {
            "path": full, "rel": rel, "rootrel": rootrel, "stem": stem,
            "fm": fm, "body": body,
            "title": title,
            "type": field(fm, "type") or "concept",
            "timestamp": iso(field(fm, "last_updated") or field(fm, "created")),
            "resource": field(fm, "resource"),
            "tags": field(fm, "tags"),
            "category": os.path.basename(dirpath),
        }
        docs.append(doc)
        for k in norm_keys(stem) | norm_keys(title):
            lookup.setdefault(k, rootrel)
        for al in aliases_of(fm):
            for k in norm_keys(al):
                lookup.setdefault(k, rootrel)

# --- 2. Konverter links + skriv OKF-filer, saml graf ---
edges = []
resolved = unresolved = 0
missing = {}


def resolve(target):
    for k in norm_keys(target):
        if k in lookup:
            return lookup[k]
    return None


def convert_links(body, src_rootrel):
    global resolved, unresolved
    def repl(mo):
        global resolved, unresolved
        inner = mo.group(1).replace("\\|", "|")   # Obsidian escaper | som \| i tabeller
        tgt, _, disp = inner.partition("|")
        disp = disp.strip() or tgt.strip()
        dest = resolve(tgt)
        if dest:
            resolved += 1
            edges.append((src_rootrel, dest))
            return "[%s](%s)" % (disp, dest)
        unresolved += 1
        missing[tgt.strip().lower()] = missing.get(tgt.strip().lower(), 0) + 1
        return disp   # behold som ren tekst — ingen død link
    return WIKILINK_RE.sub(repl, body)


if os.path.isdir(OUT):
    import shutil
    shutil.rmtree(OUT)

os.makedirs(OUT, exist_ok=True)
if not docs:
    print(f"Ingen sider har visibility >= {ARGS.visibility}. Saet `visibility: public` i frontmatter "
          f"paa de sider der maa deles, og koer igen.")
    raise SystemExit(0)

REDACTED_TOTAL = [0]

for d in docs:
    okf_fm = ["---", "type: %s" % d["type"], "title: %s" % d["title"]]
    if d["timestamp"]:
        okf_fm.append("timestamp: %s" % d["timestamp"])
    if d["resource"]:
        okf_fm.append("resource: %s" % d["resource"])
    if d["tags"]:
        okf_fm.append("tags: %s" % d["tags"])
    # bevar originale ekstra-felter (OKF tillader det) minus dem vi allerede mappede
    for line in d["fm"].splitlines():
        key = line.split(":", 1)[0].strip()
        if key in ("type", "entity", "title", "last_updated", "timestamp", "resource", "tags"):
            continue
        # strip evt. wikilinks i felt-værdier til ren tekst (ingen rå [[..]] i OKF-frontmatter)
        line = WIKILINK_RE.sub(lambda m: (m.group(1).replace("\\|", "|").split("|")[-1]).strip(), line)
        okf_fm.append(line)
    okf_fm.append("---\n")
    body = convert_links(d["body"], d["rootrel"])
    if ARGS.redact:
        body, n = redact(body)
        REDACTED_TOTAL[0] += n
        # Frontmatter laekker ogsaa: description og resource indeholder tit mails.
        redacted_fm = []
        for line in okf_fm:
            if line.startswith(("type:", "title:", "timestamp:", "tags:", "---")):
                redacted_fm.append(line)
                continue
            line, k = redact(line)
            REDACTED_TOTAL[0] += k
            redacted_fm.append(line)
        okf_fm = redacted_fm
    outpath = os.path.join(OUT, d["rel"])
    os.makedirs(os.path.dirname(outpath), exist_ok=True)
    open(outpath, "w", encoding="utf-8").write("\n".join(okf_fm) + body)

# --- 3. index.md pr. mappe (progressive disclosure) ---
by_cat = {}
for d in docs:
    by_cat.setdefault(d["category"], []).append(d)

for cat, items in by_cat.items():
    lines = ["---", "type: index", "title: %s" % cat, "---\n", "# %s\n" % cat]
    for d in sorted(items, key=lambda x: x["title"].lower()):
        lines.append("- [%s](%s) — %s" % (d["title"], d["rootrel"], d["type"]))
    open(os.path.join(OUT, "entities", cat, "index.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")

root_idx = ["---", "type: index", "title: Wiki (OKF-eksport)", "---\n",
            "# Wiki — Open Knowledge Format-eksport\n",
            "Additiv, derived kopi af Obsidian-wikien. Regenerér med `scripts/okf-export.py`.\n",
            "## Kategorier"]
for cat in sorted(by_cat):
    root_idx.append("- [%s](/entities/%s/index.md) — %d entiteter" % (cat, cat, len(by_cat[cat])))
open(os.path.join(OUT, "index.md"), "w", encoding="utf-8").write("\n".join(root_idx) + "\n")

# --- 4. graph.json ---
nodes = [{"id": d["rootrel"], "title": d["title"], "type": d["type"],
          "cat": d["category"], "deg": 0} for d in docs]
node_ix = {n["id"]: n for n in nodes}
uniq_edges = []
seen = set()
for a, b in edges:
    if a == b or (a, b) in seen or a not in node_ix or b not in node_ix:
        continue
    seen.add((a, b))
    uniq_edges.append({"source": a, "target": b})
    node_ix[a]["deg"] += 1
    node_ix[b]["deg"] += 1
graph = {"nodes": nodes, "edges": uniq_edges}
open(os.path.join(OUT, "graph.json"), "w", encoding="utf-8").write(json.dumps(graph, ensure_ascii=False))

# --- 5. graph.html (selvstændig, ingen backend/CDN) ---
HTML = r"""<!doctype html><html lang="da"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wiki-graf (OKF)</title>
<style>
 html,body{margin:0;height:100%;background:#0f1115;color:#e6e6e6;font:13px/1.4 system-ui,sans-serif;overflow:hidden}
 #ui{position:fixed;top:10px;left:10px;z-index:10;background:#1a1d24cc;padding:10px 12px;border-radius:8px;max-width:240px}
 #ui b{font-size:14px}#legend div{display:flex;align-items:center;gap:6px;margin-top:3px}
 #legend i{width:11px;height:11px;border-radius:50%;display:inline-block}
 #q{width:100%;margin-top:8px;padding:5px 7px;border-radius:6px;border:1px solid #333;background:#0f1115;color:#e6e6e6}
 svg{width:100vw;height:100vh;cursor:grab} text{pointer-events:none;fill:#cfd3dc}
 .muted{opacity:.12}
</style></head><body>
<div id="ui"><b>Wiki-graf</b> · <span id="cnt"></span><br>
<input id="q" placeholder="søg entitet…" autocomplete="off">
<div id="legend"></div></div>
<svg id="svg"></svg>
<script>
const DATA = __DATA__;
const COL = {tool:'#4ea1ff',concept:'#b072ff',person:'#ff6fae',project:'#42d392',
 client:'#ffc14e',place:'#38d0c8',recipe:'#ff8a5b',index:'#888'};
const svg=document.getElementById('svg'),NS='http://www.w3.org/2000/svg';
let W=innerWidth,H=innerHeight;
const N=DATA.nodes,E=DATA.edges,byId={};N.forEach(n=>byId[n.id]=n);
document.getElementById('cnt').textContent=N.length+' noder · '+E.length+' links';
// init positioner i cirkel
N.forEach((n,i)=>{const a=i/N.length*6.283;n.x=W/2+Math.cos(a)*300;n.y=H/2+Math.sin(a)*300;n.vx=0;n.vy=0;});
const links=E.map(e=>({s:byId[e.source],t:byId[e.target]})).filter(l=>l.s&&l.t);
// simpel force-sim, faste iterationer
const K=Math.sqrt((W*H)/N.length);
for(let it=0;it<260;it++){
 const rep=K*K*(it<200?1:0.3);
 for(let i=0;i<N.length;i++){let a=N[i];
  for(let j=i+1;j<N.length;j++){let b=N[j];let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy||0.01;
   let f=rep/d2;let d=Math.sqrt(d2);let fx=dx/d*f,fy=dy/d*f;a.vx+=fx;a.vy+=fy;b.vx-=fx;b.vy-=fy;}}
 links.forEach(l=>{let dx=l.t.x-l.s.x,dy=l.t.y-l.s.y,d=Math.sqrt(dx*dx+dy*dy)||0.01;
  let f=(d-K)/d*0.08;let fx=dx*f,fy=dy*f;l.s.vx+=fx;l.s.vy+=fy;l.t.vx-=fx;l.t.vy-=fy;});
 N.forEach(n=>{n.vx+=(W/2-n.x)*0.002;n.vy+=(H/2-n.y)*0.002;n.x+=Math.max(-30,Math.min(30,n.vx));n.y+=Math.max(-30,Math.min(30,n.vy));n.vx*=0.85;n.vy*=0.85;});
}
// tegn
let vb={x:0,y:0,w:W,h:H};
const gLink=document.createElementNS(NS,'g'),gNode=document.createElementNS(NS,'g');
svg.appendChild(gLink);svg.appendChild(gNode);
links.forEach(l=>{const ln=document.createElementNS(NS,'line');ln.setAttribute('x1',l.s.x);ln.setAttribute('y1',l.s.y);
 ln.setAttribute('x2',l.t.x);ln.setAttribute('y2',l.t.y);ln.setAttribute('stroke','#3a3f4b');ln.setAttribute('stroke-width',0.6);
 l.el=ln;gLink.appendChild(ln);});
N.forEach(n=>{const g=document.createElementNS(NS,'g');const c=document.createElementNS(NS,'circle');
 const r=3+Math.min(9,n.deg);c.setAttribute('r',r);c.setAttribute('cx',n.x);c.setAttribute('cy',n.y);
 c.setAttribute('fill',COL[n.type]||'#999');c.setAttribute('stroke','#0f1115');c.setAttribute('stroke-width',1);
 const t=document.createElementNS(NS,'text');t.setAttribute('x',n.x+r+2);t.setAttribute('y',n.y+4);
 t.setAttribute('font-size',10);t.textContent=n.title;t.style.opacity=n.deg>=6?0.7:0;
 g.appendChild(c);g.appendChild(t);n.g=g;n.c=c;n.t=t;gNode.appendChild(g);
 g.addEventListener('mouseenter',()=>{t.style.opacity=1;});
 g.addEventListener('mouseleave',()=>{t.style.opacity=n.deg>=6?0.7:0;});});
function applyVB(){svg.setAttribute('viewBox',vb.x+' '+vb.y+' '+vb.w+' '+vb.h);}applyVB();
// pan+zoom
let drag=null;
svg.addEventListener('mousedown',e=>{drag={x:e.clientX,y:e.clientY};svg.style.cursor='grabbing';});
addEventListener('mouseup',()=>{drag=null;svg.style.cursor='grab';});
addEventListener('mousemove',e=>{if(!drag)return;let k=vb.w/W;vb.x-=(e.clientX-drag.x)*k;vb.y-=(e.clientY-drag.y)*k;drag={x:e.clientX,y:e.clientY};applyVB();});
svg.addEventListener('wheel',e=>{e.preventDefault();let k=e.deltaY>0?1.1:0.9;let mx=vb.x+e.clientX/W*vb.w,my=vb.y+e.clientY/H*vb.h;
 vb.w*=k;vb.h*=k;vb.x=mx-e.clientX/W*vb.w;vb.y=my-e.clientY/H*vb.h;applyVB();},{passive:false});
// søg
document.getElementById('q').addEventListener('input',e=>{const q=e.target.value.toLowerCase();
 N.forEach(n=>{const hit=!q||n.title.toLowerCase().includes(q);n.g.classList.toggle('muted',q&&!hit);
  n.t.style.opacity=(q&&hit)?1:(n.deg>=6?0.7:0);});});
// legende
const L=document.getElementById('legend');[...new Set(N.map(n=>n.type))].sort().forEach(tp=>{
 const d=document.createElement('div');d.innerHTML='<i style="background:'+(COL[tp]||'#999')+'"></i>'+tp;L.appendChild(d);});
</script></body></html>"""
open(os.path.join(OUT, "graph.html"), "w", encoding="utf-8").write(HTML.replace("__DATA__", json.dumps(graph, ensure_ascii=False)))

# --- 6. rapport ---
print("OKF-eksport færdig -> %s" % OUT)
print("  entiteter:      %d" % len(docs))
print("  links:          %d resolved, %d unresolved" % (resolved, unresolved))
print("  graf:           %d noder, %d edges" % (len(nodes), len(uniq_edges)))
print("  kategorier:     %s" % ", ".join("%s(%d)" % (c, len(v)) for c, v in sorted(by_cat.items())))
if missing:
    top = sorted(missing.items(), key=lambda x: -x[1])[:8]
    print("  top uresolvede: %s" % ", ".join("%s x%d" % (k, v) for k, v in top))

print(f"OKF-eksport: {len(docs)} sider til {os.path.relpath(OUT, ROOT)} "
      f"(visibility >= {ARGS.visibility}" + (f", {REDACTED_TOTAL[0]} redigeringer" if ARGS.redact else "") + ")")
