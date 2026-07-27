# Issue Backlog — 27 issues

**Repository (canonical):** [intotheopen/intotheopen-backend](https://github.com/intotheopen/intotheopen-backend)  
**Issues:** https://github.com/intotheopen/intotheopen-backend/issues  
**Workflow:** [FOR_AI.md](FOR_AI.md) + [GIT_ISSUE_WORKFLOW.md](GIT_ISSUE_WORKFLOW.md) — **one issue → one PR**.

Tick the checkbox when the issue is **closed on GitHub** (PR merged with `Closes #N`).

---

## P0 — Critical

| Done | # | Title | Labels |
| ---- | - | ----- | ------ |
| [ ] | [#1](https://github.com/intotheopen/intotheopen-backend/issues/1) | Stabilize agent provider initialization (remove import-time crash path) | bug, P0, api, agents, stabilization |
| [ ] | [#3](https://github.com/intotheopen/intotheopen-backend/issues/3) | Harden API surface with auth + rate limiting before frontend exposure | enhancement, P0, api, security, stabilization |
| [ ] | [#13](https://github.com/intotheopen/intotheopen-backend/issues/13) | Implement AWS-managed secrets and credential rotation | enhancement, P0, security, aws |
| [ ] | [#15](https://github.com/intotheopen/intotheopen-backend/issues/15) | Establish AWS backup, restore, and disaster-recovery playbook | enhancement, P0, data, devops, aws |

---

## P1 — Stabilization & launch

| Done | # | Title | Labels |
| ---- | - | ----- | ------ |
| [ ] | [#2](https://github.com/intotheopen/intotheopen-backend/issues/2) | Make discoverability context resilient to DB/network outages | bug, P1, agents, data, testing, stabilization |
| [ ] | [#4](https://github.com/intotheopen/intotheopen-backend/issues/4) | Adopt reproducible Python dependency locking | enhancement, P1, devops, testing, stabilization |
| [ ] | [#5](https://github.com/intotheopen/intotheopen-backend/issues/5) | Set up CI quality gates (tests, matrix, API smoke checks) | enhancement, P1, devops, testing, stabilization |
| [ ] | [#6](https://github.com/intotheopen/intotheopen-backend/issues/6) | Define frontend-ready API contract and versioning policy | documentation, P1, api, frontend-integration, stabilization |
| [ ] | [#7](https://github.com/intotheopen/intotheopen-backend/issues/7) | Standardize API error taxonomy and response envelope | enhancement, P1, api, testing, frontend-integration, stabilization |
| [ ] | [#9](https://github.com/intotheopen/intotheopen-backend/issues/9) | Enforce tenant-safe user_id validation and authorization boundaries | bug, P1, api, data, security, stabilization |
| [ ] | [#10](https://github.com/intotheopen/intotheopen-backend/issues/10) | Add docker-compose integration test suite for critical API flows | enhancement, P1, data, devops, testing, stabilization |
| [ ] | [#11](https://github.com/intotheopen/intotheopen-backend/issues/11) | Define target AWS runtime architecture (EC2 Compose vs ECS) | enhancement, P1, devops, aws |
| [ ] | [#12](https://github.com/intotheopen/intotheopen-backend/issues/12) | Provision minimal AWS infrastructure with IaC (single-instance MVP) | enhancement, P1, devops, aws |
| [ ] | [#16](https://github.com/intotheopen/intotheopen-backend/issues/16) | Add baseline CloudWatch logs and essential alarms (MVP) | documentation, P1, devops, aws |
| [ ] | [#18](https://github.com/intotheopen/intotheopen-backend/issues/18) | Set up AWS budget alerts and monthly cost controls | enhancement, P1, devops, aws |
| [ ] | [#20](https://github.com/intotheopen/intotheopen-backend/issues/20) | Create AWS single-instance deployment and rollback runbook | documentation, P1, devops, aws |
| [ ] | [#23](https://github.com/intotheopen/intotheopen-backend/issues/23) | Define and enforce CORS trusted-origin policy for frontend integration | enhancement, P1, api, security, testing, frontend-integration |
| [ ] | [#24](https://github.com/intotheopen/intotheopen-backend/issues/24) | Add OpenAPI client generation and contract-break checks in CI | enhancement, P1, api, devops, testing, frontend-integration |
| [ ] | [#25](https://github.com/intotheopen/intotheopen-backend/issues/25) | Introduce database migration versioning and CI validation | enhancement, P1, data, devops, testing |
| [ ] | [#26](https://github.com/intotheopen/intotheopen-backend/issues/26) | Define data retention and sensitive-data governance policy | documentation, P1, data, security |
| [ ] | [#27](https://github.com/intotheopen/intotheopen-backend/issues/27) | Create end-to-end go-live readiness checklist and release gate | documentation, P1, devops, testing, frontend-integration |

---

## P2 — Post-launch / hardening

| Done | # | Title | Labels |
| ---- | - | ----- | ------ |
| [ ] | [#8](https://github.com/intotheopen/intotheopen-backend/issues/8) | Define SLOs, alerts, and runbooks for API reliability | documentation, P2, api, devops, stabilization |
| [ ] | [#14](https://github.com/intotheopen/intotheopen-backend/issues/14) | Harden AWS ingress for MVP: HTTPS + strict security groups (defer WAF) | enhancement, P2, api, security, aws |
| [ ] | [#17](https://github.com/intotheopen/intotheopen-backend/issues/17) | Enable AWS WAF and advanced edge protections after launch | enhancement, P2, security, aws, post-launch-hardening |
| [ ] | [#19](https://github.com/intotheopen/intotheopen-backend/issues/19) | Implement EC2/EBS rightsizing and idle-resource policy | enhancement, P2, devops, aws |
| [ ] | [#21](https://github.com/intotheopen/intotheopen-backend/issues/21) | Post-launch load testing and performance baseline | enhancement, P2, api, testing, performance, post-launch-hardening |
| [ ] | [#22](https://github.com/intotheopen/intotheopen-backend/issues/22) | Post-launch orchestrator latency and resilience tuning | enhancement, P2, agents, testing, performance, post-launch-hardening |

---

## Issue #21 — requirements (load baseline)

**Issue:** [intotheopen/intotheopen-backend#21](https://github.com/intotheopen/intotheopen-backend/issues/21)  
**Branch:** `feature/issue-21-load-baseline`  
**Docs:** [`docs/ops/LOAD_BASELINE.md`](../docs/ops/LOAD_BASELINE.md) · scripts: [`scripts/load/`](../scripts/load/)

### Why

After frontend launch, real user traffic can expose latency bottlenecks and
contention patterns not seen in local tests.

### Scope

- Add realistic load scenarios for `/api/v1/similar-posts` and `/api/v1/evaluate`.
- Profile hot paths and identify top 3 bottlenecks.
- Define target p95 latency and throughput for next release.

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| Reproducible load test scripts exist | `scripts/load/run_load_test.py` + `scenarios.yaml` (+ optional stub API) |
| Baseline performance report is published | `docs/ops/LOAD_BASELINE.md` |
| Improvement plan with measurable targets is captured | Same doc → feeds tuning work in **#22** |

### Execution order (from issue comment)

- Start after launch baseline is stable.
- Prefer after **#5** and **#8** are active so measurements are trustworthy.
- Feeds tuning work in **#22**.

---

## Issue #22 — requirements (orchestrator latency)

**Issue:** [intotheopen/intotheopen-backend#22](https://github.com/intotheopen/intotheopen-backend/issues/22)  
**Branch:** `feature/issue-22-orchestrator-latency`  
**Docs:** [`docs/ops/ORCHESTRATOR_LATENCY.md`](../docs/ops/ORCHESTRATOR_LATENCY.md)

### Why

After launch, orchestrator latency spikes can degrade reliability under concurrent usage.

### Scope

- Analyze slow orchestration stages and timeouts.
- Define Timeout/fallback policy for slow or failed steps.
- Preserve partial results when possible.

---

## Issue #13 — requirements (AWS secrets)

**Issue:** [intotheopen/intotheopen-backend#13](https://github.com/intotheopen/intotheopen-backend/issues/13)  
**Branch:** `feature/issue-13-aws-secrets`  
**Docs:** [`deploy/SECRETS.md`](../deploy/SECRETS.md)

### Why

Production credentials must come from Secrets Manager, not durable `.env` files.

### Scope

- Store runtime secrets in AWS Secrets Manager.
- Inject runtime env values ephemerally.
- Define credential rotation and validation flow.

---

## Issue #15 — requirements (backup / DR)

**Issue:** [intotheopen/intotheopen-backend#15](https://github.com/intotheopen/intotheopen-backend/issues/15)  
**Branch:** `feature/issue-15-aws-backup-dr`  
**Docs:** [`docs/ops/BACKUP_DR.md`](../docs/ops/BACKUP_DR.md)

### Why

Stateful services need explicit backup and restore guarantees before production traffic.

### Scope

- Document RPO and RTO targets.
- Ensure scheduled backup jobs and restore drill workflow are defined.
- Keep DR validation in the release readiness path.

---

## Issue #16 — requirements (CloudWatch logs & alarms)

**Issue:** [intotheopen/intotheopen-backend#16](https://github.com/intotheopen/intotheopen-backend/issues/16)  
**Branch:** `feature/issue-16-cloudwatch-logs-alarms`  
**Docs:** [`docs/ops/CLOUDWATCH.md`](../docs/ops/CLOUDWATCH.md) · Terraform: [`infra/observability/`](../infra/observability/)

### Why

Cloud operations need first-class observability and alerting integrated with
AWS-native tooling.

### Scope

- Ship app/system logs to CloudWatch with retention policy.
- Define CloudWatch alarms for API error rate, latency, host health, and disk pressure.
- Connect alert destinations (SNS / Slack / PagerDuty).

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| Critical alerts fire in a controlled test | `scripts/test_cloudwatch_alarms.py` (+ `--live` SNS check) |
| Dashboards include API and host health | `infra/observability/dashboard.tf` |
| On-call runbook links alarm → diagnosis → mitigation | `docs/ops/CLOUDWATCH.md` |

### Execution order (from issue comment)

- After **#12** (Compose host instance id / IAM role).
- Can run in parallel with **#15** and **#18**.
- Feeds go-live observability sign-off in **#27**.

---

## Progress summary

| Priority | Count | Closed |
| -------- | ----- | ------ |
| P0 | 4 | 0 |
| P1 | 17 | 0 |
| P2 | 6 | 0 |
| **Total** | **27** | **0** |

_Update this table when issues close._
