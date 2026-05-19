#!/usr/bin/env python3
"""Check client websites for uptime and basic health."""
import os, re, yaml, json
import urllib.request
from datetime import date
from pathlib import Path

wiki = Path("/wiki")
clients_dir = wiki / "entities" / "clients"

def extract_frontmatter(content):
    if not content.startswith("---"):
        return {}
    try:
        end = content.index("---", 3)
        return yaml.safe_load(content[3:end].strip()) or {}
    except Exception:
        return {}

def check_url(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WikiAgent/1.0"})
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, str(e)
    except Exception as e:
        return 0, str(e)

results = []

for f in sorted(clients_dir.glob("*.md")):
    try:
        content = f.read_text(encoding="utf-8")
        fm = extract_frontmatter(content)

        urls = re.findall(r'https?://[^\s\)>\]]+', content)
        client_urls = [u for u in urls if not u.startswith("https://github.com")
                       and "facebook.com" not in u and "linkedin.com" not in u
                       and "mahope" not in u and "_sources" not in u]

        if not client_urls:
            continue

        url = client_urls[0].rstrip("/.,;:")
        status, error = check_url(url)

        results.append({
            "client": fm.get("entity", f.stem),
            "file": f.name,
            "url": url,
            "status": status,
            "error": error,
            "ok": 200 <= status < 400
        })
    except Exception:
        pass

report = [
    "---",
    "title: Client Health Check",
    f"date: {date.today().isoformat()}",
    "---",
    "",
    f"# Client Website Health Check — {date.today().isoformat()}",
    "",
    f"> {len(results)} sites checked",
    "",
]

ok = [r for r in results if r["ok"]]
down = [r for r in results if not r["ok"]]

if down:
    report.append("## Sites med problemer")
    report.append("")
    for r in down:
        report.append(f"- **[[{r['file'].replace('.md','')}|{r['client']}]]** — {r['url']} — Status: {r['status']} {r['error'] or ''}")
    report.append("")

report.append(f"## Sunde sites ({len(ok)})")
report.append("")
for r in ok:
    report.append(f"- [[{r['file'].replace('.md','')}|{r['client']}]] — {r['url']} — {r['status']}")

(wiki / "_health-check.md").write_text("\n".join(report), encoding="utf-8")

print(f"Health check: {len(ok)} ok, {len(down)} issues")
for r in down:
    print(f"  DOWN: {r['client']} — {r['url']} — {r['status']} {r['error']}")
