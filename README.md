# Logic Platform

Local app for turning a survey questionnaire PDF and dataset into **`logics.json`**, **`structure.json`**, and **Fairset review** outputs (FairsetReview-style Excel report).

Repo layout:

```text
apps/api/           FastAPI + static UI (built `apps/web/dist`)
apps/web/           React + Vite UI
src/logic_platform/ Pipeline + Fairset integration
tests/              Pytest
Makefile            Convenience targets (optional)
.env.example        Copy to `.env` and add secrets (not committed)
```

## First-time setup (coworkers)

Prerequisites: **Python 3.11+**, **Node 18+**, **npm**.

```bash
git clone <this-repo-url>
cd <repo-folder>

make setup          # creates .venv from .env.example if needed, installs Python + npm deps

# Edit .env and add MANUS_API_KEY (required for logics extraction).
```

Without `make`:

```bash
cp .env.example .env           # edit: MANUS_API_KEY only is enough for defaults
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
cd apps/web && npm install && cd ../..
```

`pip install -e .` installs the `logic_platform` package and **`apps.api`** so you can run **`python -m apps.api`** without exporting `PYTHONPATH`.

## Fairset review (included in-repo)

Fairset-era prior parsing (**`prior_extract.py`**) and constraint checks (**`constraint_checks.py`**) live under **`logic_platform.fairset`**. **`analysis.py`** exposes JSON-safe wrappers for the API. No separate FairsetReview checkout or extra env vars.

## Run locally

Terminal 1 — API (`load_dotenv` reads `.env` from the current working directory; run from repo root):

```bash
make api
# same as:  .venv/bin/python -m apps.api
```

- **http://127.0.0.1:8000** — FastAPI docs and (if **`npm run build`** was run) the built SPA.
- **SPA from API only**: `cd apps/web && npm run build`, then reload the API — no second terminal needed.

Terminal 2 — Vite dev UI (proxies `/runs` to port 8000):

```bash
make web
# same as:  cd apps/web && npm run dev
```

Open **http://127.0.0.1:5173**.

Optional: **`VITE_API_BASE`** — only if the API is **not** on the same origin (see `apps/web/vite.config.ts` proxy).

## Environment variables (`/.env`)

| Variable | When |
|---------|------|
| **`MANUS_API_KEY`** | Default pipeline (**Manus**). Required for **`POST /runs/logics`** and the web wizard. |
| **`GOOGLE_CLOUD_PROJECT`** | Only **`engine=opus`** (Claude on Vertex AI). Ignored if you stick to Manus. |
| **`LOGIC_PLATFORM_RUNS_ROOT`** | Optional; defaults to `./runs`. |

Secrets and local outputs stay out of git (see `.gitignore`).

## Test before you push

```bash
make test
# same as:
#   .venv/bin/python -m pytest
#   cd apps/web && npm run build
```

## Useful paths

Generated runs live under `./runs/` (gitignored).

Do **not** commit: `.env`, raw survey payloads, **`runs/`**, **`node_modules/`**, **`apps/web/dist/`**.
