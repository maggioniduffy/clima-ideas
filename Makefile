.PHONY: dev test lint install publish publish-dry

install:
	cd backend && uv sync
	cd web && pnpm install

dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && exec uv run uvicorn clima_nqn.api.app:app --reload --port 8000) & \
	(cd web && exec pnpm dev) & \
	wait

test:
	cd backend && uv run pytest
	cd web && pnpm test

lint:
	cd backend && uv run ruff check
	cd web && pnpm lint
	cd web && pnpm typecheck

# R2_* vars come from the environment or, if present, the repo-root .env (exported vars win).
ENV_FILE := $(if $(wildcard .env),--env-file ../.env)

# Upload data/processed and layers.json to Cloudflare R2 (needs R2_* env vars, see docs/architecture.md).
publish:
	cd backend && uv run $(ENV_FILE) clima-nqn publish

publish-dry:
	cd backend && uv run $(ENV_FILE) clima-nqn publish --dry-run
