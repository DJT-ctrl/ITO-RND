# EC2 / EBS rightsizing & idle-resource policy

Issue **#19** — keep the low-cost MVP from drifting via oversized instances,
bloated volumes, and idle non-prod resources.

Related: monthly spend guardrails **#18**, Compose host Terraform **#12**,
deploy path **#20**.

Machine-readable baseline: [`infra/rightsizing/baseline.json`](../../infra/rightsizing/baseline.json).

---

## Baseline instance / storage (selected with rationale)

| Resource | Baseline | Rationale |
| -------- | -------- | --------- |
| **EC2** | `t3.small` (2 vCPU, 2 GiB) | Fits Docker Compose API + Postgres + light telemetry on one node; burstable CPU matches spiky evaluate traffic without `t3.medium` cost |
| **Root EBS** | **30 GiB `gp3`** | OS + Docker images + logs; gp3 baseline IOPS enough for Compose pulls |
| **Data EBS** | **50 GiB `gp3`** (`ito:role=postgres-data`) | Postgres + embeddings headroom for MVP corpus; grow only after disk alarms (#16) |
| **EIP** | One per env when public ingress needed | Release when instance terminated; never leave unattached |

**When to upsize**

| Signal | Next step |
| ------ | --------- |
| CPU credit balance chronically ~0 / steal high | `t3.medium` or `t3a.medium` |
| Mem > ~85% sustained / OOM kills | `t3.medium` (4 GiB) before larger |
| Data volume > 70% for 7 days | Grow EBS (+20 GiB steps); do not jump to io2 |
| Root volume docker bloat | `docker system prune`; then grow root if still tight |

**When to downsize**

| Signal | Next step |
| ------ | --------- |
| CPU < 20% p95 and mem < 50% for 14 days on non-prod | `t3.micro` only for **dev** sandboxes (not staging/prod) |
| Data volume < 30% for 30 days | Plan shrink via new volume + copy (do not online-shrink casually) |

Defaults match **#12** Terraform (`instance_type`, `root_volume_size_gb`, `data_volume_size_gb`, `data_volume_type`).

---

## Non-prod idle resource policy

Applies to resources tagged `ito:env=dev` or `ito:env=staging` **and**
`ito:idle-policy=office-hours`. **Never** auto-stop `ito:env=prod`.

### Schedule (UTC)

| Action | When |
| ------ | ---- |
| **Stop** eligible EC2 | Weekdays **20:00**, weekends **all day** (stop if running) |
| **Start** eligible EC2 | Weekdays **08:00** |
| **Cleanup scan** | Daily **06:30** |

### Stop / start

```bash
# Dry-run (default):
python scripts/apply_nonprod_idle_policy.py --action auto --simulate
# Live:
python scripts/apply_nonprod_idle_policy.py --action stop --live
python scripts/apply_nonprod_idle_policy.py --action start --live
```

Tag instances (and optionally volumes) from Terraform / console:

| Tag | Value |
| --- | ----- |
| `ito:project` | `intotheopen` |
| `ito:env` | `dev` / `staging` / `prod` |
| `ito:idle-policy` | `office-hours` (non-prod) or `none` (prod) |

### Cleanup rules

| Resource | Policy |
| -------- | ------ |
| Unattached **Elastic IPs** with `ito:project=intotheopen` | Release after **24h** unattached (non-prod only) |
| Available **EBS** volumes tagged `ito:env=dev\|staging` older than **7 days** unused | Snapshot then delete (operator confirm in live mode) |
| **Snapshots** with `ito:env=dev` older than **14 days** | Delete (keep staging/prod per #15) |

```bash
python scripts/apply_nonprod_idle_policy.py --action cleanup --simulate
python scripts/apply_nonprod_idle_policy.py --action cleanup --live
```

Policy file: [`infra/rightsizing/idle_policy.json`](../../infra/rightsizing/idle_policy.json).

---

## Monthly rightsizing review cadence

| Cadence | Owner | When |
| ------- | ----- | ---- |
| **Monthly** | Ops / budget owner | First business day (with #18 cost report) |

```bash
python scripts/run_rightsizing_review.py --month YYYY-MM --simulate
python scripts/run_rightsizing_review.py --month YYYY-MM   # uses AWS if creds present
```

Writes `docs/ops/rightsizing-reviews/YYYY-MM.md` (+ JSON). Checklist embedded in
the report:

1. Compare running instance types vs baseline (`t3.small` / gp3 sizes).
2. Check CloudWatch CPU/mem/disk (#16) against upsize/downsize signals above.
3. Confirm non-prod idle stops ran (no `dev`/`staging` running all weekend).
4. List unattached EIPs / orphan volumes.
5. Record decision: **keep** / **resize** / **stop** / **cleanup** + ticket link.
6. Cross-check spend vs **#18** EC2/EBS budget slices.

---

## Acceptance mapping (#19)

| Criterion | Deliverable |
| --------- | ----------- |
| Baseline instance/storage selected with rationale | Table above + `baseline.json` |
| Non-prod idle resource policy implemented | `idle_policy.json` + `apply_nonprod_idle_policy.py` |
| Monthly rightsizing review cadence in place | This section + `run_rightsizing_review.py` |
