#!/usr/bin/env python3
"""Generate wiki dashboard with health score, key metrics, and recent activity."""
import re, yaml, json, subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import defaultdict

wiki = Path(__file__).resolve().parent.parent
entities_dir = wiki / "entities"
today = date.today()

# --- Helpers ---
def extract_frontmatter(content):
    if not content.startswith("---"):
        return {}
    try:
        end = content.index("---", 3)
        return yaml.safe_load(content[3:end].strip()) or {}
    except Exception:
        return {}

def parse_date(s):
    try:
        parts = str(s).split(" ")[0].split("T")[0].split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None

# --- Scan all entities ---
categories = defaultdict(int)
confidence_counts = defaultdict(int)
total_words = 0
total_links = 0
orphan_count = 0
stale_count = 0
recently_updated = []
all_files = list(entities_dir.rglob("*.md"))

# Build incoming link map
incoming = defaultdict(int)
for f in all_files:
    try:
        content = f.read_text(encoding="utf-8")
        for link in re.findall(r'\[\[([^\|\]]+)', content):
            incoming[link.lower()] += 1
    except Exception:
        pass

for f in all_files:
    try:
        content = f.read_text(encoding="utf-8")
        fm = extract_frontmatter(content)
        etype = fm.get("type", "unknown")
        conf = fm.get("confidence", "unknown")
        lu = parse_date(fm.get("last_updated", ""))

        categories[etype] += 1
        confidence_counts[conf] += 1
        total_words += len(content.split())
        total_links += len(re.findall(r'\[\[[^\]]+\]\]', content))

        stem_lower = f.stem.lower()
        entity_lower = (fm.get("entity", "") or "").lower()
        if incoming.get(stem_lower, 0) == 0 and incoming.get(entity_lower, 0) == 0:
            orphan_count += 1

        if lu:
            days_old = (today - lu).days
            if days_old > 90:
                stale_count += 1
            recently_updated.append((lu, fm.get("entity", f.stem), f.stem, etype))
    except Exception:
        pass

recently_updated.sort(reverse=True)
total_entities = len(all_files)

# --- Load completeness scores ---
scores_file = wiki / "_completeness-scores.json"
avg_completeness = 0
if scores_file.exists():
    try:
        scores = json.loads(scores_file.read_text(encoding="utf-8"))
        avg_completeness = sum(s.get("score", 0) for s in scores) / len(scores) if scores else 0
    except Exception:
        pass

# --- Health Score ---
high_pct = confidence_counts.get("high", 0) / total_entities if total_entities else 0
orphan_pct = orphan_count / total_entities if total_entities else 0
stale_pct = stale_count / total_entities if total_entities else 0
completeness_norm = avg_completeness / 100

# Recent activity: how many entities updated in last 14 days?
recent_14d = sum(1 for lu, _, _, _ in recently_updated if (today - lu).days <= 14)
activity_pct = min(recent_14d / 20, 1.0)  # 20 updates in 14 days = 100%

health = int(
    high_pct * 25 +
    (1 - orphan_pct) * 15 +
    (1 - stale_pct) * 10 +
    completeness_norm * 30 +
    activity_pct * 20
)
health = max(0, min(100, health))

# Health bar
filled = health // 4
empty = 25 - filled
bar = "█" * filled + "░" * empty

# --- Git recent commits ---
git_log = ""
try:
    result = subprocess.run(
        ["git", "-C", str(wiki), "log", "--oneline", "-10", "--format=%h %s (%ar)"],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    git_log = result.stdout.strip()
except Exception:
    git_log = "(git log utilgaengelig)"

# --- Auto-ingest state ---
ingest_state = {}
state_file = wiki / "_auto-ingest-state.json"
if state_file.exists():
    try:
        ingest_state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        pass

# --- Generate dashboard ---
cat_rows = []
for t in ["client", "person", "project", "tool", "concept", "place", "recipe"]:
    if categories[t]:
        cat_rows.append(f"| {t} | {categories[t]} |")

conf_rows = []
for c in ["high", "medium", "low"]:
    if confidence_counts[c]:
        pct = confidence_counts[c] / total_entities * 100
        conf_rows.append(f"| {c} | {confidence_counts[c]} | {pct:.0f}% |")

recent_rows = []
for lu, name, stem, etype in recently_updated[:10]:
    recent_rows.append(f"| [[{stem}|{name}]] | {etype} | {lu.isoformat()} |")

dashboard = f"""---
title: Wiki Dashboard
description: Auto-genereret overblik over wiki-sundhed og aktivitet
date: {today.isoformat()}
---

# Wiki Dashboard

> Auto-genereret {today.isoformat()} af `scripts/gen-dashboard.py`

## Health Score

```
{bar} {health}/100
```

| Komponent | Score | Vaegt |
|-----------|-------|-------|
| Confidence high | {high_pct*100:.0f}% | x25 |
| Ingen orphans | {(1-orphan_pct)*100:.0f}% | x15 |
| Ikke stale | {(1-stale_pct)*100:.0f}% | x10 |
| Completeness | {avg_completeness:.0f}% | x30 |
| Aktivitet (14d) | {activity_pct*100:.0f}% | x20 |

## Noegletal

| Metric | Vaerdi |
|--------|--------|
| Entities total | **{total_entities}** |
| Wikilinks total | {total_links} |
| Ord total | {total_words:,} |
| Orphans | {orphan_count} |
| Stale (>90 dage) | {stale_count} |
| Opdateret seneste 14 dage | {recent_14d} |

## Per type

| Type | Antal |
|------|-------|
{chr(10).join(cat_rows)}

## Confidence-fordeling

| Confidence | Antal | Andel |
|------------|-------|-------|
{chr(10).join(conf_rows)}

## Senest opdaterede (top 10)

| Entitet | Type | Dato |
|---------|------|------|
{chr(10).join(recent_rows)}

## Auto-ingest status

| Felt | Vaerdi |
|------|--------|
| Seneste koersel | {ingest_state.get('last_run', 'aldrig')} |
| Filer ingestet | {ingest_state.get('total_ingested', 0)} |

## Seneste commits

```
{git_log}
```

## Pipeline-status

| Routine | Schedule | Status |
|---------|----------|--------|
| Gmail Ingest | Hverdage 08:00 | Aktiv |
| Hostinger Export | Dagligt 07:00 | Aktiv (lokal) |
| Weekly Lint + Calendar | Soendage 20:00 | Aktiv |
| Weekly Digest | Mandage 07:30 | Aktiv |
| Auto-commit hook | Ved wiki-aendring | Aktiv |
| Auto-push hook | Ved commit | Aktiv |
"""

(wiki / "_dashboard.md").write_text(dashboard, encoding="utf-8")
print(f"Dashboard generated. Health: {health}/100")
print(f"  Entities: {total_entities}, Orphans: {orphan_count}, Stale: {stale_count}")
print(f"  Confidence: high={confidence_counts['high']}, medium={confidence_counts['medium']}, low={confidence_counts['low']}")
print(f"  Completeness avg: {avg_completeness:.0f}%")
