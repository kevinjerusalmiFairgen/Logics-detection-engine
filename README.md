# Logic Platform

Local app for turning a survey questionnaire PDF and dataset into:

- `logics.json`
- `structure.json`
- Fairset review reports

The repo is organized around the platform now:

```text
apps/api/          FastAPI app
apps/web/          React + Vite UI
src/logic_platform/ Python package and pipeline code
tests/             Regression tests
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

cd apps/web
npm install
```

## Run Locally

From the repo root:

```bash
PYTHONPATH=src:. python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

In another terminal:

```bash
cd apps/web
npm run dev
```

Open `http://127.0.0.1:5173`.

## Test

```bash
python -m pytest
cd apps/web && npm run build
```

## Local Files

Generated runs, uploaded data, virtual environments, frontend dependencies, and caches are intentionally local-only and ignored by git.

Do not commit `.env`, raw survey data, PDFs, `.sav` files, generated `runs/`, or frontend `node_modules/`.
