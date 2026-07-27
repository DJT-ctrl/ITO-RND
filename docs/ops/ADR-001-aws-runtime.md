# ADR-001: Target AWS runtime architecture (EC2 Compose vs ECS)

| Field | Value |
| ----- | ----- |
| **ADR** | ADR-001 |
| **Issue** | [#11](https://github.com/intotheopen/intotheopen-backend/issues/11) |
| **Status** | **Accepted** (MVP) — merge of this PR is the approval record |
| **Date** | 2026-07-17 |
| **Owners** | Backend / DevOps (day-2 ops); Tech Lead (architecture changes) |
| **Blocks** | [#12](https://github.com/intotheopen/intotheopen-backend/issues/12) IaC, [#20](https://github.com/intotheopen/intotheopen-backend/issues/20) deploy/rollback runbook |
| **Related** | [#13](https://github.com/intotheopen/intotheopen-backend/issues/13) secrets, [#14](https://github.com/intotheopen/intotheopen-backend/issues/14) ingress, [#15](https://github.com/intotheopen/intotheopen-backend/issues/15) backup/DR |

## Context

IntoTheOpen already ships a **single-host Docker Compose monolith**
(Postgres + FastAPI + local Prometheus/Grafana) with systemd
(`deploy/ito-stack.service`). Before go-live we must pick a concrete AWS
runtime so IaC (#12), secrets (#13), backups (#15), and the deploy runbook
(#20) share one set of assumptions.

Constraints (from labels / milestone):

- **budget:low-cost-mvp** — prefer one small instance over managed container platform cost.
- Team size small — minimize operational surface area until traffic justifies complexity.
- Stateful Postgres today is **on-instance** (EBS bind mount via `DB_DATA_PATH`), not RDS.

## Decision

**MVP target runtime: one EC2 instance running the existing Docker Compose stack,
supervised by systemd.**

| Concern | MVP choice |
| ------- | ---------- |
| Compute | Single EC2 (Amazon Linux 2023 or Ubuntu LTS), Docker Engine + Compose v2 |
| Process supervisor | `ito-stack.service` → `docker compose up -d` |
| Data | EBS volume mounted at `DB_DATA_PATH` (Postgres); optional second volume for backups staging |
| Secrets | AWS Secrets Manager → ephemeral runtime env (#13) — not durable `.env` on disk |
| Ingress | Security group + host Nginx (or ALB later in #14); API on `:8000` localhost behind proxy |
| Telemetry | Compose Prometheus/Grafana on-instance (localhost-bound scrapers) |
| Backups | EBS snapshots (DLM) + logical `pg_dump` to S3 (#15) |

**Not chosen for MVP:** ECS Fargate (or ECS on EC2). Deferred as the **scale /
HA migration path** after product traction (see below).

## Alternatives considered

### A. Single EC2 + Docker Compose (chosen)

| Pros | Cons |
| ---- | ---- |
| Matches repo today — zero rewrite | Single AZ / single host = availability risk |
| Lowest fixed cost for MVP | Manual/host patching; no native task autoscaling |
| Simple mental model for backups & debugging | Vertical scaling only until migration |
| systemd + Compose already documented | Blast radius: host compromise = full stack |

### B. ECS Fargate + managed data plane

| Pros | Cons |
| ---- | ---- |
| Better isolation, rolling deploys, less host patching | Higher baseline cost; needs ALB, task defs, networking |
| Clearer path to multi-service split later | Postgres must move to RDS (or ECS is awkward for stateful DB) |
| IAM task roles fit Secrets Manager well | Large rewrite vs current Compose monolith |

**Why not B for MVP:** cost + rewrite violate low-budget path; would block
#12/#20 with months of work. ECS remains the documented **next** architecture
when RTO/availability or deploy cadence outgrow one box.

### C. ECS on EC2 / Kubernetes

Rejected for MVP — more ops overhead than Fargate or single Compose host
without proportional benefit at current scale.

## Networking boundary & trust boundaries

### MVP network sketch

```
Internet
   │
   ▼
┌─────────────────────────────────────────────────────────┐
│  Public subnet (single AZ)                              │
│  ┌───────────────────────────────────────────────────┐  │
│  │  EC2 (ito)                                        │  │
│  │  SG: 443/80 from allowed CIDRs (or 0.0.0.0/0 +    │  │
│  │       WAF later #17); SSH from bastion/admin IP   │  │
│  │                                                   │  │
│  │  Nginx (:443) ──► 127.0.0.1:8000 (api)            │  │
│  │  Compose bridge: db, migrate, api, prometheus…    │  │
│  │  Postgres/Grafana/Prom bound to 127.0.0.1 on host │  │
│  └───────────────────────────────────────────────────┘  │
│                         │                               │
│                         ▼ EBS (postgres data)           │
└─────────────────────────────────────────────────────────┘
         │
         ▼ VPC endpoints / NAT as needed for
           Secrets Manager, S3, Gemini (egress HTTPS)
```

**MVP deliberately uses one public subnet + tight security groups** (not
private-app + public-ALB). Private subnets + ALB are the **post-MVP** shape
when moving toward ECS/RDS (#14 hardening can introduce ALB earlier without
abandoning Compose).

### Trust boundaries

| Boundary | Assumption |
| -------- | ---------- |
| Internet → Nginx | TLS terminate at Nginx (or ALB); only `/` API routes public |
| Nginx → API | Loopback only; no direct public `:8000` in production SG |
| API → Postgres | Compose network only; host port `127.0.0.1:5432` for admin |
| API → Gemini / Apify | Egress HTTPS; keys from Secrets Manager (#13) |
| Humans → host | SSH from allowlisted IPs or SSM Session Manager (preferred) |
| CI → prod | No automatic prod deploy from PR merge until #20/#27 gates |

## Security assumptions & constraints

Explicit assumptions for #12 / #14 / #27:

1. **One trusted operator identity** initially (shared break-glass IAM + SSM);
   no multi-tenant host access.
2. **No production secrets in git or durable `.env`** — Secrets Manager only (#13).
3. **Postgres is not internet-exposed** — SG denies 5432 from `0.0.0.0/0`.
4. **Image builds do not bake secrets** (existing `.dockerignore`).
5. **API auth / rate limits** (#3) assumed before broad frontend exposure;
   this ADR does not replace application auth.
6. **Single-AZ acceptance:** MVP RPO/RTO from #15 (≤24h / ≤4h) bound recovery;
   Multi-AZ RDS is out of scope until ECS/RDS migration.
7. **IMDSv2 required** on the instance; instance role least-privilege
   (Secrets Manager get, S3 backup put/get, optional SSM).
8. **Patch cadence:** OS + Docker security updates at least weekly
   (manual or SSM patch) — owner: DevOps.
9. **WAF / advanced edge** deferred to #17; HTTPS + SG is the MVP floor (#14).

## Deployment path (MVP)

Documented in detail under #20; this ADR fixes the **shape**:

1. Provision EC2 + EBS + IAM instance profile + SG (#12 IaC).
2. Install Docker, clone repo to `/opt/ito-rnd`, configure systemd units.
3. Materialize secrets → start `ito-stack` → run migrate/ingest as needed.
4. Point DNS / Nginx at the instance; verify `GET /health`.
5. Enable backup timer + DLM snapshots (#15).

**Rollback path (MVP):**

| Failure | Rollback |
| ------- | -------- |
| Bad API image / compose change | `git checkout <prev-sha>` + `systemctl restart ito-stack` (or previous Compose project tag) |
| Bad config / secret | Revert secret version in Secrets Manager; re-fetch; restart stack |
| Data corruption | Restore logical dump or EBS snapshot per #15 playbook |
| Instance loss | Launch replacement from IaC AMI/user-data; attach/restore EBS or S3 dump |

ECS-style blue/green is **not** required for MVP rollback.

## Migration path (Compose → ECS Fargate)

Trigger when any of: sustained multi-instance need, RTO ≪ 4h, or deploy
frequency makes host restarts unacceptable.

1. Move Postgres to **RDS Postgres + pgvector** (or Aurora) — hard prerequisite.
2. Build/push API image to ECR; task definition with Secrets Manager refs.
3. ALB → Fargate service in private subnets; egress via NAT.
4. Retire on-instance Prometheus or replace with AMP/CloudWatch (#16).
5. Keep Compose as **local/dev** parity; prod Compose decommissioned.

Until that migration ADR is written, **all cloud issues assume EC2 Compose**.

## Operational owner model

| Area | Primary owner | Escalation |
| ---- | ------------- | ---------- |
| Architecture changes to this ADR | Tech Lead | CTO |
| EC2 / SG / IAM / DNS | DevOps | Tech Lead |
| Application deploys & API health | Backend | DevOps |
| Secrets rotation | DevOps (+ Backend for app keys) | Tech Lead |
| Backup / restore drills | DevOps | Backend (data validation) |
| On-call (MVP) | Shared Backend/DevOps rotation | — |

## Consequences

**Positive**

- Unblocks #12 / #20 with a single, cheap target.
- Aligns with existing Compose + systemd assets.
- Clear deferral criteria for ECS.

**Negative / accepted risks**

- Single host / single AZ until migration.
- Ops load includes OS patching and Docker engine care.
- Vertical scaling ceiling.

## Acceptance mapping (#11)

| Criterion | Where |
| --------- | ----- |
| ADR approved with chosen target | This document — **Accepted (MVP): EC2 + Docker Compose** |
| Deployment and rollback path documented | Sections above; detailed runbook in **#20** |
| Security assumptions and constraints listed | “Security assumptions & constraints” + trust boundaries |

## Approval

| Role | Decision |
| ---- | -------- |
| Engineering (this PR) | Accept EC2 Compose for MVP |
| Follow-ups | #12 implements IaC for this shape; revisit ECS when migration triggers fire |
