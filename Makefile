.PHONY: up down migrate test test-integration test-pitr lint

up:
	docker compose up -d

down:
	docker compose down

migrate:
	docker compose exec backend alembic upgrade head

test:
	docker compose exec backend pytest

test-integration: ## Run integration tests (requires Docker running locally)
	cd backend && python -m pytest tests/integration/ -m "integration and not integration_pitr" -v

test-pitr: ## Run PITR test (requires compose stack running)
	docker compose exec backend pytest backend/tests/integration/test_pitr.py -v

lint:
	docker compose exec backend ruff check .
	docker compose exec backend mypy --strict .
