# Data retention & sensitive-data governance

**Issue:** [#26](https://github.com/intotheopen/intotheopen-backend/issues/26)  
**Audience:** operators, onboarding engineers, AI agents working in this repo  
**Driver:** internal R&D / ops — maximize retention for the corpus and feedback
loop. This is **not** a formal GDPR/CCPA compliance program (yet).

Approval for Milestone 1 is via PR review on the issue (`Closes #26`).

---

## Principles

1. **Retain by default.** Business data (scrapes, corpus, Postgres, validation,
   feedback, backups, app telemetry JSONL) is kept **indefinitely** until an
   operator deliberately deletes it.
2. **Deletion is manual and intentional.** There are no automated purge or TTL
   jobs for business datasets in this milestone.
3. **No PII masking / LLM name-blocking.** Author identifiers and post text are
   stored and passed to models as-is. Prompt-injection wrapping
   (`agents/prompt_safety.py`) is **not** redaction.
4. **Secrets are not data.** Credentials live in `.env` (local) or a managed
   secret store (production — see [#13](https://github.com/intotheopen/intotheopen-backend/issues/13)).
5. **Disk is the constraint.** Unlimited retention can fill a small instance;
   monitor disk and rightsizing ([#19](https://github.com/intotheopen/intotheopen-backend/issues/19)).

---

## Data inventory

| Store | Location | Sensitive fields | Retention | Who can access |
| ----- | -------- | ---------------- | --------- | -------------- |
| Raw scrapes | `data/raw/` | post text, `author_public_id`, URLs | Indefinite (manual) | Local/EC2 operator (gitignored) |
| Processed corpus | `data/processed/` | same + engagement stats | Indefinite | Repo readers (samples committed); operators for live runs |
| Embeddings | `data/embeddings/` | derived vectors | Indefinite | Local/EC2 operator |
| Postgres corpus | `posts`, `profiles` | `content`, `author_public_id`, `linkedin_url` | Indefinite | DB credentials holders; API tenants when [#9](https://github.com/intotheopen/intotheopen-backend/issues/9) lands |
| Validation loop | `predictions`, `prediction_feedback`, clusters, snapshots | post content + author ids | Indefinite | DB credentials holders |
| Pre-ingest backups | `data/db_backups/` | full DB dump | Indefinite | Local/EC2 operator |
| Telemetry / audit | `data/telemetry/` | costs, override audit JSONL | Indefinite | Local/EC2 operator — **do not delete** audit JSONL ([runbook](../current%20md/10_PRODUCTION_RUNBOOK.md)) |
| Validation scrapes | `data/validation/` | same as raw | Indefinite | Local/EC2 operator |
| Postgres volume | `DB_DATA_PATH` (default `./data/pgdata`) | all tables | Indefinite | Host filesystem + DB password |
| Prometheus TSDB | Docker volume `prometheus_data` | request/host metrics only | **Indefinite by default** (`PROMETHEUS_RETENTION_TIME=0`) | Localhost `:9090` |
| Grafana state | Docker volume `grafana_data` | dashboards, admin session | Indefinite | Grafana admin password |
| Secrets | `.env` (not committed) | see checklist below | N/A (rotate on exposure) | Machine owner / secrets store |

**Profile cache note:** `PROFILE_CACHE_STALENESS_DAYS` (default 30) triggers a
**re-scrape**, not row deletion. Cached `profiles` rows are retained.

**CI note:** integration CI (when present) uses an ephemeral Postgres volume for
test isolation. That is **not** the production retention policy.

---

## Retention windows (policy)

| Class | Window |
| ----- | ------ |
| Raw / processed / embeddings / validation files | Indefinite until manual purge |
| Postgres (`posts`, `profiles`, predictions, feedback, …) | Indefinite until manual purge |
| `data/db_backups/` dumps | Indefinite until manual purge (prefer keep last N if disk is tight) |
| `data/telemetry/` (incl. feedback override audit) | Indefinite; do not delete audit JSONL during incidents |
| Prometheus metrics | Default **unlimited** (`PROMETHEUS_RETENTION_TIME=0`). Operators on small disks may set e.g. `90d` or `365d` in `.env`. |
| Grafana / named telemetry volumes | Survive `docker compose down`; wiped only by `docker compose down -v` |

Automated backup/DR scheduling is **out of scope** here — tracked in
[#15](https://github.com/intotheopen/intotheopen-backend/issues/15).

---

## Sensitive-data classification

### Credentials (highest sensitivity)

| Secret | Env var | Notes |
| ------ | ------- | ----- |
| LinkedIn session cookies | `LINKEDIN_COOKIES` | Treat like a password; prefer no-cookie Apify actors when possible |
| Apify token | `APIFY_API_TOKEN` | |
| Gemini API key | `GEMINI_API_KEY` | |
| Postgres password | `POSTGRES_PASSWORD` / `DATABASE_URL` | |
| Grafana admin | `GRAFANA_ADMIN_PASSWORD` | |
| API keys (when auth enabled) | `API_KEYS_JSON` | See [#3](https://github.com/intotheopen/intotheopen-backend/issues/3) |

### Scraped identifiers (stored as-is)

- `author_public_id`, `linkedin_url`, post `content`, headlines, locations
- **No masking** in this milestone (no LLM name-blocking step)

`wrap_untrusted_text` in `agents/prompt_safety.py` only reduces prompt-injection
risk; it does not redact names or PII.

---

## Secrets handling checklist (onboarding)

- [ ] Copy `.env.example` → `.env`; never commit `.env` or real cookie JSON
- [ ] Leave `LINKEDIN_COOKIES` empty unless a specific actor requires it
- [ ] If cookies are exposed (committed, pasted in chat, logged): **rotate** the
      LinkedIn session immediately and regenerate the export
- [ ] Do **not** log or print cookie values (or full `LINKEDIN_COOKIES` strings)
- [ ] Change `POSTGRES_PASSWORD` and `GRAFANA_ADMIN_PASSWORD` before any
      non-local use
- [ ] Production: move secrets to AWS Secrets Manager / SSM — [#13](https://github.com/intotheopen/intotheopen-backend/issues/13)
- [ ] Prefer binding Postgres and telemetry ports to localhost; restrict EC2
      security groups (see [README.md](README.md))

---

## Intentional deletion paths

These wipe data **on purpose**. Prefer backups first (`storage/db_backup.py`).

| Action | What it removes |
| ------ | --------------- |
| `python -m validation_pipeline.jobs.run_bulk_import --reset …` | Validation + feedback tables via `reset_validation_data` |
| `validation_pipeline.reset.reset_validation_data` | `prediction_feedback`, snapshots, `predictions`, `prediction_clusters` |
| `docker compose down -v` | Named volumes only (`prometheus_data`, `grafana_data`) — **not** `DB_DATA_PATH` bind mount |
| Manual `rm` under `data/raw`, `data/processed`, … | Host files you delete |
| Dropping/recreating Postgres volume / `DB_DATA_PATH` | Entire database |

**Incident guidance:** if calibration MAE worsens, keep feedback records — do
**not** delete `prediction_feedback` (see
[10_PRODUCTION_RUNBOOK.md](../current%20md/10_PRODUCTION_RUNBOOK.md)).

---

## Disk & ops guidance

Unlimited retention implies growing disk use (Postgres, embeddings, Prometheus).

- Monitor free space on the host / EBS volume
- Rightsizing and idle resources: [#19](https://github.com/intotheopen/intotheopen-backend/issues/19)
- Cost alerts: [#18](https://github.com/intotheopen/intotheopen-backend/issues/18)
- Automated backup + restore drills: [#15](https://github.com/intotheopen/intotheopen-backend/issues/15)
- If Prometheus fills the disk, set `PROMETHEUS_RETENTION_TIME=90d` (or similar)
  in `.env` and recreate the prometheus container

---

## Implementation map

| Policy area | Status in this repo | Related issues |
| ----------- | ------------------- | -------------- |
| Retention policy documented | Done (this file) | #26 |
| Secrets onboarding checklist | Done (this file + `.env.example`) | #26, #13 |
| PII / name masking | Deferred (explicitly out of scope) | open new issue if compliance requires |
| Automated purge / TTL jobs | Deferred | ops / #15 |
| AWS backup & DR | Deferred | #15 |
| Managed secrets in AWS | Deferred | #13 |
| Tenant isolation of `user_id` | Separate | #9 |
| API auth for data access | Separate | #3 |

---

## Explicitly deferred

| Item | Reason |
| ---- | ------ |
| LLM author/name masking | Avoids an extra pipeline step; not needed for internal ops |
| Automated retention/purge jobs | Docs-only enforcement for #26 |
| GDPR erasure workflow | Internal ops driver only for now |
| AWS backup automation | [#15](https://github.com/intotheopen/intotheopen-backend/issues/15) |
| Secrets Manager migration | [#13](https://github.com/intotheopen/intotheopen-backend/issues/13) |
