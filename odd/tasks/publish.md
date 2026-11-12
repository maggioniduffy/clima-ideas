# Feature: publish layers online (F0.11)

Objective: `clima-nqn publish` uploads `data/processed/` and a `layers.json` index to Cloudflare R2; the static web
reads them through `VITE_DATA_URL`. Branch: `fm/f0-11-publish`. Delivery: ask-on-risk. Runners: pytest, vitest.

## Specs

- S1 (F0.11, verbatim from `plan/00-foundations.md`) "Publicar en línea: `clima-nqn publish` sube `data/processed/` y
  un índice `layers.json` a Cloudflare R2; la web se despliega estática y los lee por `VITE_DATA_URL` (decisión del
  usuario, 2026-11-05). El usuario crea el bucket y las claves" — hecho cuando: "Una capa de la fase 1 carga en la web
  publicada + unit del índice".
- S2 (design, assumption) Static objects mirror the API: `GET /layers` → `layers.json`; `GET /layers/{id}` →
  `{id}/manifest.json`; `GET /layers/{id}/data?file=f` → `{id}/{f}` (default `files[0]`);
  `GET /layers/{id}/frames/{t}` → `{id}/frames/{t}.bin`. Only manifest-listed files and frames of layers that list
  `frames/index.json` are uploaded (same rule as `api/app.py`).
- S3 (memory, 2026-11-05) Locally the web keeps using FastAPI via the Vite `/api` proxy when `VITE_DATA_URL` is unset.
- S4 Secrets: R2 keys come from env vars set by the user; never written to the repo or handled by the agent.

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| T1 publish CLI + index | S1, S2, S4 | builder (parallel with T2) | done | RED ImportError; GREEN 10 passed; index uploaded last; suite 264 passed; dry-run 448 objects, 40.92 MB |
| T2 web static mode | S1, S2, S3 | builder (parallel with T1) | done | RED 11/11 fail (missing helpers); GREEN src/api 11 passed, web 166 passed, lint + typecheck clean |
| T3 docs, Makefile, R2 steps | S1, S4 | inline | done | `docs/architecture.md` "Publicación estática"; `make publish`, `make publish-dry` |
| T4 user upload + check published site | S1 | user, then browser pane | pending | |

## Log

- L1 (2026-11-12, user): "pull from main (2 PR recently merged) and continue working"; picked "F0.11 publish" and
  asked "Isn't done that already?" — no: web fetches only `/api`, no publish command or R2 code exists.
- L2: forecast ≈ 450 authored lines (T1 ≈ 250 with tests, T2 ≈ 120, T3 ≈ 80). Risk item 5 (new `boto3` dependency,
  deploy path) → one verifier pass.
- L3 (2026-11-12, user): gave the bucket's S3 endpoint; bucket `nqn-idea`. That endpoint is signed-only, so
  `VITE_DATA_URL` still needs the public `r2.dev` or custom-domain URL. Account ID kept out of the repo.
- L4 (2026-11-12, user): switched to bucket `nqn` (other account). CORS save failed on the placeholder origin;
  suggested `AllowedOrigins: ["*"]` (public read-only data). Public r2.dev URL still pending.
- L5 (2026-11-12, user): public URL `https://pub-89e22e4a31da4ba2bde9dd24522147a9.r2.dev` → `VITE_DATA_URL` in Vercel.
- L6: verifier (item 5): S1–S4 pass, no defects; every web fetch maps to an uploaded key (433 frames, 4 stations, relief). Static build with VITE_DATA_URL ok. Pending: T4 upload and check on the published site.
