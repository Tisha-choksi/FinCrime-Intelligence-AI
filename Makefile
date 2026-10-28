.PHONY: up down logs migrate seed test

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	@echo "TODO: run database/migrations against postgres (no migration runner wired up yet)"

seed:
	@echo "TODO: load datasets/synthetic fixtures (no seed script yet)"

test:
	@echo "TODO: pytest tests/unit tests/integration (no test suite yet)"
