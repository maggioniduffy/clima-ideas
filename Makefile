.PHONY: dev test lint install

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
