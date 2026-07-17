# AWS Budgets & monthly cost controls (issue #18)

Low-cost MVP **cost guardrails**: overall monthly budget, service-level split
(EC2 / EBS / CloudWatch), **actual + forecast** alerts to SNS (email / Slack /
PagerDuty), and a monthly Cost Explorer report script.

## Default monthly split (USD)

| Bucket | Default | Notes |
| ------ | ------- | ----- |
| **Overall** | **80** | Account COST budget |
| EC2 compute | 45 | Compose host (`t3.small` class) |
| EBS | 15 | Root + Postgres data volume |
| CloudWatch | 12 | Logs/alarms/dashboard (#16) |
| Other (residual) | 8 | Data transfer, SNS, Secrets, Budgets |

Override via Terraform variables when the environment needs a different envelope.

## Apply

```bash
cd infra/budgets
cp terraform.tfvars.example terraform.tfvars   # set alert_emails
terraform init
terraform plan
terraform apply
```

## Notify before overrun

Overall budget notifies at **50% / 80% / 100% ACTUAL** and **100% FORECASTED**.
Service budgets notify at **80% ACTUAL** and **100% FORECASTED**.

## Monthly report

```bash
python scripts/generate_monthly_cost_report.py --month 2026-07
# Offline / CI:
python scripts/generate_monthly_cost_report.py --month 2026-07 --simulate
```

Writes `docs/ops/cost-reports/YYYY-MM.md` (and JSON sidecar).

## Acceptance mapping (#18)

| Criterion | Deliverable |
| --------- | ----------- |
| Budget alarms notify owner channels before overrun | `budgets.tf` + SNS (50/80/100 + forecast) |
| Monthly cloud cost report generated and reviewed | `scripts/generate_monthly_cost_report.py` |
| Cost control steps documented | [`docs/ops/COST_CONTROLS.md`](../../docs/ops/COST_CONTROLS.md) |
