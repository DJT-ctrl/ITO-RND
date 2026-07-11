# Deployment — ITO monolith stack

Postgres + FastAPI + local telemetry (Prometheus, Grafana, cAdvisor,
node-exporter) + a self-hosted **Langfuse** LLM trace engine as a single
Docker Compose stack, brought up with **one command** and optionally
supervised by systemd on the instance.

## Prerequisites

- Docker Engine + the Docker Compose v2 plugin (`docker compose`, not the
  legacy `docker-compose`).
- A `.env` file at the repo root: `cp .env.example .env` and fill in at least
  `POSTGRES_PASSWORD`, `GEMINI_API_KEY`, and `GRAFANA_ADMIN_PASSWORD`. The
  Langfuse backing stores boot on built-in local-dev defaults, so no extra
  secrets are needed to bring the stack up — override those defaults in
  `docker-compose.yml` for any non-local deployment.

## Start the whole stack (one command)

```bash
docker compose up -d
```

That builds the API image, starts Postgres, runs the one-shot `migrate`
service (creates the `pgvector` extension + `posts` table + HNSW index), then
starts the API and the telemetry services. Check it:

```bash
docker compose ps          # all services up; `migrate` shows Exited (0)
curl localhost:8000/health # {"status":"ok"}
```

## Endpoints

| Service       | URL                          | Notes                                   |
| ------------- | ---------------------------- | --------------------------------------- |
| FastAPI       | http://localhost:8000/docs   | OpenAPI UI                              |
| API metrics   | http://localhost:8000/metrics| scraped by Prometheus                   |
| Prometheus    | http://localhost:9090        | bound to localhost                      |
| Grafana       | http://localhost:3000        | login from `GRAFANA_ADMIN_*` in `.env`  |
| cAdvisor      | http://localhost:8080        | bound to localhost                      |
| node-exporter | http://localhost:9100        | bound to localhost                      |
| Langfuse      | http://localhost:3001        | LLM trace engine UI (T6.5)              |

Grafana opens with the Prometheus datasource and an **ITO Stack Overview**
dashboard already provisioned (API request rate / p95 latency, per-container
CPU & memory).

### Langfuse trace engine (LLM observability)

Prometheus/Grafana cover container and HTTP metrics; Langfuse covers the LLM
layer the app-level metrics can't see — per-agent **execution cost** (token
usage priced per model), **execution time** (a span per Predictor / SEO /
Clarity / Tone / Variant agent run), and the **payload properties** (each
agent's prompt and structured response). PydanticAI emits these as
OpenTelemetry spans; `agents/observability.py` routes them to the self-hosted
Langfuse container. Everything runs locally — no cloud, no per-trace billing.

**Setup:** put a `pk-lf-...` / `sk-lf-...` pair in `.env` as
`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` (any random values — a UUID
works) before the first `docker compose up`. Headless init seeds the Langfuse
project with those keys on first boot, so the app starts tracing immediately —
no manual UI step. Log into the UI at http://localhost:3001 with the default
`admin@ito.local` / `langfuse-admin` (override via `LANGFUSE_INIT_USER_EMAIL` /
`LANGFUSE_INIT_USER_PASSWORD` in `.env` before first boot).

Leave the keys blank to disable tracing — it becomes a silent no-op and the
API and test suite run exactly as before. With keys set, each
`POST /api/v1/evaluate` produces one nested trace per evaluation cycle, with a
child span per agent showing its latency, token cost, and input/output
payloads.

> Only the API (`:8000`) and Grafana (`:3000`) publish beyond localhost.
> Postgres and the raw telemetry ports bind to `127.0.0.1`. On EC2, restrict
> even `:8000`/`:3000` via the security group and/or front them with the Nginx
> config in `deploy/nginx.conf.example`.

### Port conflicts

If a host port is already in use, override it in `.env` (or inline) — the
containers still reach each other over the internal network:

```bash
DB_HOST_PORT=5433 API_HOST_PORT=8001 GRAFANA_HOST_PORT=3002 LANGFUSE_HOST_PORT=3003 docker compose up -d
```

## Load sample data (optional)

The `migrate` service only creates the empty schema. To populate the 250
sample posts from the repo, run the ingest against the running DB:

```bash
# From the host (venv with requirements installed), pointing at the container:
python -m processors.run_db_ingest
```

`run_db_ingest` needs the `data/processed/*.jsonl` + `data/embeddings/*.npy`
files (which are excluded from the API image), so run it from the host with a
`.env` `DATABASE_URL` of `...@localhost:5432/...`.

## Run as a systemd service (start on boot)

```bash
sudo cp deploy/ito-stack.service /etc/systemd/system/ito-stack.service
# edit WorkingDirectory in the unit if the repo isn't at /opt/ito-rnd
sudo systemctl daemon-reload
sudo systemctl enable --now ito-stack.service
```

Then `systemctl status ito-stack` and `journalctl -u ito-stack -f`.

## Common operations

```bash
docker compose logs -f api      # tail the API logs
docker compose up -d --build    # rebuild + restart after a code change
docker compose down             # stop the stack (keeps volumes/data)
docker compose down -v          # stop AND wipe telemetry volumes
```

## Notes

- **Data persistence:** Postgres data lives in `DB_DATA_PATH` (default
  `./data/pgdata`; point at the mounted EBS volume on EC2). Prometheus,
  Grafana, and the Langfuse backing stores use named volumes
  (`prometheus_data`, `grafana_data`, `langfuse_db_data`, `clickhouse_data`,
  `clickhouse_logs`, `minio_data`).
- **Langfuse footprint:** the trace engine adds six containers
  (`langfuse-web`, `langfuse-worker`, `langfuse-db`, `clickhouse`, `minio`,
  `redis`) and ~2 GB RAM. It only publishes `:3001`; the rest talk over the
  internal network.
- **cAdvisor / node-exporter** rely on Linux host mounts (`/sys`, `/proc`,
  `/var/lib/docker`). They are intended for the Linux EC2 host; on macOS/
  colima their host-level metrics may be partial, but the stack still starts.
