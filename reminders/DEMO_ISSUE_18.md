# Demo — Issue #18 (AWS budget alerts)

**Branch:** `feature/issue-18-aws-budget-alerts`  
**Issue:** [intotheopen/intotheopen-backend#18](https://github.com/intotheopen/intotheopen-backend/issues/18)

| Criterion | Deliverable |
| --------- | ----------- |
| Budgets + forecast alerts → owners | `infra/budgets` (overall + EC2/EBS/CloudWatch) |
| Monthly cost report | `scripts/generate_monthly_cost_report.py` |
| Cost-control playbook | `docs/ops/COST_CONTROLS.md` |

```bash
pytest tests/test_aws_budgets.py -q
python scripts/generate_monthly_cost_report.py --month 2026-06 --simulate
cd infra/budgets && terraform init -backend=false && terraform validate
```
