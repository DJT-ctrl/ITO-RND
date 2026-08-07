# Demo — Issue #16 (CloudWatch logs & alarms)

**Branch:** `feature/issue-16-cloudwatch-logs-alarms`  
**Issue:** [intotheopen/intotheopen-backend#16](https://github.com/intotheopen/intotheopen-backend/issues/16)

| Criterion | Deliverable |
| --------- | ----------- |
| Logs + retention | `infra/observability/logs.tf` + agent JSON |
| Essential alarms + SNS | `alarms.tf` / `sns.tf` (email + HTTPS) |
| API + host dashboard | `dashboard.tf` |
| Controlled alert test | `scripts/test_cloudwatch_alarms.py` |
| On-call runbook | `docs/ops/CLOUDWATCH.md` |

```bash
pytest tests/test_cloudwatch_observability.py -q
python scripts/test_cloudwatch_alarms.py --simulate
cd infra/observability && terraform init -backend=false && terraform validate
```
