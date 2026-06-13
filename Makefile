.PHONY: dev test migrate migration shell lint fmt

dev:
	uv run uvicorn cairn.main:app --reload --host 0.0.0.0 --port 8000

test:
	uv run pytest

migrate:
	uv run alembic upgrade head

migration:
	@read -p "Migration message: " msg; uv run alembic revision --autogenerate -m "$$msg"

shell:
	uv run python -i -c "import asyncio; from cairn.database import AsyncSessionLocal, engine"

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .
