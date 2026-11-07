# Fase 0 — Bases

Estado: hecha (F0.2: CI verde en el PR #7, 2026-11-07) · Refs: `docs/architecture.md`, `docs/design.md` (solo F0.3–F0.4), `docs/agents.md`

## Objetivo

Repo listo para que cada etapa solo sume capas: pipeline, API y visor andando con una capa de prueba.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F0.1 | Monorepo: `backend/` (uv, Python 3.12) y `web/` (pnpm, Vite, React, TS); `Makefile`; `data/` en `.gitignore` | Sonnet | `make dev` levanta API y visor |
| F0.2 | CI: ruff, pytest, eslint, tsc, vitest, Playwright | Sonnet | CI verde en un PR |
| F0.3 | Tokens de diseño, tema claro/oscuro, `web/src/i18n/es.ts` | Sonnet | Cambio de tema sin recarga; ningún string fuera de `es.ts` |
| F0.4 | Shell del visor: barra superior, panel de capas, inspector, línea de tiempo, lienzo deck.gl | Sonnet | Layout fijo en ambos temas |
| F0.5 | Relieve como nube de puntos: GLO-30 de Neuquén, submuestreado a binario Float32 | opencode (descarga y proceso) + Sonnet (carga en `PointCloudLayer`) | Relieve visible, < 15 MB |
| F0.6 | FastAPI: `/health`, `/layers`, `/layers/{id}`; validación del manifiesto con pydantic | Sonnet | Unit tests de manifiesto válido e inválido |
| F0.7 | Capa de prueba de punta a punta (manifiesto + datos falsos) | Sonnet | e2e: la capa aparece, se activa e inspecciona |
| F0.8 | Investigación de acceso a datos (lista abajo) → `docs/research/data-access.md` | opencode | Cada ítem con estado, URL y licencia, o "sin verificar" |
| F0.9 | Instalar TECA y correr BARD sobre un año de ERA5 | opencode (largo) | Log y máscara de salida, o el error exacto |
| F0.10 | Índice ENSO compartido: ONI mensual (NOAA CPC) 1950–hoy y fase por mes (Niño ≥ +0,5, Niña ≤ −0,5, Neutro) en `backend/` como única fuente para todas las fases | Sonnet | Parquet + unit: umbrales y fase sobre una serie sintética |

## F0.8: qué investigar

BDHI y AIC (caudales: acceso, resolución, licencia) · lluvia horaria SMN Neuquén Aero y AIC · CAMELS-CL ·
licencias ERA5, IMERG, GEFS, ECMWF open data y AIFS · inventario de aluviones de Neuquén · radar SINARAME en la
provincia · mapas de suelo y cobertura para SCS-CN · fechas y magnitudes de crecidas y aluviones en el norte · índices ENSO (ONI, Niño 3.4, SOI) y pronósticos
ENSO (IRI, C3S) · ECMWF open data y GEFS operativos (latencia, retención) · ERA5T y ERA5-Land (latencia).

## Tests

Unit: manifiesto, carga del relieve, store de tema, fase ENSO. e2e: shell, tema, capa de prueba.

## Abierto

- F0.9 hecha (2026-11-07): run 42296570089 de `.github/workflows/teca.yml` corrió BARD (TECA 6.0.0) sobre ERA5 2023, 6 h,
  hemisferio sur completo (`-10,-180,-80,179.75`), fuente ARCO-ERA5 (CDS rechaza pedidos por cola llena). Salida: 12 archivos
  mensuales, 1460 pasos, artefacto `bard-2023--10_-180_-80_179p75` (vence 2027-02-04). En una caja sobre Neuquén (36–42S,
  68–72O) hay 62 pasos con río atmosférico (prob. > 0.67), casi todos en invierno (jun 24, ago 15, sep 9, jul 6). BARD
  necesita dominio amplio: en la ventana regional `-15,-95,-60,-40` nunca pasa de ~0.39. Para la fase 1: correr en el
  hemisferio y recortar después; BARD tarda ~2,5 h por año en el runner (correr por mes para ver avance).
