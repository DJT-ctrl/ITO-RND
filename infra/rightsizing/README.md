# Rightsizing artifacts (issue #19)

| File | Purpose |
| ---- | ------- |
| [`baseline.json`](baseline.json) | Selected EC2/EBS baseline + rationale |
| [`idle_policy.json`](idle_policy.json) | Non-prod stop/start + cleanup rules |

Runbook: [`docs/ops/RIGHTSIZING.md`](../../docs/ops/RIGHTSIZING.md).

```bash
python scripts/apply_nonprod_idle_policy.py --action auto --simulate
python scripts/run_rightsizing_review.py --month 2026-07 --simulate
pytest tests/test_rightsizing.py -q
```
