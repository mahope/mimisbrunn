#!/usr/bin/env python3
"""Score all wiki entities 0-100% based on content quality indicators."""
import re, yaml, json
from pathlib import Path
from collections import defaultdict

wiki = Path(__file__).resolve().parent.parent
entities_dir = wiki / "entities"

def extract_frontmatter(content):
    if not content.startswith("---"):
        return {}
    try:
        end = content.index("---", 3)
        return yaml.safe_load(content[3:end].strip()) or {}
    except Exception:
        return {}

def count_wikilinks_out(content):
    return len(re.findall(r'\[\[[^\]]+\]\]', content))

def count_words(content):
    lines = content.split("\n")
    past_fm = False
    text = []
    for line in lines:
        if line.strip() == "---":
            past_fm = not past_fm
            continue
        if not past_fm:
            text.append(line)
    return len(" ".join(text).split())

def count_sections(content):
    return len(re.findall(r'^##\s+', content, re.MULTILINE))

def has_summary(content):
    lines = content.split("\n")
    past_fm = False
    past_h1 = False
    for line in lines:
        if line.strip() == "---":
            past_fm = not past_fm
            continue
        if past_fm:
            continue
        if line.startswith("# "):
            past_h1 = True
            continue
        if line.startswith("> "):
            continue
        if past_h1 and line.strip() and not line.startswith("#"):
            return len(line.strip()) > 20
    return False

# Build incoming link map
all_files = list(entities_dir.rglob("*.md"))
incoming_links = defaultdict(int)
for f in all_files:
    try:
        content = f.read_text(encoding="utf-8")
        links = re.findall(r'\[\[([^\|\]]+)', content)
        for link in links:
            incoming_links[link.lower()] += 1
    except Exception:
        pass

# Type-specific expected fields
type_fields = {
    "client": ["kontakt", "website", "tech", "faktur", "omsætning"],
    "person": ["rolle", "relation", "kontakt", "email", "telefon"],
    "project": ["status", "tech", "repo", "url", "github"],
    "tool": ["kategori", "brug", "config", "version"],
    "place": ["adresse", "beliggen"],
    "concept": ["definition", "kontekst", "formål"],
    "recipe": ["ingrediens", "fremgangsmåde", "portioner"],
}

results = []
for f in sorted(all_files):
    try:
        content = f.read_text(encoding="utf-8")
        fm = extract_frontmatter(content)
        entity_name = fm.get("entity", f.stem)
        entity_type = fm.get("type", "unknown")
        confidence = fm.get("confidence", "unknown")
        sources = fm.get("sources", [])
        last_updated = fm.get("last_updated", "")

        score = 0

        # 1. Has summary (>1 sentence) — 10 pts
        if has_summary(content):
            score += 10

        # 2. Has sources with ≥1 source — 10 pts
        if sources and len(sources) >= 1:
            score += 10

        # 3. Confidence: high=15, medium=8, low=0
        if confidence == "high":
            score += 15
        elif confidence == "medium":
            score += 8

        # 4. Has ≥3 sections — 10 pts
        if count_sections(content) >= 3:
            score += 10

        # 5. Has ≥3 outgoing wikilinks — 10 pts
        if count_wikilinks_out(content) >= 3:
            score += 10

        # 6. Has ≥1 incoming link — 10 pts
        stem_lower = f.stem.lower()
        if incoming_links.get(stem_lower, 0) >= 1 or incoming_links.get(entity_name.lower(), 0) >= 1:
            score += 10

        # 7. last_updated within 90 days — 10 pts
        if last_updated:
            lu_str = str(last_updated).split(" ")[0].split("T")[0]
            try:
                from datetime import date
                parts = lu_str.split("-")
                lu_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
                days_old = (date.today() - lu_date).days
                if days_old <= 90:
                    score += 10
            except Exception:
                pass

        # 8. Content >200 words — 10 pts
        if count_words(content) > 200:
            score += 10

        # 9. Has ≥2 unique sources — 5 pts
        if sources and len(sources) >= 2:
            score += 5

        # 10. Type-specific fields filled — 10 pts
        content_lower = content.lower()
        expected = type_fields.get(entity_type, [])
        if expected:
            filled = sum(1 for field in expected if field in content_lower)
            ratio = filled / len(expected) if expected else 0
            score += int(ratio * 10)

        results.append({
            "file": str(f.relative_to(wiki)),
            "entity": entity_name,
            "type": entity_type,
            "confidence": confidence,
            "score": score,
            "words": count_words(content),
            "sections": count_sections(content),
            "links_out": count_wikilinks_out(content),
            "links_in": incoming_links.get(stem_lower, 0) + incoming_links.get(entity_name.lower(), 0),
        })
    except Exception as e:
        results.append({"file": str(f.relative_to(wiki)), "entity": f.stem, "score": 0, "error": str(e)})

# Sort by score
results.sort(key=lambda r: r["score"], reverse=True)

# Generate report
excellent = [r for r in results if r["score"] >= 90]
good = [r for r in results if 70 <= r["score"] < 90]
needs_work = [r for r in results if 50 <= r["score"] < 70]
stub = [r for r in results if r["score"] < 50]
avg_score = sum(r["score"] for r in results) / len(results) if results else 0

report = [
    "---",
    "title: Completeness Report",
    f"date: {__import__('datetime').date.today().isoformat()}",
    "description: Auto-genereret kvalitetsrapport for alle wiki-entiteter",
    "---",
    "",
    "# Completeness Report",
    "",
    f"> Genereret {__import__('datetime').date.today().isoformat()} — {len(results)} entiteter scannet",
    "",
    "## Oversigt",
    "",
    f"| Metric | Værdi |",
    f"|--------|-------|",
    f"| Gennemsnit | **{avg_score:.0f}%** |",
    f"| Excellent (90-100%) | {len(excellent)} |",
    f"| Good (70-89%) | {len(good)} |",
    f"| Needs work (50-69%) | {len(needs_work)} |",
    f"| Stub/minimal (<50%) | {len(stub)} |",
    "",
    "## Confidence-fordeling",
    "",
    f"| Confidence | Antal | Gns. score |",
    f"|------------|-------|------------|",
]

for conf in ["high", "medium", "low"]:
    conf_items = [r for r in results if r.get("confidence") == conf]
    if conf_items:
        conf_avg = sum(r["score"] for r in conf_items) / len(conf_items)
        report.append(f"| {conf} | {len(conf_items)} | {conf_avg:.0f}% |")

report.extend([
    "",
    "## Top 20 (højest score)",
    "",
])
for r in results[:20]:
    report.append(f"- [[{Path(r['file']).stem}|{r['entity']}]] — **{r['score']}%** ({r['type']}, {r.get('confidence','?')})")

report.extend([
    "",
    "## Bottom 20 (lavest score — prioritér disse)",
    "",
])
for r in results[-20:]:
    report.append(f"- [[{Path(r['file']).stem}|{r['entity']}]] — **{r['score']}%** ({r['type']}, {r.get('confidence','?')}, {r.get('words',0)} ord)")

report.extend([
    "",
    "## Per type gennemsnit",
    "",
    "| Type | Antal | Gns. score |",
    "|------|-------|------------|",
])
for t in ["client", "person", "project", "tool", "concept", "place", "recipe"]:
    items = [r for r in results if r.get("type") == t]
    if items:
        t_avg = sum(r["score"] for r in items) / len(items)
        report.append(f"| {t} | {len(items)} | {t_avg:.0f}% |")

report.append("")

(wiki / "_completeness-report.md").write_text("\n".join(report), encoding="utf-8")

# Also save raw JSON for other scripts
(wiki / "_completeness-scores.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
)

print(f"Scored {len(results)} entities. Average: {avg_score:.0f}%")
print(f"  Excellent: {len(excellent)}, Good: {len(good)}, Needs work: {len(needs_work)}, Stub: {len(stub)}")
print(f"Report written to _completeness-report.md")
