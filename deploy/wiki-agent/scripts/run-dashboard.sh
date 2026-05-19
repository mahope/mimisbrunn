#!/bin/bash
# Generate fresh dashboard + completeness scores and push
set -e
source /app/.env.cron

cd /wiki
git pull --rebase origin main || true

python3 scripts/completeness-score.py
python3 scripts/gen-dashboard.py
python3 scripts/gen-graph.py

if git diff --quiet && git diff --cached --quiet; then
    echo "$(date) — Dashboard unchanged."
else
    git add _dashboard.md _completeness-report.md _completeness-scores.json _graph.json _graph-analysis.md _index.md
    git commit -m "wiki-agent: daily dashboard $(date +%Y-%m-%d)"
    git push origin main
    echo "$(date) — Dashboard updated and pushed."
fi
