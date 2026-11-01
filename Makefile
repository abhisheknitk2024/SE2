# Relay developer workflow. Run `make setup` once per fresh checkout.

PY := .venv/bin/python
PORT ?= 8000

.PHONY: setup db migrate dev test lint fmt check psql

setup: ## create venv and install the project + dev tools
	python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e ".[dev]"
	@echo "setup done -> make db, make migrate, make dev"

db: ## start the local Postgres and print its DSN
	@$(PY) scripts/dev_db.py

migrate: ## apply pending migrations
	@$(PY) scripts/migrate.py

dev: ## run the API with reload on 0.0.0.0:8000
	$(PY) -m uvicorn relay.app:app --host 0.0.0.0 --port $(PORT) --reload

test: ## run the test suite against a throwaway database
	$(PY) -m pytest -q

lint: ## static checks
	$(PY) -m ruff check src tests scripts
	$(PY) -m ruff format --check src tests scripts

fmt: ## auto-format and auto-fix
	$(PY) -m ruff format src tests scripts
	$(PY) -m ruff check --fix src tests scripts

check: ## what CI runs
	lint test

psql: ## interactive psql against the dev database
	@$(PY) scripts/dev_db.py > /dev/null
	@psql "$$($(PY) -c 'from relay.config import get_settings; print(get_settings().database_url)')"
