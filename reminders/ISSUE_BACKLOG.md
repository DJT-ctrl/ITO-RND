# Issue Backlog — 27 issues

**Repository (canonical):** [intotheopen/intotheopen-backend](https://github.com/intotheopen/intotheopen-backend)  
**Issues:** https://github.com/intotheopen/intotheopen-backend/issues  
**Workflow:** [FOR_AI.md](FOR_AI.md) + [GIT_ISSUE_WORKFLOW.md](GIT_ISSUE_WORKFLOW.md) — **one issue → one PR**.

Tick the checkbox when the issue is **closed on GitHub** (PR merged with `Closes #N`).

---

## P0 — Critical

| Done | # | Title | Labels |
| ---- | - | ----- | ------ |
| [ ] *(PR [#29](https://github.com/intotheopen/intotheopen-backend/pull/29) open)* | [#1](https://github.com/intotheopen/intotheopen-backend/issues/1) | Stabilize agent provider initialization (remove import-time crash path) | bug, P0, api, agents, stabilization |
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

## Progress summary

| Priority | Count | Closed |
| -------- | ----- | ------ |
| P0 | 4 | 0 |
| P1 | 17 | 0 |
| P2 | 6 | 0 |
| **Total** | **27** | **0** |

_Update this table when issues close._
