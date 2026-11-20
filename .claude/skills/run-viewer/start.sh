#!/usr/bin/env bash
# Launch the clima-ideas viewer locally with the flood-stations layer built from the data branches.
# Usage: bash .claude/skills/run-viewer/start.sh [causes.json]
# Leaves the API on :8000 and the Vite viewer on :5173 running; logs in $WORK.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
WORK="${WORK:-${TMPDIR:-/tmp}/clima-viewer}"
CAUSES="${1:-}"
mkdir -p "$WORK/flow"
cd "$ROOT"

# 1. Daily flow (published layer, rounded to 0.1 m3/s) from the data branch.
git fetch -q origin data/f25-flow
for f in 12004.parquet 12010.parquet 12012.parquet stations.json; do
  git show "origin/data/f25-flow:$f" > "$WORK/flow/$f"
done

# 2. That stations.json lacks `river` and `fetched`, which `flow layer` needs. Values: rivers as in
#    reports/02/F2.3.md, download date from the data branch README (SNIH fetched 2026-11-09).
python3 - "$WORK/flow/stations.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
rivers = {12004: "Neuquén", 12010: "Agrio", 12012: "Curí Leuvú"}
d.setdefault("fetched", "2026-11-09")
for s in d["stations"]:
    s.setdefault("river", rivers.get(s["id"]))
    s.setdefault("fetched", d["fetched"])
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
PY

# 3. GEV fits (F2.2) into the work dir, so reports/02/F2.2.md is not overwritten; then the layer.
cd "$ROOT/backend"
uv sync --locked -q
uv run clima-nqn flow gev --flow-dir "$WORK/flow" --out "$WORK/flow/gev" --report "$WORK/F2.2.md"
LAYER_ARGS=(--flow-dir "$WORK/flow" --gev-dir "$WORK/flow/gev")
[ -n "$CAUSES" ] && LAYER_ARGS+=(--causes "$CAUSES")
uv run clima-nqn flow layer "${LAYER_ARGS[@]}"

# 4. API (reads data/processed) and viewer (proxies /api to :8000).
pkill -f "uvicorn clima_nqn.api.app:app" 2>/dev/null || true
pkill -f "vite --port 5173" 2>/dev/null || true
nohup uv run uvicorn clima_nqn.api.app:app --port 8000 > "$WORK/api.log" 2>&1 &
cd "$ROOT/web"
pnpm install --frozen-lockfile --silent
nohup pnpm dev --port 5173 > "$WORK/web.log" 2>&1 &
for _ in $(seq 60); do
  curl -sf localhost:8000/health >/dev/null && curl -sf localhost:5173 >/dev/null && break
  sleep 1
done
curl -sf localhost:8000/health >/dev/null || { echo "API did not start, see $WORK/api.log"; exit 1; }
curl -sf localhost:5173 >/dev/null || { echo "viewer did not start, see $WORK/web.log"; exit 1; }
echo "viewer: http://localhost:5173  api: http://localhost:8000  work dir: $WORK"
