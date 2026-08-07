# AWS single-instance deploy & rollback runbook

Issue **#20** — repeatable release path for the Compose-on-EC2 MVP (ADR-001 /
issue **#11**). Strategy is **controlled rolling restart** on one node (not a
second blue/green instance — that would break `budget:low-cost-mvp`).

| Audience | Another engineer with SSM (or SSH) to the Compose host |
| -------- | ------------------------------------------------------ |
| Host layout | Repo at `/opt/ito-rnd`, systemd `ito-stack`, Docker Compose |
| Prerequisites | **#12** host up; prefer **#13** secrets; backups **#15** healthy |

Companion scripts:

| Script | Role |
| ------ | ---- |
| [`scripts/deploy_release.py`](../../scripts/deploy_release.py) | Pre-smoke → record previous SHA/image → pull/build/restart → post-smoke |
| [`scripts/rollback_release.py`](../../scripts/rollback_release.py) | Restore previous git SHA + rebuild; abort criteria |
| [`scripts/run_deploy_drill.py`](../../scripts/run_deploy_drill.py) | Controlled/simulated rollback drill + timings |

Latest drill artifact: [`DEPLOY_DRILL_LATEST.json`](DEPLOY_DRILL_LATEST.json).

---

## Downtime window expectations

| Phase | Expected API downtime | Notes |
| ----- | --------------------- | ----- |
| Pre-deploy smoke | **0** | Read-only checks |
| `git fetch` / checkout | **0** | Code on disk only |
| Compose rebuild + recreate API | **≈ 2–5 minutes** | Typical cold build shorter if layers cached |
| Post-deploy smoke | **0** (must pass) | Fail → rollback |
| Full rollback (git + rebuild) | **≈ 2–5 minutes** additional | Same order as deploy |

**MVP agreement:** plan maintenance for **≤ 10 minutes** end-to-end (deploy or
rollback). Postgres data volume stays mounted — do **not** `docker compose down -v`.
True zero-downtime needs a second instance or ALB (#14 / post-MVP) and is out of
scope for this low-cost single node.

Frontend (Lovable) should tolerate brief 502/503 with retry (`retryable: true`).

---

## Deploy strategy (controlled rolling restart)

```
pre-smoke ──► record rollback point ──► git sync ──► compose up -d --build api
                                                         │
                                                         ▼
                                              post-smoke (fail → rollback)
```

1. **Pre-deploy smoke** — `/health` OK; optional `/api/v1/similar-posts` 2xx/4xx
   (not 5xx); disk not critically full.
2. **Record rollback point** — current `git rev-parse HEAD` + API image id written
   under `data/deploy/LAST_GOOD.json` (created by the deploy script).
3. **Sync code** — `git fetch` + checkout target ref (tag or SHA).
4. **Rolling restart** — rebuild/recreate **api** (and migrate if needed) without
   wiping volumes:
   ```bash
   docker compose up -d --build --remove-orphans api
   docker compose run --rm migrate   # when schema changed
   ```
   Or: `sudo systemctl restart ito-stack` for a full stack bounce (longer downtime).
5. **Post-deploy smoke** — same checks; must pass within the downtime budget.
6. **On failure** — run rollback immediately (below).

Prefer API-only recreate over full `ito-stack` restart when only the API image changed.

---

## Pre-deploy checklist

- [ ] Change ticket / issue linked; target git SHA or tag known
- [ ] Backup status OK within RPO (#15) — especially before migrate
- [ ] Secrets present (`ITO_ENV_FILE` / Secrets Manager per #13, or approved `.env`)
- [ ] Owner channel notified of **≤ 10 min** maintenance window
- [ ] `python scripts/deploy_release.py --dry-run` looks sane

---

## Deploy commands (another team member)

On the Compose host (SSM Session Manager preferred):

```bash
cd /opt/ito-rnd
# optional: source runtime env
# set -a && source /run/ito/runtime.env && set +a

# Dry-run (no mutate):
python scripts/deploy_release.py --ref main --dry-run

# Live controlled deploy:
python scripts/deploy_release.py --ref <git-sha-or-tag>
```

Manual equivalent:

```bash
curl -sf localhost:8000/health
git rev-parse HEAD > /tmp/ito-prev-sha
git fetch origin && git checkout <git-sha-or-tag>
docker compose up -d --build --remove-orphans api
curl -sf localhost:8000/health
# smoke similar-posts (expect not 5xx):
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/v1/similar-posts \
  -H 'Content-Type: application/json' \
  -d '{"content":"deploy smoke"}'
```

---

## Post-deploy smoke checks

| Check | Pass criteria |
| ----- | ------------- |
| `GET /health` | HTTP 200, body contains ok/healthy status |
| `POST /api/v1/similar-posts` | Not 5xx (2xx or 4xx validation OK) |
| Compose | `api` (and `db`) Up / healthy |
| Optional | `GET /metrics` returns 200 when telemetry enabled |

Script flag: `python scripts/deploy_release.py ...` runs these automatically.

---

## Rollback — decision criteria

**Rollback immediately if any of:**

| Trigger | Why |
| ------- | --- |
| Post-deploy `/health` fails for **> 2 minutes** | API unusable |
| similar-posts or evaluate returning sustained **5xx** | Error budget burn |
| Crash-loop / OOM on `api` container | Unstable release |
| Bad migrate / data errors after deploy | Prefer restore drill (#15) if data corrupt |

**Do not rollback solely for:** cosmetic UI, non-prod log noise, or a single
transient 5xx that clears on retry.

### Rollback command

```bash
cd /opt/ito-rnd
python scripts/rollback_release.py
# or explicit SHA from LAST_GOOD.json:
python scripts/rollback_release.py --ref <previous-sha>
```

Manual:

```bash
PREV=$(cat data/deploy/LAST_GOOD.json | python -c 'import sys,json;print(json.load(sys.stdin)["git_sha"])')
git checkout "$PREV"
docker compose up -d --build --remove-orphans api
curl -sf localhost:8000/health
```

---

## Rollback drill (acceptance)

Run at least once in staging or a controlled local/Compose environment:

```bash
python scripts/run_deploy_drill.py --simulate
# Against a live stack (staging):
python scripts/run_deploy_drill.py --live --base-url http://127.0.0.1:8000
```

This writes [`DEPLOY_DRILL_LATEST.json`](DEPLOY_DRILL_LATEST.json) with timings.
**Pass:** simulated or live drill `ok=true` and documented downtime ≤ 10 minutes
expectation (live wall clock recorded when `--live`).

---

## Related issues (do not reinvent)

| Topic | Issue |
| ----- | ----- |
| Host / Terraform | #12 |
| Secrets | #13 |
| HTTPS / SG hardening | #14 |
| Backup before risky migrate | #15 |
| CloudWatch paging | #16 |
| Cost guardrails | #18 |
| Go-live checklist uses this runbook | #27 |

---

## Acceptance mapping (#20)

| Criterion | Deliverable |
| --------- | ----------- |
| Runbook executable by another teammate | This doc + `deploy_release.py` / `rollback_release.py` |
| Rollback tested once (staging/controlled) | `run_deploy_drill.py` + `DEPLOY_DRILL_LATEST.json` |
| Downtime expectations documented | Table above (≤ 10 minutes MVP window) |
