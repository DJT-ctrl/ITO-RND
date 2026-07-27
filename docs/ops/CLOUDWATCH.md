# CloudWatch logs & essential alarms (MVP)

Issue **#16** — AWS-native observability for the Compose-on-EC2 MVP: log
shipping with retention, essential alarms, SNS alert destinations, a health
dashboard, and this on-call runbook.

Related: local Prometheus/Grafana reliability path in
[`API_RELIABILITY_RUNBOOK.md`](API_RELIABILITY_RUNBOOK.md) / issue **#8** when
merged. Prefer CloudWatch for **paging**; use Prometheus for deep scrape-level
diagnosis on the box.

## Quick links

| Resource | Where |
| -------- | ----- |
| Terraform | [`infra/observability/`](../../infra/observability/) |
| Agent config | [`deploy/cloudwatch/amazon-cloudwatch-agent.json`](../../deploy/cloudwatch/amazon-cloudwatch-agent.json) |
| Install agent | `sudo bash deploy/cloudwatch/install-agent.sh <env>` |
| Metrics bridge | `python scripts/publish_cw_api_metrics.py --environment <env> --loop` |
| Controlled test | `python scripts/test_cloudwatch_alarms.py --simulate` |
| Dashboard | CloudWatch → Dashboards → `intotheopen-<env>-mvp-health` |
| SNS topic | `intotheopen-<env>-critical-alerts` |

## Log groups & retention

| Log group | Contents | Retention (default) |
| --------- | -------- | ------------------- |
| `/ito/<env>/api` | API application / access logs | **14 days** |
| `/ito/<env>/host` | Host syslog (`/var/log/messages`) | **14 days** |
| `/ito/<env>/docker` | Container JSON logs | **14 days** |

Retention is set in Terraform (`log_retention_days`) and mirrored in the agent
JSON. Raise only when budget (#18) allows.

## Alert destinations

SNS topic `intotheopen-<env>-critical-alerts` fans out to:

| Destination | How |
| ----------- | --- |
| **Email** | `alert_email` Terraform variable → confirm subscription |
| **Slack** | `alert_https_endpoint` via AWS Chatbot or webhook bridge |
| **PagerDuty** | `alert_https_endpoint` → Events API v2 integration URL |

All critical / warning alarms in this pack publish to the same topic for MVP
simplicity.

## Controlled test (acceptance)

```bash
# Offline — validates alarm + runbook wiring
python scripts/test_cloudwatch_alarms.py --simulate

# Live — forces ALARM then OK so SNS fires once
python scripts/test_cloudwatch_alarms.py \
  --alarm intotheopen-dev-api-error-rate \
  --live
```

Expect one notification on ALARM and a resolve/OK depending on destination.

---

## Severity

| Level | Meaning | Response |
| ----- | ------- | -------- |
| **SEV-1** | Host status check failed or API error rate critical | Page on-call; mitigate immediately |
| **SEV-2** | Disk pressure or latency p95 burn | Investigate within 30m |
| **SEV-3** | 5xx log spike without metrics confirmation | Correlate; watch |

---

## Alarm → diagnosis → mitigation

### host-status-check-failed

**Meaning:** `AWS/EC2 StatusCheckFailed > 0` for the Compose host.

**Diagnosis:**

1. CloudWatch → EC2 → instance status / system status.
2. SSM Session Manager into the instance (prefer over SSH).
3. `docker compose ps` / `systemctl status ito-stack` / `dmesg | tail`.

**Mitigation:**

- System check failed: stop/start instance from EC2 console (EIP should reattach if #12 Elastic IP is enabled).
- Instance check failed: reboot; if stuck, replace from Terraform (#12) after confirming backups (#15).

### disk-used-percent

**Meaning:** `CWAgent disk_used_percent` on `/` above threshold (default **85%**).

**Diagnosis:**

```bash
df -h
docker system df
du -sh /var/lib/docker /opt/ito-rnd/data /var/log | sort -h
```

**Mitigation:**

- `docker system prune -f` (careful on prod — avoid deleting needed images mid-incident).
- Rotate / truncate large logs; confirm CloudWatch agent still shipping.
- Expand root EBS or clear old dumps under `data/db_backups` after offsite copy (#15).

### api-error-rate

**Meaning:** Custom metric `ITO/API ErrorRate` (%) over 5m exceeds threshold (default **5%**).

**Diagnosis:**

1. Dashboard panel **API error rate**.
2. Logs Insights on `/ito/<env>/api`:
   ```
   fields @timestamp, @message
   | filter @message like /5[0-9][0-9]|ERROR|Traceback/
   | sort @timestamp desc
   | limit 50
   ```
3. On host: `curl -sf localhost:8000/health` and sample `/api/v1/similar-posts`.
4. Map error envelope codes ([`docs/api/ERROR_CODES.md`](../api/ERROR_CODES.md) when present).

**Mitigation:**

- Restart API: `docker compose up -d --build api` (or `systemctl restart ito-stack`).
- Fix `DATABASE_URL` / Secrets Manager injection (#13).
- Roll back bad deploy (see [#20](https://github.com/intotheopen/intotheopen-backend/issues/20) runbook when published).

### api-latency-p95

**Meaning:** `ITO/API LatencyP95Seconds` above threshold (default **30s**, aligned with evaluate SLO).

**Diagnosis:**

1. Dashboard **API latency p95** panel.
2. Check Gemini/provider latency and DB load (`docker compose logs --tail=100 api`).
3. Cross-check Prometheus histograms if the local stack is up (#8).

**Mitigation:**

- Reduce concurrent evaluate load; disable expensive optional paths temporarily.
- Scale instance type / rightsizing later (#19).
- If a bad release: roll back API image.

### api-5xx-log-spike

**Meaning:** Metric filter on `/ito/<env>/api` counted many 5xx/ERROR lines in 5m.

**Diagnosis:** Same as [api-error-rate](#api-error-rate). Treat as backup signal when the metrics publisher is down.

**Mitigation:** Restore `publish_cw_api_metrics.py` loop; fix underlying 5xx cause.

---

## Dashboard checklist

The Terraform dashboard `intotheopen-<env>-mvp-health` must show:

1. API error rate  
2. API latency p95  
3. Host status check failed  
4. Disk used percent  
5. Recent API log lines  

---

## Operational ownership

| Area | Owner |
| ---- | ----- |
| Alarm thresholds / SNS membership | Ops / on-call |
| Agent install on new hosts | Whoever applies #12 + this pack |
| Metrics publisher process | Keep under `ito-stack` or a systemd unit in #20 |

Update this runbook when alarm names or thresholds change in
`infra/observability/`.
