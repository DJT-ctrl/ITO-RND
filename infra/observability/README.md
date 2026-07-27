# CloudWatch observability (issue #16)

Baseline **CloudWatch Logs**, essential **alarms**, **SNS** alert fan-out, and an
**API + host health** dashboard for the Compose-on-EC2 MVP.

Depends on the host from issue **#12** (`compose_host_instance_id` /
`compose_host_role_name`). Local Prometheus/Grafana (#8) remains the deep
diagnostics path; CloudWatch is the AWS-native on-call page path.

## What this root provisions

| Resource | Purpose |
| -------- | ------- |
| Log groups `/ito/<env>/{api,host,docker}` | App/system/docker logs + retention |
| SNS `${project}-${env}-critical-alerts` | Email and/or HTTPS (Slack/PagerDuty) |
| Alarms | Host status, disk %, API error rate, API p95 latency, 5xx log spike |
| Dashboard `${project}-${env}-mvp-health` | API + host health panels |
| IAM attachments | `CloudWatchAgentServerPolicy` + PutMetricData / logs write |

## Apply

```bash
cd infra/observability
terraform init
terraform plan \
  -var="environment=dev" \
  -var="compose_host_instance_id=i-0123456789abcdef0" \
  -var="compose_host_role_name=intotheopen-dev-compose-host" \
  -var="alert_email=oncall@example.com"
terraform apply ...
```

Optional HTTPS destination (Slack via Chatbot/webhook bridge, or PagerDuty):

```bash
-var="alert_https_endpoint=https://events.pagerduty.com/integration/.../enqueue"
```

## Host follow-up

```bash
# On the Compose EC2 host (SSM)
sudo bash deploy/cloudwatch/install-agent.sh dev
# Publish API ErrorRate + LatencyP95Seconds into namespace ITO/API
python scripts/publish_cw_api_metrics.py --environment dev --loop
```

## Controlled alarm test

```bash
python scripts/test_cloudwatch_alarms.py --simulate
# Live (sets ALARM then OK on the error-rate alarm):
python scripts/test_cloudwatch_alarms.py \
  --alarm intotheopen-dev-api-error-rate \
  --live
```

## Acceptance mapping (#16)

| Criterion | Deliverable |
| --------- | ----------- |
| Critical alerts fire in a controlled test | `scripts/test_cloudwatch_alarms.py` |
| Dashboards include API and host health | `aws_cloudwatch_dashboard.ito_mvp` |
| On-call runbook alarm → diagnosis → mitigation | [`docs/ops/CLOUDWATCH.md`](../../docs/ops/CLOUDWATCH.md) |
