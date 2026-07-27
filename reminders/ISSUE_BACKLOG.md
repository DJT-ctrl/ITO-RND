# Issue Backlog — requirements reference

**Repository (canonical):** [intotheopen/intotheopen-backend](https://github.com/intotheopen/intotheopen-backend)
**Source of truth:** [reminders/ISSUES.yaml](ISSUES.yaml) (this file is auto-generated; do not edit manually)
**Workflow:** [FOR_AI.md](FOR_AI.md) + [GIT_ISSUE_WORKFLOW.md](GIT_ISSUE_WORKFLOW.md) — **one issue → one PR**.

---

## Issue #11 — AWS runtime ADR

**Issue:** [intotheopen/intotheopen-backend#11](https://github.com/intotheopen/intotheopen-backend/issues/11)
**Branch:** `feature/issue-11-aws-runtime-adr`
**Docs:** [`docs/ops/ADR-001-aws-runtime.md`](../docs/ops/ADR-001-aws-runtime.md)

### Why

Before go-live, the team should align on a concrete AWS architecture to avoid rework and unclear ownership.

### Scope

- Decide target runtime (single EC2 Docker Compose vs ECS Fargate)
- Define networking boundary, ingress path, and trust boundaries
- Produce an ADR with trade-offs, migration path, and operational owner model

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| ADR approved with chosen target architecture | ADR-001 **Accepted (MVP): EC2 + Docker Compose** |
| Deployment and rollback path documented | ADR sections + detailed runbook in **#20** |
| Security assumptions and constraints listed | ADR 'Security assumptions & constraints' |

### Execution order

- Start cloud track here first (architecture decision)
- Blocks: **#12** and **#20** design assumptions
- Keep lightweight for low-budget MVP path

---

## Issue #12 — AWS IaC

**Issue:** [intotheopen/intotheopen-backend#12](https://github.com/intotheopen/intotheopen-backend/issues/12)
**Branch:** `feature/issue-12-aws-iac`
**Docs:** [`infra/README.md`](../infra/README.md)

### Why

Manual AWS setup is error-prone and hard to reproduce. Infrastructure should be provisioned declaratively.

### Scope

- Provision VPC, subnets, routes, security groups, IAM, instance profile, storage via Terraform
- Least-privilege defaults and tagging standards
- Plan/apply workflow and env separation (dev/staging/prod)

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| Fresh environment from code only | `infra/terraform` + bootstrap in `infra/README.md` |
| Drift detection in CI/CD | `.github/workflows/terraform.yml` (`plan -detailed-exitcode`) |
| Bootstrap and teardown docs | `infra/README.md` |

### Execution order

- Do immediately after **#11**
- Blocks practical execution of: **#13**, **#14**, **#15**, **#16**, **#18**, **#19**, **#20**
- This is the cloud foundation issue

---

## Issue #13 — AWS secrets

**Issue:** [intotheopen/intotheopen-backend#13](https://github.com/intotheopen/intotheopen-backend/issues/13)
**Branch:** `feature/issue-13-aws-secrets`
**Docs:** [`deploy/SECRETS.md`](../deploy/SECRETS.md)

### Why

Production credentials must come from Secrets Manager, not durable `.env` files.

### Scope

- Store runtime secrets in AWS Secrets Manager
- Inject runtime env values ephemerally
- Define credential rotation and validation flow

---

## Issue #14 — HTTPS ingress hardening

**Issue:** [intotheopen/intotheopen-backend#14](https://github.com/intotheopen/intotheopen-backend/issues/14)
**Branch:** `feature/issue-14-https-ingress`
**Docs:** [`docs/ops/INGRESS_HTTPS.md`](../docs/ops/INGRESS_HTTPS.md)

### Why

Production traffic should terminate TLS at the edge and keep app/database ports private by default.

### Scope

- Enforce HTTPS redirect and TLS termination at ingress
- Restrict public ingress to 80/443 and block direct app/db access
- Document WAF deferral and follow-up scope

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| Ingress config enforces TLS and redirect | `deploy/nginx/ito-api.conf` + install script |
| Security group ingress policy is documented | `infra/ingress/sg_allowlist.json` |
| Operational guidance is published | `docs/ops/INGRESS_HTTPS.md` |

### Execution order

- Depends on **#12** infrastructure baseline
- Feeds WAF follow-up in **#17**
- Keep app and database listeners private

---

## Issue #15 — Backup / DR

**Issue:** [intotheopen/intotheopen-backend#15](https://github.com/intotheopen/intotheopen-backend/issues/15)
**Branch:** `feature/issue-15-aws-backup-dr`
**Docs:** [`docs/ops/BACKUP_DR.md`](../docs/ops/BACKUP_DR.md)

### Why

Stateful services need explicit backup and restore guarantees before production traffic.

### Scope

- Document RPO and RTO targets
- Ensure scheduled backup jobs and restore drill workflow are defined
- Keep DR validation in the release readiness path

---

## Issue #16 — CloudWatch logs & alarms

**Issue:** [intotheopen/intotheopen-backend#16](https://github.com/intotheopen/intotheopen-backend/issues/16)
**Branch:** `feature/issue-16-cloudwatch-logs-alarms`
**Docs:** [`docs/ops/CLOUDWATCH.md`](../docs/ops/CLOUDWATCH.md)

### Why

Cloud operations need first-class observability and alerting integrated with AWS-native tooling.

### Scope

- Ship app/system logs to CloudWatch with retention policy
- Define CloudWatch alarms for API error rate, latency, host health, and disk pressure
- Connect alert destinations (SNS / Slack / PagerDuty)

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| Critical alerts fire in a controlled test | `scripts/test_cloudwatch_alarms.py` (+ `--live` SNS check) |
| Dashboards include API and host health | `infra/observability/dashboard.tf` |
| On-call runbook links alarm → diagnosis → mitigation | `docs/ops/CLOUDWATCH.md` |

### Execution order

- After **#12** (Compose host instance id / IAM role)
- Can run in parallel with **#15** and **#18**
- Feeds go-live observability sign-off in **#27**

---

## Issue #21 — Load baseline

**Issue:** [intotheopen/intotheopen-backend#21](https://github.com/intotheopen/intotheopen-backend/issues/21)
**Branch:** `feature/issue-21-load-baseline`
**Docs:** [`docs/ops/LOAD_BASELINE.md`](../docs/ops/LOAD_BASELINE.md)

### Why

After frontend launch, real user traffic can expose latency bottlenecks and contention patterns not seen in local tests.

### Scope

- Add realistic load scenarios for `/api/v1/similar-posts` and `/api/v1/evaluate`
- Profile hot paths and identify top 3 bottlenecks
- Define target p95 latency and throughput for next release

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| Reproducible load test scripts exist | `scripts/load/run_load_test.py` + `scenarios.yaml` (+ optional stub API) |
| Baseline performance report is published | `docs/ops/LOAD_BASELINE.md` |
| Improvement plan with measurable targets is captured | Same doc → feeds tuning work in **#22** |

### Execution order

- Start after launch baseline is stable
- Prefer after **#5** and **#8** are active so measurements are trustworthy
- Feeds tuning work in **#22**

---

## Issue #22 — Orchestrator latency

**Issue:** [intotheopen/intotheopen-backend#22](https://github.com/intotheopen/intotheopen-backend/issues/22)
**Branch:** `feature/issue-22-orchestrator-latency`
**Docs:** [`docs/ops/ORCHESTRATOR_LATENCY.md`](../docs/ops/ORCHESTRATOR_LATENCY.md)

### Why

After launch, orchestrator response times and fallback behaviour under load need to be measured and tuned to meet user-facing SLOs.

### Scope

- Profile end-to-end latency for `/api/v1/similar-posts` and `/api/v1/evaluate`
- Identify top bottlenecks in provider initialisation and corpus lookup
- Define and enforce timeout/fallback policy

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| Baseline latency measured and documented | `docs/ops/ORCHESTRATOR_LATENCY.md` |
| Timeout/fallback policy defined and enforced in code | `config/settings.py` + orchestrator guard |
| Regression test prevents silent regressions | `tests/test_orchestrator_latency.py` |

### Execution order

- Start after **#21** load baseline is available
- Feeds SLO definitions in **#8**

---
