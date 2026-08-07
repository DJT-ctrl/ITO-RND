# AWS budget alerts & monthly cost controls

Issue **#18** — low-cost MVP spend guardrails: published monthly threshold and
service split, AWS Budgets with **actual + forecast** alerts to owner channels,
monthly Cost Explorer report, and actionable response steps.

Terraform: [`infra/budgets/`](../../infra/budgets/).

## Published monthly budget (defaults)

| Bucket | USD / month | Primary drivers |
| ------ | ----------- | --------------- |
| **Overall** | **80** | Whole account COST |
| EC2 | 45 | Compose host instance hours |
| EBS | 15 | Root + Postgres data volume |
| CloudWatch | 12 | Log ingestion/retention, alarms (#16) |
| Other (residual) | 8 | Data transfer, SNS, Secrets Manager, Budgets |

Adjust via `infra/budgets` variables when product needs a different envelope.
Keep `budget:low-cost-mvp` intent: prefer rightsizing (#19) over raising limits.

## Alert destinations (before overrun)

| Channel | Wiring |
| ------- | ------ |
| Email | `alert_emails` on budgets + SNS email subscriptions |
| Slack | SNS `alert_https_endpoint` via AWS Chatbot / webhook bridge |
| PagerDuty | Same HTTPS endpoint → Events API v2 |

**Overall** budget notifies at **50% / 80% / 100% ACTUAL** and **100% FORECASTED**.
Service budgets notify at **80% ACTUAL** and **100% FORECASTED**.

Forecast alerts are the primary “before overrun” signal mid-month.

## Monthly cloud cost report

On the **first business day** of each month (or after a budget alert):

```bash
python scripts/generate_monthly_cost_report.py --month YYYY-MM
# CI / offline sample:
python scripts/generate_monthly_cost_report.py --month YYYY-MM --simulate
```

Artifacts:

- `docs/ops/cost-reports/YYYY-MM.md` — human review
- `docs/ops/cost-reports/YYYY-MM.json` — machine-readable sidecar

**Review checklist**

1. Total vs overall budget ($80 default).
2. Top 3 services vs EC2 / EBS / CloudWatch slices.
3. Anomalies (idle EIPs, unexpected regions, log ingest spikes).
4. File actions taken (or “no change”) in the report’s Review section.
5. Link outcome into go-live / ops notes (#27) when relevant.

---

## Response playbook (budget alert fired)

### 1. Triage (15 minutes)

1. Open AWS Budgets → which budget (`overall` / `ec2` / `ebs` / `cloudwatch`) and ACTUAL vs FORECASTED.
2. Cost Explorer → **last 7 days** by service and by instance/resource tag (`ito:project=intotheopen`).
3. Confirm environment (`dev` vs `prod`) — stop non-prod sandboxes first.

### 2. Immediate cost-control steps

| Lever | Action |
| ----- | ------ |
| Stop idle non-prod | `terraform destroy` / stop unused EC2 in `dev`/`staging` |
| Rightsizing | Downsize instance type; see #19 |
| Disk | Delete unused snapshots / old AMI; prune docker on host |
| Logs | Lower CloudWatch retention (`log_retention_days` in #16) toward 7 days |
| Data transfer | Avoid public large pulls; keep traffic in-region |
| Elastic IP | Release unattached EIPs |
| Budgets themselves | Free for first budgets; avoid creating many unused budgets |

### 3. If still forecast to overrun

1. Freeze non-essential batch/Apify/Gemini spend that drives AWS *egress* or *storage* growth.
2. Temporarily stop Grafana/Prometheus on the host if they inflate EBS (local) — does not cut AWS bill much; prefer EBS/snapshot cleanup.
3. Raise budget **only** with explicit owner approval; update Terraform vars and re-apply; document in the monthly report.

### 4. Close the loop

- Post a short note to the owner channel: cause, action, residual forecast.
- Attach or link the latest `docs/ops/cost-reports/YYYY-MM.md`.
- Schedule rightsizing follow-up (#19) if EC2 is the hot slice.

---

## Ownership

| Task | Cadence | Owner |
| ---- | ------- | ----- |
| Confirm SNS subscriptions | After every `terraform apply` | Whoever applies #18 |
| Monthly report + review | First business day | Ops / budget owner |
| Threshold changes | As needed | Ops + engineering lead |

## Acceptance mapping

| Criterion | Where |
| --------- | ----- |
| Budget alarms notify owner channels before overrun | AWS Budgets + SNS in `infra/budgets` |
| Monthly cloud cost report generated and reviewed | `generate_monthly_cost_report.py` + review checklist above |
| Cost control steps documented | This playbook |
