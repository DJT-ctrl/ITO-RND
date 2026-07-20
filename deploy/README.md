# Deployment — ITO monolith stack

Postgres + FastAPI + local telemetry (Prometheus, Grafana, cAdvisor,
node-exporter) as a single Docker Compose stack, brought up with **one
command** and optionally supervised by systemd on the instance.

## Prerequisites

- Docker Engine + the Docker Compose v2 plugin (`docker compose`, not the
  legacy `docker-compose`).
- A `.env` file at the repo root: `cp .env.example .env` and fill in at least
  `POSTGRES_PASSWORD`, `GEMINI_API_KEY`, and `GRAFANA_ADMIN_PASSWORD`.

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

Grafana opens with the Prometheus datasource and an **ITO Stack Overview**
dashboard already provisioned (API request rate / p95 latency, per-container
CPU & memory).

> Only the API (`:8000`) and Grafana (`:3000`) publish beyond localhost.
> Postgres and the raw telemetry ports bind to `127.0.0.1`. On EC2, put the
> public **edge** in front (see below) — it terminates HTTPS, restricts the
> origin to Cloudflare, and rebinds the API to localhost so Nginx is the only
> public entry point. Grafana stays localhost-only (reach it via SSH tunnel).

## Public edge — Cloudflare + Nginx (HTTPS)

Everything above binds to localhost or an internal port. To serve the API on a
real domain over HTTPS, add the **Web Traffic & Security Guard** layer in
[edge/](edge/): a free Cloudflare proxy in front of an Nginx origin that
terminates TLS, locks itself to Cloudflare's IP ranges, rate-limits, and blocks
`/metrics`. Automated HTTPS uses Let's Encrypt via the Cloudflare DNS-01
challenge (auto-renewed).

```bash
set -a; source .env; set +a                       # CF_*/EDGE_*/LETSENCRYPT_* — see .env.example
deploy/edge/cloudflare/cloudflare-setup.sh        # proxied DNS + Full(strict) SSL + Always-HTTPS
deploy/edge/cloudflare/update-cloudflare-ips.sh   # refresh CF IP snippets
docker compose -f docker-compose.yml -f deploy/edge/docker-compose.edge.yml run --rm certbot
docker compose -f docker-compose.yml -f deploy/edge/docker-compose.edge.yml up -d
```

Full runbook, security model, cert options, and the self-contained test suite
(`deploy/edge/tests/run-all.sh`): **[edge/README.md](edge/README.md)**.

### Port conflicts

If a host port is already in use, override it in `.env` (or inline) — the
containers still reach each other over the internal network:

```bash
DB_HOST_PORT=5433 API_HOST_PORT=8001 GRAFANA_HOST_PORT=3001 docker compose up -d
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
  `./data/pgdata`; point at the mounted EBS volume on EC2). Prometheus and
  Grafana use named volumes (`prometheus_data`, `grafana_data`).
- **cAdvisor / node-exporter** rely on Linux host mounts (`/sys`, `/proc`,
  `/var/lib/docker`). They are intended for the Linux EC2 host; on macOS/
  colima their host-level metrics may be partial, but the stack still starts.
