# Fase 0 — Bases

Estado: pendiente · Refs: `../docs/architecture.md`, `docs/design.md` (solo SA0.4–SA0.5), `../docs/agents.md`

## Objetivo

Repo `space-apps/` listo para sumar capas, y las dudas que bloquean resueltas: reglas del evento y acceso a datos.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| SA0.1 | Reglas de Space Apps 2026: código o datos preparados antes del evento, licencia, entregables (video, slides, página del proyecto, repo público) → `docs/research/rules.md` | Opus (opencode falló: 401) | Cada punto con URL oficial, o "sin verificar" ✅ |
| SA0.2 | Monorepo como clima-ideas F0.1: `backend/` (uv, Python 3.12, paquete `firecal`) y `web/` (pnpm, Vite, React, TS, deck.gl); `Makefile`; `data/` fuera de git | Sonnet | `make dev` levanta API y app |
| SA0.3 | CI como clima-ideas F0.2, filtrado a `space-apps/**` | Sonnet | CI verde en un PR |
| SA0.4 | Tokens de `docs/design.md`, tema claro/oscuro, `web/src/i18n/es.ts` y `en.ts` | Sonnet | Cambio de tema y de idioma sin recarga; ningún string fuera de i18n |
| SA0.5 | Shell de la app según el canvas: barra superior con desafío y autor, panel izquierdo, mapa, inspector, franja del calendario | Sonnet | Layout fijo en ambos temas y a ancho de teléfono |
| SA0.6 | FastAPI y manifiesto como clima-ideas F0.6, con `source`, `period`, `license` y campo opcional `experimental` | Sonnet | Unit de manifiesto válido e inválido |
| SA0.7 | Capa de prueba de punta a punta con focos falsos | Sonnet | e2e: la capa aparece y se inspecciona |
| SA0.8 | Acceso a datos (lista abajo) → `docs/research/data-access.md` | opencode | Cada ítem con estado, URL, licencia y volumen, o "sin verificar" |
| SA0.9 | ONI mensual (NOAA CPC) y fase ENSO por mes, igual que clima-ideas F0.10; si F0.10 ya existe, se importa | Sonnet | Parquet + unit de umbrales sobre serie sintética |

## SA0.8: qué investigar

FIRMS: archivo histórico MODIS C6.1 y VIIRS (S-NPP, NOAA-20, NOAA-21) por país y global, volumen, formato;
API de área (MAP_KEY, límite de días por request, standard vs. NRT, latencia) · Catálogo de Focos de Calor y
Áreas Quemadas y Visor Temático de CONAE (acceso, licencia) · SPI/SPEI: CHIRPS, ERA5, SPEIbase · FWI de
Copernicus CEMS · cobertura del suelo global (MODIS MCD12Q1 o ESA WorldCover) · deriva orbital de Terra y Aqua
y fechas de fin de misión · dónde desplegar la demo gratis.

## Tests

Unit: manifiesto, fase ENSO, store de tema e idioma. e2e: shell, tema, idioma, capa de prueba.
