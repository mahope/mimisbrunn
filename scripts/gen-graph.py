#!/usr/bin/env python3
"""Generate wiki relationship graph data + analysis report."""
import re, yaml, json
from pathlib import Path
from collections import defaultdict

wiki = Path(__file__).resolve().parent.parent
entities_dir = wiki / "entities"

# --- Build graph ---
nodes = {}
edges = []
edge_set = set()

all_files = list(entities_dir.rglob("*.md"))

# First pass: collect all nodes
for f in all_files:
    try:
        content = f.read_text(encoding="utf-8")
        fm = {}
        if content.startswith("---"):
            end = content.index("---", 3)
            fm = yaml.safe_load(content[3:end].strip()) or {}

        stem = f.stem
        nodes[stem] = {
            "id": stem,
            "entity": fm.get("entity", stem),
            "type": fm.get("type", "unknown"),
            "confidence": fm.get("confidence", "unknown"),
            "category": f.parent.name,
            "links_out": 0,
            "links_in": 0,
            "words": len(content.split()),
        }
    except Exception:
        pass

# Second pass: collect edges
for f in all_files:
    try:
        content = f.read_text(encoding="utf-8")
        source = f.stem
        links = re.findall(r'\[\[([^\|\]]+)', content)

        seen_targets = set()
        for link in links:
            target = link.lower().strip()
            if target == source.lower():
                continue
            if target in seen_targets:
                continue
            seen_targets.add(target)

            # Find matching node
            target_node = None
            for nid in nodes:
                if nid.lower() == target:
                    target_node = nid
                    break

            if target_node:
                edge_key = (source, target_node)
                if edge_key not in edge_set:
                    edges.append({"source": source, "target": target_node})
                    edge_set.add(edge_key)
                    nodes[source]["links_out"] += 1
                    nodes[target_node]["links_in"] += 1
    except Exception:
        pass

# --- Analysis ---
node_list = list(nodes.values())
node_list.sort(key=lambda n: n["links_in"] + n["links_out"], reverse=True)

# Most connected
most_connected = node_list[:20]

# Orphans (0 incoming)
orphans = [n for n in node_list if n["links_in"] == 0]

# Isolated (0 incoming AND 0 outgoing)
isolated = [n for n in node_list if n["links_in"] == 0 and n["links_out"] == 0]

# Hubs (high incoming, connect many things)
hubs = sorted(node_list, key=lambda n: n["links_in"], reverse=True)[:15]

# Bridges (high outgoing, reference many things)
bridges = sorted(node_list, key=lambda n: n["links_out"], reverse=True)[:15]

# Type distribution
type_connections = defaultdict(lambda: {"nodes": 0, "avg_in": 0, "avg_out": 0, "total_in": 0, "total_out": 0})
for n in node_list:
    t = n["type"]
    type_connections[t]["nodes"] += 1
    type_connections[t]["total_in"] += n["links_in"]
    type_connections[t]["total_out"] += n["links_out"]
for t in type_connections:
    tc = type_connections[t]
    if tc["nodes"]:
        tc["avg_in"] = tc["total_in"] / tc["nodes"]
        tc["avg_out"] = tc["total_out"] / tc["nodes"]

# Cross-type edge analysis
cross_type = defaultdict(int)
for e in edges:
    src_type = nodes.get(e["source"], {}).get("type", "?")
    tgt_type = nodes.get(e["target"], {}).get("type", "?")
    key = f"{src_type} -> {tgt_type}"
    cross_type[key] += 1
cross_type_sorted = sorted(cross_type.items(), key=lambda x: x[1], reverse=True)

# --- Save JSON ---
graph_data = {
    "nodes": [{"id": n["id"], "entity": n["entity"], "type": n["type"],
               "confidence": n["confidence"], "links_in": n["links_in"],
               "links_out": n["links_out"]} for n in node_list],
    "edges": edges,
    "stats": {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "orphans": len(orphans),
        "isolated": len(isolated),
        "avg_connections": sum(n["links_in"] + n["links_out"] for n in node_list) / len(node_list) if node_list else 0,
    }
}
(wiki / "_graph.json").write_text(json.dumps(graph_data, ensure_ascii=False, indent=2), encoding="utf-8")

# --- Generate report ---
report = f"""---
title: Wiki Graph Analysis
date: {__import__('datetime').date.today().isoformat()}
description: Analyse af relationer og forbindelser i wiki-grafen
---

# Wiki Graph Analysis

> {len(nodes)} noder, {len(edges)} unikke forbindelser

## Oversigt

| Metric | Vaerdi |
|--------|--------|
| Noder (entities) | {len(nodes)} |
| Kanter (forbindelser) | {len(edges)} |
| Gns. forbindelser per entity | {graph_data['stats']['avg_connections']:.1f} |
| Orphans (ingen indgaaende) | {len(orphans)} |
| Isolerede (ingen forbindelser) | {len(isolated)} |

## Top 20 mest forbundne entities

| Entity | Type | Ind | Ud | Total |
|--------|------|-----|----|-------|
"""

for n in most_connected:
    report += f"| [[{n['id']}|{n['entity']}]] | {n['type']} | {n['links_in']} | {n['links_out']} | {n['links_in']+n['links_out']} |\n"

report += f"""
## Top 15 hubs (flest indgaaende links)

Disse entities refereres oftest fra andre sider — de er wikiens "knudepunkter".

| Entity | Type | Indgaaende |
|--------|------|------------|
"""
for n in hubs:
    report += f"| [[{n['id']}|{n['entity']}]] | {n['type']} | {n['links_in']} |\n"

report += f"""
## Top 15 bridges (flest udgaaende links)

Disse sider linker til flest andre entities — de er wikiens "broer" og oversigter.

| Entity | Type | Udgaaende |
|--------|------|-----------|
"""
for n in bridges:
    report += f"| [[{n['id']}|{n['entity']}]] | {n['type']} | {n['links_out']} |\n"

report += f"""
## Forbindelser per type

| Type | Entities | Gns. ind | Gns. ud |
|------|----------|----------|---------|
"""
for t in ["client", "person", "project", "tool", "concept", "place", "recipe"]:
    tc = type_connections.get(t, {})
    if tc.get("nodes"):
        report += f"| {t} | {tc['nodes']} | {tc['avg_in']:.1f} | {tc['avg_out']:.1f} |\n"

report += f"""
## Top kryds-type forbindelser

Viser hvilke entity-typer der oftest linker til hinanden.

| Forbindelse | Antal |
|-------------|-------|
"""
for key, count in cross_type_sorted[:15]:
    report += f"| {key} | {count} |\n"

report += f"""
## Orphans ({len(orphans)} entities uden indgaaende links)

Disse sider er "usynlige" i grafen — ingen andre sider linker til dem.

"""
for n in sorted(orphans, key=lambda x: x["type"]):
    report += f"- [[{n['id']}|{n['entity']}]] ({n['type']})\n"

if isolated:
    report += f"""
## Isolerede ({len(isolated)} entities uden nogen forbindelser)

Disse sider hverken linker til eller linkes fra andre sider.

"""
    for n in isolated:
        report += f"- [[{n['id']}|{n['entity']}]] ({n['type']})\n"

(wiki / "_graph-analysis.md").write_text(report, encoding="utf-8")

print(f"Graph: {len(nodes)} nodes, {len(edges)} edges")
print(f"  Avg connections: {graph_data['stats']['avg_connections']:.1f}")
print(f"  Orphans: {len(orphans)}, Isolated: {len(isolated)}")
print(f"  Most connected: {most_connected[0]['entity']} ({most_connected[0]['links_in']+most_connected[0]['links_out']} links)")
print(f"Saved: _graph.json + _graph-analysis.md")
