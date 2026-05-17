# POSIX-friendly helpers (direct ``.venv/bin/...`` paths; no shell ``source``).
.PHONY: setup api web ui test help

PYTHON ?= python3
VENV = .venv
PIP = $(VENV)/bin/pip
PY = $(VENV)/bin/python

help:
	@echo "Targets:"
	@echo "  make setup   Create .venv, install Python deps (+ editable pkg), npm install UI"
	@echo "  make api     FastAPI (+ built UI dist if present): http://127.0.0.1:8000"
	@echo "  make web     Vite UI: http://127.0.0.1:5173 — run api in another terminal"
	@echo "  make ui      alias for ``make web``"
	@echo "  make test    pytest + ``npm run build`` in apps/web"

setup:
	@if ! test -f .env; then cp .env.example .env && echo "[logic-platform] Created .env from .env.example — add MANUS_API_KEY"; fi
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -r requirements.txt
	$(PIP) install -e .
	cd apps/web && npm install

api:
	@test -x $(PY) || (echo ">> Run ``make setup`` first" && exit 1)
	$(PY) -m apps.api

web ui:
	cd apps/web && npm run dev

test:
	@test -x $(PY) || (echo ">> Run ``make setup`` first" && exit 1)
	$(PY) -m pytest
	cd apps/web && npm run build
