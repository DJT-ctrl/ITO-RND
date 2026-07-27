# Issue Backlog — 27 issues

**Repository (canonical):** [intotheopen/intotheopen-backend](https://github.com/intotheopen/intotheopen-backend)  
**Issues:** https://github.com/intotheopen/intotheopen-backend/issues  
**Workflow:** [FOR_AI.md](FOR_AI.md) + [GIT_ISSUE_WORKFLOW.md](GIT_ISSUE_WORKFLOW.md) — **one issue → one PR**.

Tick the checkbox when the issue is **closed on GitHub** (PR merged with `Closes #N`).

### Merge conflicts — stay wary

Open issues often share files (`api/main.py`, tests, `.gitignore`, CI). Resolving
one PR against `main` (or updating a stacked base branch) can leave **other** open
PRs conflicting — or GitHub can report a conflict even when the branch is clean
vs `main` because the PR base is another feature branch.

**Before and after any conflict fix:** check *all* open PRs’ mergeable status
(without merging to `main`), keep both sides’ intent when resolving, and recheck
siblings so fixing one does not silently break another. Full checklist:
[GIT_ISSUE_WORKFLOW.md — Merge conflicts](GIT_ISSUE_WORKFLOW.md#merge-conflicts--check-before-and-after).

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

## Issue #13 — requirements (AWS secrets)

**Issue:** [intotheopen/intotheopen-backend#13](https://github.com/intotheopen/intotheopen-backend/issues/13)  
**Branch:** `feature/issue-13-aws-secrets`  
**Docs:** [`deploy/SECRETS.md`](../deploy/SECRETS.md)

### Why

Environment secrets in plain files are not safe for cloud production.

### Scope

- Move runtime secrets to AWS Secrets Manager (JSON secret).
- Inject at runtime via ephemeral env file / optional in-process fetch (not baked into images).
- Define rotation policy for DB/API credentials.

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| No production secrets in repo or server-side `.env` | Ephemeral `/run/ito/runtime.env`; example JSON placeholders only |
| App reads secrets from managed AWS secret store | `scripts/fetch_aws_secrets.py` + `config.aws_secrets` / `ITO_ENV_FILE` |
| Rotation playbook tested end-to-end | `deploy/SECRETS.md` + `tests/test_aws_secrets.py` dry-run |

### Execution order (from issue comment)

- Prioritize early once **#12** exists.
- Should be complete before production deploy runbook (**#20**).
- Feeds security sign-off in **#27**.

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

## Issue #18 — requirements (AWS budget alerts)

**Issue:** [intotheopen/intotheopen-backend#18](https://github.com/intotheopen/intotheopen-backend/issues/18)  
**Branch:** `feature/issue-18-aws-budget-alerts`  
**Docs:** [`docs/ops/COST_CONTROLS.md`](../docs/ops/COST_CONTROLS.md) · Terraform: [`infra/budgets/`](../infra/budgets/)

### Why

Low-budget operation requires explicit cost guardrails to avoid unexpected AWS spend.

### Scope

- Define monthly budget threshold and service-level budget split.
- Configure AWS Budgets with forecast alerts.
- Add actionable response playbook for budget alerts.

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| Budget alarms notify owner channels before overrun | `infra/budgets` (50/80/100 ACTUAL + FORECASTED → SNS) |
| Monthly cloud cost report is generated and reviewed | `scripts/generate_monthly_cost_report.py` + `docs/ops/cost-reports/` |
| Cost control steps are documented | `docs/ops/COST_CONTROLS.md` |

### Execution order (from issue comment)

- After **#12** exists (real spend to guard).
- Parallel with **#15** / **#16**.
- Feeds cost sign-off in **#27**.

---

## Issue #20 — requirements (deploy & rollback runbook)

**Issue:** [intotheopen/intotheopen-backend#20](https://github.com/intotheopen/intotheopen-backend/issues/20)  
**Branch:** `feature/issue-20-deploy-rollback-runbook`  
**Docs:** [`docs/ops/DEPLOY_ROLLBACK.md`](../docs/ops/DEPLOY_ROLLBACK.md)

### Why

A single-instance low-cost deployment still needs a repeatable release path.

### Scope

- Define deploy strategy (blue/green-lite or controlled rolling restart) for single-node setup.
- Add pre-deploy and post-deploy smoke checks.
- Define rollback command and decision criteria.

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| Deployment runbook can be executed by another team member | `DEPLOY_ROLLBACK.md` + `deploy_release.py` / `rollback_release.py` |
| Rollback tested at least once in staging or controlled environment | `run_deploy_drill.py` + `DEPLOY_DRILL_LATEST.json` |
| Downtime window expectations documented | ≤ 10 minutes MVP window in runbook |

### Execution order (from issue comment)

- Near end of Milestone 4 after **#11**, **#12**, **#13**.
- Must include rollback and smoke checks used by **#27**.
- Treat as operational readiness evidence.

---

## Issue #14 — requirements (HTTPS ingress + strict SGs)

**Issue:** [intotheopen/intotheopen-backend#14](https://github.com/intotheopen/intotheopen-backend/issues/14)  
**Branch:** `feature/issue-14-https-ingress`  
**Docs:** [`docs/ops/INGRESS_HTTPS.md`](../docs/ops/INGRESS_HTTPS.md)

### Why

Public APIs require TLS termination, controlled ingress, and baseline edge protection.

### Scope

- Configure certificates and HTTPS-only ingress (Nginx + Let's Encrypt on-host for MVP).
- Strict security groups (80/443 only publicly; API on localhost).
- Evaluate AWS WAF — **defer enablement to #17** (issue title / low-cost MVP).

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| API is reachable only over HTTPS | `deploy/nginx/ito-api.conf` TLS → `127.0.0.1:8000` |
| HIssue #22 — requirements (orchestrator latency)

**Issue:** [intotheopen/intotheopen-backend#22](https://github.com/intotheopen/intotheopen-backend/issues/22)  
**Branch:** `feature/issue-22-orchestrator-latency`  
**Docs:** [`docs/ops/ORCHESTRATOR_LATENCY.md`](../docs/ops/ORCHESTRATOR_LATENCY.md)

### Why

After launch, orchestrator response times and fallback behaviour under load need
to be measured and tuned to meet user-facing SLOs.

### Scope

- Profile end-to-end latency for `/api/v1/similar-posts` and `/api/v1/evaluate`.
- Identify top bottlenecks in provider initialisation and corpus lookup.
- Define and enforce timeout/fallback policy.

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| Baseline latency measured and documented | `docs/ops/ORCHESTRATOR_LATENCY.md` |
| Timeout/fallback policy defined and enforced in code | `config/settings.py` + orchestrator guard |
| Regression test prevents silent regressions | `tests/test_orchestrator_latency.py` |

### Execution order (from issue comment)

- Start after **#21** load baseline is available.
- Feeds SLO definitions in **#8**.

---

## TTP is redirected or blocked | `return 301 https://…` on port 80 |
| WAF and security group rules are documented and tested | WAF → #17 in runbook; `sg_allowlist.json` + hardening tests |

### Execution order

- After **#12** (host + SG) and alongside **#20** (deploy).
- WAF enablement tracked separately in **#17**.

---

## Issue #17 — requirements (AWS WAF post-launch)

**Issue:** [intotheopen/intotheopen-backend#17](https://github.com/intotheopen/intotheopen-backend/issues/17)  
**Branch:** `feature/issue-17-aws-waf`  
**Docs:** [`docs/ops/WAF.md`](../docs/ops/WAF.md) · Terraform: [`infra/waf/`](../infra/waf/)

### Why

For low-budget launch, WAF and advanced edge policies can be deferred, but should
be tracked as explicit post-launch hardening.

### Scope

- Add AWS WAF managed rule groups tuned for API traffic.
- Add stricter bot/rate controls at edge layer.
- Validate false-positive impact with staged rollout (COUNT → BLOCK).

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| WAF deployed and attached to production ingress | `infra/waf` Web ACL + ALB association (`alb_arn`) |
| Baseline managed rules enabled and tuned | Managed groups + rate limit + `enable_blocking` |
| Runbook includes block/allow exception process | `docs/ops/WAF.md` |

### Execution order

- After launch / after **#14** HTTPS path; requires ALB (or CloudFront) in front of EC2.
- Watch cost vs **#18** before enabling Block in prod.

---

## Issue #19 — requirements (EC2/EBS rightsizing)

**Issue:** [intotheopen/intotheopen-backend#19](https://github.com/intotheopen/intotheopen-backend/issues/19)  
**Branch:** `feature/issue-19-ec2-ebs-rightsizing`  
**Docs:** [`docs/ops/RIGHTSIZING.md`](../docs/ops/RIGHTSIZING.md)

### Why

Cloud spend can drift from idle resources and oversized instance/storage choices.

### Scope

- Right-size EC2 and EBS for baseline traffic.
- Add stop/start and cleanup policy for non-production environments.
- Document periodic rightsizing review checklist.

### Acceptance criteria

| Criterion | Deliverable |
| --------- | ----------- |
| Baseline instance/storage class selected with rationale | `baseline.json` + runbook table (`t3.small` / gp3) |
| Non-prod idle resource policy implemented | `idle_policy.json` + `apply_nonprod_idle_policy.py` |
| Monthly rightsizing review cadence in place | `run_rightsizing_review.py` + `docs/ops/rightsizing-reviews/` |

### Execution order

- Post-launch hardening; pairs with **#18** monthly cost review.
- Uses host defaults from **#12**.

---

## Progress summary

| Priority | Count | Closed |
| -------- | ----- | ------ |
| P0 | 4 | 0 |
| P1 | 17 | 0 |
| P2 | 6 | 0 |
| **Total** | **27** | **0** |

_Update this table when issues close._
