.DEFAULT_GOAL := help

UV ?= uv
HOST_PYTHON ?= python
PYTHON ?= ./.venv/Scripts/python.exe
RUFF ?= ./.venv/Scripts/ruff.exe
MYPY ?= ./.venv/Scripts/mypy.exe
PYTEST ?= ./.venv/Scripts/pytest.exe
ALEMBIC ?= ./.venv/Scripts/alembic.exe
UVICORN ?= ./.venv/Scripts/uvicorn.exe
CELERY ?= ./.venv/Scripts/celery.exe
DOCKER_COMPOSE ?= docker compose

.PHONY: help setup sync env lint format type test check compile app-smoke compose-check docker-check db-up db-down migrate migrate-up migrate-down seed add-emails api worker beat docker-up docker-up-detached stack-up stack-down clean

help:
	@echo Available targets:
	@echo   setup          Create .env and install dev dependencies
	@echo   sync           Install/update dependencies with uv
	@echo   lint           Run Ruff lint checks
	@echo   format         Run Ruff formatter and auto-fixes
	@echo   type           Run mypy over app/
	@echo   test           Run pytest
	@echo   check          Run lint, type, tests, compile, app smoke, compose config
	@echo   docker-check   Verify Docker Desktop/engine is reachable
	@echo   db-up          Start Postgres and Redis
	@echo   migrate        Alias for migrate-up
	@echo   migrate-up     Apply Alembic migrations up to latest
	@echo   migrate-down   Roll Alembic back by one migration
	@echo   seed           Seed demo firms, users, clients, and emails
	@echo   add-emails     Add one demo email for refresh testing
	@echo   api            Run FastAPI locally without Docker
	@echo   worker         Run Celery worker locally without Docker
	@echo   beat           Run Celery beat locally without Docker
	@echo   docker-up      Build, migrate, seed, and run the full Docker stack
	@echo   docker-up-detached  Build, migrate, seed, and run Docker stack in background
	@echo   stack-up       Run API, worker, beat, Postgres, and Redis with Docker
	@echo   stack-down     Stop Docker Compose services

setup: env sync

sync:
	$(UV) sync --extra dev

env:
	@$(HOST_PYTHON) -c "from pathlib import Path; src=Path('.env.example'); dst=Path('.env'); dst.exists() or dst.write_text(src.read_text())"

lint:
	$(RUFF) check .

format:
	$(RUFF) format .
	$(RUFF) check . --fix

type:
	$(MYPY) app

test:
	uv run pytest tests/unit -v --cov=app --cov-report=html

compile:
	$(PYTHON) -m compileall app scripts tests

app-smoke:
	$(PYTHON) -c "from app.main import app; from app.core.encryption import EncryptionService; EncryptionService(); print(app.title)"

compose-check: env
	$(DOCKER_COMPOSE) config --quiet

docker-check:
	@$(HOST_PYTHON) -c "import subprocess, sys; p=subprocess.run(['docker','info'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); sys.exit(0 if p.returncode == 0 else 'Docker is not reachable. Start Docker Desktop, wait until it says Docker is running, then rerun make docker-up.')"

check: lint type test compile app-smoke compose-check

db-up: env docker-check
	$(DOCKER_COMPOSE) up -d postgres redis

db-down:
	$(DOCKER_COMPOSE) down

migrate: migrate-up

migrate-up:
	$(ALEMBIC) upgrade head

migrate-down:
	$(ALEMBIC) downgrade -1

seed:
	$(PYTHON) -m scripts.seed

add-emails:
	$(PYTHON) -m scripts.add_new_emails

api:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

worker:
	$(CELERY) -A app.workers.celery_app:celery_app worker --loglevel=INFO

beat:
	$(CELERY) -A app.workers.celery_app:celery_app beat --loglevel=INFO

docker-up: env docker-check
	$(DOCKER_COMPOSE) up -d postgres redis
	$(DOCKER_COMPOSE) run --rm api python -m alembic upgrade head
	$(DOCKER_COMPOSE) run --rm api python -m scripts.seed
	$(DOCKER_COMPOSE) up --build api worker beat

docker-up-detached: env docker-check
	$(DOCKER_COMPOSE) up -d postgres redis
	$(DOCKER_COMPOSE) run --rm api python -m alembic upgrade head
	$(DOCKER_COMPOSE) run --rm api python -m scripts.seed
	$(DOCKER_COMPOSE) up -d --build api worker beat

stack-up: env docker-check
	$(DOCKER_COMPOSE) up api worker beat

stack-down:
	$(DOCKER_COMPOSE) down

clean:
	$(PYTHON) -c "import shutil; from pathlib import Path; [shutil.rmtree(p, ignore_errors=True) for p in Path('.').rglob('__pycache__')]; [shutil.rmtree(p, ignore_errors=True) for p in ['.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov']]"
