# intotheopen-backend

LinkedIn post intelligence backend: scraping, enrichment, embeddings, multi-agent
evaluation, validation pipeline, and feedback loop.

## Repository layout

```
api/                    FastAPI service (OpenAPI at /docs)
agents/                 PydanticAI evaluation agents
scrapers/               Apify-backed LinkedIn scrapers
processors/             Collection, analysis, embedding, and batch pipelines
validation_pipeline/    Ground-truth collection, prediction, and rescrape
feedback/               Calibration, cluster feedback, and evaluation loop
storage/                Postgres schema, vector store, backups
dashboard/              Streamlit dev harness and validation UI
telemetry/              Cost and evaluation telemetry
deploy/                 Docker Compose stack and deployment notes
tests/                  Unit and integration tests (mocked APIs)
```

## Quick start

1. **Environment**

   ```bash
   cp .env.example .env
   # Set POSTGRES_PASSWORD, GEMINI_API_KEY, APIFY_API_TOKEN, etc.
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Full stack (Postgres + API + telemetry)**

   ```bash
   docker compose up -d
   curl localhost:8000/health
   ```

   See [deploy/README.md](deploy/README.md) for endpoints, Grafana, and systemd notes.

3. **Streamlit dashboard (local dev)**

   ```bash
   streamlit run dashboard/app.py
   ```

4. **Collect LinkedIn samples**

   ```bash
   python -m processors.run_sample_collection --search "ai marketing" --max-posts 20
   ```

## Tests

```bash
pytest -q
```

Tests mock external APIs — no Apify or Gemini charges during CI/local runs.

## Key environment variables

| Variable | Purpose |
| -------- | ------- |
| `GEMINI_API_KEY` | Gemini models for analysis and embeddings |
| `APIFY_API_TOKEN` | LinkedIn scraper actors |
| `DATABASE_URL` | Postgres + pgvector connection |
| `POSTGRES_PASSWORD` | Required for `docker compose up` |

Full list in `.env.example`.
