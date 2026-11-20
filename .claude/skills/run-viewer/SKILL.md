---
name: run-viewer
description: Launch the clima-ideas web viewer locally (FastAPI on :8000 + Vite on :5173) with the flood-stations layer built from the data branches, and screenshot a station panel. Use when asked to run the app, see the viewer, or check a flood-layer change in the browser from a fresh Linux container (no data/ directory).
---

# Run the viewer

Verified from a cold container on 2026-11-17 (branch `fm/f23-basins`). A fresh container has no `data/`; this
builds only the `flood-stations` layer. The atmospheric-river layer (`ar-events`, frames) is not built here, so the
bottom timeline reads "Sin serie temporal".

## Launch

From the repo root:

```bash
bash .claude/skills/run-viewer/start.sh                      # layer without AR labels
bash .claude/skills/run-viewer/start.sh "$PWD/data/f23/causes-basins.json"   # with F2.3 labels, if that file exists
```

What it does, and why:

1. Reads `12004/12010/12012.parquet` and `stations.json` from `origin/data/f25-flow` with `git show` (the git index is
   not touched) into `$WORK/flow` (default `${TMPDIR:-/tmp}/clima-viewer`; set `WORK=` to choose).
2. Patches that `stations.json`: it has no `river` or `fetched`, and `clima-nqn flow layer` fails with
   `KeyError: 'fetched'` without them. Rivers as in `reports/02/F2.3.md`; date 2026-11-09 from the data branch README.
3. `clima-nqn flow gev --out $WORK/flow/gev --report $WORK/F2.2.md`: without GEV fits the panel shows no
   return-period curve. `--report` keeps `reports/02/F2.2.md` untouched. Takes about 1–2 minutes.
4. `clima-nqn flow layer --flow-dir ... --gev-dir ... [--causes ...]` writes `data/processed/flood-stations`. Pass
   `--gev-dir` explicitly.
5. Restarts `uvicorn clima_nqn.api.app:app --port 8000` and `pnpm dev --port 5173` (Vite proxies `/api` to :8000),
   then waits for both. Logs: `$WORK/api.log`, `$WORK/web.log`.

The flow in `data/f25-flow` is the published layer, rounded to 0.1 m³/s; GEV values can differ slightly from F2.2.

## Drive and screenshot

```bash
node .claude/skills/run-viewer/shot.cjs 12004 viewer-12004
```

It checks the floods layer, clicks `feature-<id>`, waits for `return-period-curve`, and writes `<prefix>.png` (panel) and
`<prefix>-floods.png` (scrolled to `top-floods`, with "Coincide con AR-…" chips when causes were passed). It prints
the console error count. Look at both images; a missing curve means the GEV step did not run.

Report the port to the user's app (port 5173, name "web") if the session has a preview tool.

## Stop

```bash
pkill -f "uvicorn clima_nqn.api.app:app"; pkill -f "vite --port 5173"
```
