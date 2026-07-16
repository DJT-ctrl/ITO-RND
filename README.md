# intotheopen-backend

LinkedIn post intelligence backend: scraping, enrichment, embeddings, multi-agent
evaluation, validation pipeline, and feedback loop.

This document is the **build and reproduction guide**. For production deployment
(Docker Compose stack, Grafana, systemd), see [deploy/README.md](deploy/README.md).

---

## Table of contents

1. [Architecture overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Clone and install](#clone-and-install)
4. [Environment configuration](#environment-configuration)
5. [Build](#build)
6. [Run the stack](#run-the-stack)
7. [Reproduce the corpus pipeline](#reproduce-the-corpus-pipeline)
8. [Reproduce the validation pipeline](#reproduce-the-validation-pipeline)
9. [Reproduce the feedback loop](#reproduce-the-feedback-loop)
10. [Streamlit dashboard](#streamlit-dashboard)
11. [API endpoints](#api-endpoints)
12. [Tests](#tests)
13. [Troubleshooting](#troubleshooting)

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Corpus pipeline (offline)                       │
│  Apify scrape → normalize/analyse → embed (Gemini) → ingest (pgvector)  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Runtime services                                │
│  FastAPI (similarity + evaluation)  │  Streamlit dev harness            │
│  Postgres 16 + pgvector               │  Prometheus / Grafana            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Validation + feedback loop                           │
│  collect & predict → wait window → re-scrape → score delta → feedback   │
└─────────────────────────────────────────────────────────────────────────┘
```

| Directory | Purpose |
| --------- | ------- |
| `api/` | FastAPI service (OpenAPI at `/docs`) |
| `agents/` | PydanticAI evaluation agents |
| `scrapers/` | Apify-backed LinkedIn scrapers |
| `processors/` | Collection, analysis, embedding, and batch pipelines |
| `validation_pipeline/` | Ground-truth collection, prediction, and rescrape |
| `feedback/` | Calibration, cluster feedback, and evaluation loop |
| `storage/` | Postgres schema, vector store, backups |
| `dashboard/` | Streamlit dev harness and validation UI |
| `telemetry/` | Cost and evaluation telemetry |
| `deploy/` | Docker Compose stack and deployment notes |
| `tests/` | Unit and integration tests (mocked external APIs) |

---

## Prerequisites

| Requirement | Version / notes |
| ----------- | --------------- |
| **Python** | **3.12 required** for local installs (matches `Dockerfile` and the pinned `requirements.txt` lockfile) |
| **Docker** | Engine + Compose v2 plugin (`docker compose`, not legacy `docker-compose`) |
| **Git** | To clone the repo |
| **Apify account** | For live LinkedIn scraping ([apify.com](https://apify.com)) |
| **Gemini API key** | For post analysis, embeddings, and agents ([Google AI Studio](https://aistudio.google.com/app/apikey)) |

Optional for profile enrichment and some validation rescrapes:

- **LinkedIn cookies** — exported via the Cookie-Editor browser extension while
  logged into LinkedIn. Treat like a password; never commit real values.

---

## Clone and install

```bash
git clone https://github.com/intotheopen/intotheopen-backend.git
cd intotheopen-backend

python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt   # pinned lockfile (see requirements.in to change deps)
```

**Dependency locking (issue #4):** `requirements.in` is the human-editable source;
`requirements.txt` is the pinned lockfile generated with pip-tools on **Python 3.12**
(matching Docker). After editing `requirements.in`, regenerate the lock:

```bash
./scripts/compile-requirements.sh
```

Local + CI + Docker should all install from the same `requirements.txt` for
reproducible environments.

---

## Environment configuration

Copy the example file and fill in secrets:

```bash
cp .env.example .env
```

**Minimum for `docker compose up`:**

| Variable | Purpose |
| -------- | ------- |
| `POSTGRES_PASSWORD` | Postgres container password (required by Compose) |
| `GRAFANA_ADMIN_PASSWORD` | Grafana login (change before any non-local use) |

**Minimum for live scraping and AI features:**

| Variable | Purpose |
| -------- | ------- |
| `APIFY_API_TOKEN` | Apify API access |
| `APIFY_ACTOR_ID` | LinkedIn post-search actor |
| `GEMINI_API_KEY` | Gemini models for analysis, embeddings, and agents |
| `DATABASE_URL` | Postgres connection string (default in `.env.example` works locally) |

**Optional but commonly needed:**

| Variable | Purpose |
| -------- | ------- |
| `APIFY_PROFILE_ACTOR_ID` | Profile enrichment actor (default: `harvestapi/linkedin-profile-scraper`) |
| `APIFY_POST_URL_ACTOR_ID` | Direct post URL re-scrape for validation |
| `LINKEDIN_COOKIES` | JSON cookie array for profile scraper (sensitive) |
| `VALIDATION_DEV_WINDOW_MINUTES` | Short validation window for local testing (e.g. `5`) |

Full list and defaults: `.env.example`.

---

## Build

### Local Python environment

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Docker API image

The Compose stack builds the API image automatically on first `up`. To build
manually:

```bash
docker compose build api
```

The image uses `python:3.12-slim`, installs the pinned `requirements.txt` lockfile,
and runs `uvicorn api.main:app` on port 8000. Data files and the Streamlit dashboard
are excluded via `.dockerignore` — host-side scripts read from `data/` directly.

---

## Run the stack

Start Postgres, schema migration, API, and telemetry in one command:

```bash
docker compose up -d
```

Verify:

```bash
docker compose ps          # migrate should show Exited (0)
curl localhost:8000/health # {"status":"ok"}
```

| Service | URL | Notes |
| ------- | --- | ----- |
| FastAPI | http://localhost:8000/docs | OpenAPI UI |
| API metrics | http://localhost:8000/metrics | Scraped by Prometheus |
| Grafana | http://localhost:3000 | Login from `GRAFANA_ADMIN_*` |
| Prometheus | http://localhost:9090 | Localhost only |

Port conflicts: override in `.env` or inline:

```bash
DB_HOST_PORT=5433 API_HOST_PORT=8001 GRAFANA_HOST_PORT=3001 docker compose up -d
```

See [deploy/README.md](deploy/README.md) for systemd, Nginx, and common ops.

---

## Reproduce the corpus pipeline

The corpus pipeline turns raw LinkedIn scrapes into a searchable vector database.
There are two paths: **bundled sample data** (no Apify/Gemini cost) and **live
end-to-end** (full reproduction).

### Path A — Bundled sample data (fastest)

The repo ships a pre-built dataset you can load without scraping:

- `data/processed/linkedin_20260704T205635Z.jsonl` (290 posts)
- `data/embeddings/linkedin_gemini_20260705T022011Z.npy` (290 × 3072 vectors)

**Steps:**

```bash
# 1. Start Postgres (if not already running)
docker compose up -d db migrate

# 2. Ingest into pgvector
source .venv/bin/activate
python -m processors.run_db_ingest \
  --processed-file data/processed/linkedin_20260704T205635Z.jsonl \
  --embeddings-file data/embeddings/linkedin_gemini_20260705T022011Z.npy
```

**Verify similarity search** (requires `GEMINI_API_KEY` in `.env` and API running):

```bash
curl -s localhost:8000/api/v1/similar-posts \
  -H 'Content-Type: application/json' \
  -d '{"content": "Tips for hiring engineers in 2026", "limit": 5}' | python -m json.tool
```

### Path B — Full live pipeline

Run each stage in order. All commands assume an activated venv and a configured
`.env`.

#### Stage 1 — Scrape posts + enrich profiles

```bash
python -m processors.run_sample_collection \
  --search "ai marketing" \
  --max-posts 20
```

**Outputs** (timestamped under `data/`):

- `data/raw/linkedin_{ts}.json` — raw post scan
- `data/raw/linkedin_profiles_{ts}.json` — profile data (if personal authors found)
- `data/processed/linkedin_enriched_{ts}.csv` — merged enrichment preview

> `data/raw/` is gitignored. Raw files stay on your machine.

#### Stage 2 — Normalize, benchmark, and analyse

Stage 1 features only (free, no Gemini):

```bash
python -m processors.run_pipeline
```

With Gemini qualitative tags (costs API calls):

```bash
python -m processors.run_pipeline --with-gemini
```

With profile-enriched follower benchmarks and local posting time:

```bash
python -m processors.run_pipeline --with-profile-enrichment --with-gemini
```

**Outputs:**

- `data/processed/linkedin_python_{ts}.csv` and `.jsonl`
- `data/processed/linkedin_analysed_{ts}.csv` and `.jsonl` (when Gemini runs)

#### Stage 3 — Generate embeddings

```bash
# Uses latest linkedin_analysed_*.jsonl by default
python -m processors.run_embeddings

# Or target a specific file; use --limit for a cheap test run
python -m processors.run_embeddings \
  --processed-file data/processed/linkedin_analysed_YYYY-MM-DD_HHMMSSZ.jsonl \
  --limit 10
```

**Output:** `data/embeddings/linkedin_gemini_{ts}.npy`

#### Stage 4 — Ingest into Postgres

```bash
docker compose up -d db migrate   # ensure schema exists

python -m processors.run_db_ingest
# Or pass explicit paths:
python -m processors.run_db_ingest \
  --processed-file data/processed/linkedin_analysed_YYYY-MM-DD_HHMMSSZ.jsonl \
  --embeddings-file data/embeddings/linkedin_gemini_YYYYMMDDT_HHMMSSZ.npy
```

`run_db_ingest` takes a full-database backup to `data/db_backups/` before
writing. Use `--skip-backup` only when you know the DB is empty.

#### Pipeline diagram

```
run_sample_collection
        │
        ▼
   data/raw/*.json
        │
        ▼
  run_pipeline [--with-gemini] [--with-profile-enrichment]
        │
        ▼
  data/processed/linkedin_analysed_*.jsonl
        │
        ▼
     run_embeddings
        │
        ▼
  data/embeddings/linkedin_gemini_*.npy
        │
        ▼
     run_db_ingest  ──►  Postgres + pgvector (posts table, HNSW index)
```

---

## Reproduce the validation pipeline

The validation pipeline scrapes fresh posts, predicts engagement percentiles,
waits for a validation window, then re-scrapes to measure accuracy.

### Quick local test (short window)

Add to `.env`:

```bash
VALIDATION_DEV_WINDOW_MINUTES=5
```

### Collect, predict, and schedule validation

```bash
python -m validation_pipeline.jobs.run_collect_predict \
  --search "ai marketing" \
  --max-posts 10
```

This scrapes posts, runs predictions, and schedules re-scrape jobs after the
validation window (`VALIDATION_WINDOW_HOURS`, default 48h, or the dev override).

### Process due validations

Run periodically (cron, systemd timer, or manually):

```bash
python -m validation_pipeline.jobs.run_validation_worker --limit 50
```

Re-scrapes due predictions, computes deltas, and persists scores.

### Dashboard alternative

```bash
streamlit run dashboard/app.py
```

Navigate to **Validation Pipeline → Collect & Predict**, **Validation Queue**,
and **Accuracy History** for interactive control and charts.

---

## Reproduce the feedback loop

The feedback loop turns validation deltas into calibration offsets and template
feedback for future predictions.

### Safe production baseline

```bash
VALIDATION_FEEDBACK_ENABLED=true
VALIDATION_CALIBRATION_ENABLED=false
VALIDATION_FEEDBACK_INJECTION_ENABLED=false
```

Dashboard overrides in **Validation Pipeline → Feedback Loop** take precedence
over `.env` values.

### Generate template feedback (CLI)

```bash
python -m feedback.jobs.run_feedback_batch --limit 100
```

Idempotent for `(prediction_id, feedback_version)`.

### Held-out evaluation (before enabling calibration)

Requires at least 31 validated rows in the database:

```bash
python -m feedback.jobs.run_feedback_evaluation --holdout-size 30
```

Reports are saved to `data/telemetry/eval_feedback_*.json`.

Latest Phase F decision: [`current md/11_GO_NO_GO.md`](current%20md/11_GO_NO_GO.md)
(active feedback-loop docs live under [`current md/`](current%20md/)).

**Enable global calibration only when:**

1. Holdout has at least 30 rows
2. Raw-to-calibrated MAE improves by at least 5%
3. The result repeats in two evaluation runs

**Enable cluster calibration** only for clusters with ≥ 50 training rows and
better MAE than the global fallback.

### Incident rollback

If MAE worsens after enabling calibration:

1. Turn **Calibration** off in the Feedback Loop dashboard immediately
2. Export `eval_feedback_*.json` and Accuracy History data
3. Re-enable only after a new held-out evaluation passes the gates above

---

## Streamlit dashboard

Local dev harness for every pipeline stage:

```bash
streamlit run dashboard/app.py
```

| Section | Pages |
| ------- | ----- |
| **Corpus Pipeline** | Scraper → Post Analyser → Pattern Analysis → Vectorisation → Similarity Search |
| **Validation Pipeline** | Collect & Predict → Validation Queue → Accuracy History → Feedback Loop |
| **Evaluation** | Evaluation Cycle (multi-agent draft scoring) |

The dashboard reads `.env` from the repo root regardless of working directory.

---

## API endpoints

With the API running (`docker compose up -d` or `uvicorn api.main:app`):

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/health` | Liveness check |
| `GET` | `/metrics` | Prometheus metrics |
| `POST` | `/api/v1/similar-posts` | Cosine-similarity retrieval over ingested corpus |
| `POST` | `/api/v1/evaluate` | Full multi-agent evaluation cycle |

**Similar posts example:**

```bash
curl -s localhost:8000/api/v1/similar-posts \
  -H 'Content-Type: application/json' \
  -d '{"content": "Your draft post text here", "limit": 5}'
```

**Evaluate example:**

```bash
curl -s localhost:8000/api/v1/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"content": "Your draft post text here"}'
```

OpenAPI schema: http://localhost:8000/docs

---

## Tests

```bash
pytest -q
```

Tests mock external APIs (Apify, Gemini, Postgres where needed) — no API
charges during CI or local test runs.

Run a specific module:

```bash
pytest tests/test_run_pipeline.py -q
pytest tests/test_api.py -q
pytest tests/test_validation_store.py -q
pytest tests/test_feedback_evaluation.py -q
```

---

## Troubleshooting

### `POSTGRES_PASSWORD must be set in .env`

Copy `.env.example` to `.env` and set `POSTGRES_PASSWORD` before
`docker compose up`.

### Port already in use

Override host ports:

```bash
DB_HOST_PORT=5433 API_HOST_PORT=8001 docker compose up -d
```

### `No analysed JSONL files found` (embeddings)

Run the post analyser first:

```bash
python -m processors.run_pipeline --with-gemini
```

Or use the bundled sample paths in [Path A](#path-a--bundled-sample-data-fastest).

### `DATABASE_URL is not set`

Ensure `.env` exists at the repo root with a valid `DATABASE_URL`. For
host-side scripts pointing at the Compose Postgres:

```
DATABASE_URL=postgresql://ito:<password>@localhost:5432/ito_posts
```

### Gemini / Apify errors during live runs

- Confirm `GEMINI_API_KEY` and `APIFY_API_TOKEN` are set and valid
- Check Apify actor IDs match your account's actors
- For profile scraping, `LINKEDIN_COOKIES` may be required

### Streamlit import errors

Run from the repo root (or any directory — `dashboard/app.py` adds the project
root to `sys.path`):

```bash
streamlit run dashboard/app.py
```

### Docker rebuild after code changes

```bash
docker compose up -d --build
```

---

## Further reading

- [deploy/README.md](deploy/README.md) — production stack, Grafana, systemd, Nginx
- [.env.example](.env.example) — full environment variable reference
