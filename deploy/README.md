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

**Target AWS runtime (issue #11):** single EC2 + this Compose stack —
see [`docs/ops/ADR-001-aws-runtime.md`](../docs/ops/ADR-001-aws-runtime.md).
ECS Fargate is the documented post-MVP migration path.

**Secrets (issue #13):** production credentials come from AWS Secrets Manager —
see [`SECRETS.md`](SECRETS.md). Local dev still uses a gitignored `.env`.

**Load testing (issue #21):** reproducible scenarios in
[`scripts/load/`](../scripts/load/) and the published baseline in
[`docs/ops/LOAD_BASELINE.md`](../docs/ops/LOAD_BASELINE.md).

> Only the API (`:8000`) and Grafana (`:3000`) publish beyond localhost.
> Postgres and the raw telemetry ports bind to `127.0.0.1`. On EC2, restrict
> even `:8000`/`:3000` via the security group and/or front them with the Nginx
> config in `deploy/nginx.conf.example`.

**AWS provisioning (issue #12):** Terraform under [`infra/`](../infra/) —
bootstrap/teardown and CI drift checks in [`infra/README.md`](../infra/README.md).

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

### Database backups (issue #15)

```bash
sudo cp deploy/ito-db-backup.service deploy/ito-db-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ito-db-backup.timer
```

Playbook, RPO/RTO, and restore drill: [`docs/ops/BACKUP_DR.md`](../docs/ops/BACKUP_DR.md).

Then `systemctl status ito-stack` and `journalctl -u ito-stack -f`.

## AWS WAF (issue #17 — post-launch)

Edge WAF attaches to an **ALB** (not bare Nginx/EC2). Terraform:
[`infra/waf/`](../infra/waf/). Runbook: [`docs/ops/WAF.md`](../docs/ops/WAF.md).

```bash
cd infra/waf && cp terraform.tfvars.example terraform.tfvars
terraform apply -var="enable_blocking=false"   # COUNT mode first
python scripts/test_waf_edge.py --simulate
```

## Common operations

See [CI.md](CI.md) for pipeline jobs, merge gates, and flaky-test policy.

```bash
docker compose logs -f api      # tail the API logs
docker compose up -d --build    # rebuild + restart after a code change
docker compose down             # stop the stack (keeps volumes/data)
docker compose down -v          # stop AND wipe telemetry volumes
```

## CloudWatch (AWS on-call path — issue #16)

Local Prometheus/Grafana stay on-box. For AWS-native paging, apply
[`infra/observability/`](../infra/observability/), then on the EC2 host:

```bash
sudo bash deploy/cloudwatch/install-agent.sh dev
python scripts/publish_cw_api_metrics.py --environment dev --loop
python scripts/test_cloudwatch_alarms.py --simulate
```

Runbook: [`docs/ops/CLOUDWATCH.md`](../docs/ops/CLOUDWATCH.md).

## Notes

- **Data persistence:** Postgres data lives in `DB_DATA_PATH` (default
  `./data/pgdata`; point at the mounted EBS volume on EC2). Prometheus and
  Grafana use named volumes (`prometheus_data`, `grafana_data`).
- **Data retention & secrets:** see [DATA_GOVERNANCE.md](DATA_GOVERNANCE.md).
  Business data is kept indefinitely by default. Prometheus retention defaults
  to unlimited (`PROMETHEUS_RETENTION_TIME=0`); set e.g. `90d` in `.env` on
  small disks.
- **cAdvisor / node-exporter** rely on Linux host mounts (`/sys`, `/proc`,
  `/var/lib/docker`). They are intended for the Linux EC2 host; on macOS/
  colima their host-level metrics may be partial, but the stack still starts.
