# Demo — Issue #19 (EC2/EBS rightsizing)

**Branch:** `feature/issue-19-ec2-ebs-rightsizing`  
**Issue:** [intotheopen/intotheopen-backend#19](https://github.com/intotheopen/intotheopen-backend/issues/19)

| Criterion | Deliverable |
| --------- | ----------- |
| Baseline + rationale | `infra/rightsizing/baseline.json` (`t3.small` / gp3) |
| Non-prod idle policy | `idle_policy.json` + `apply_nonprod_idle_policy.py` |
| Monthly review cadence | `run_rightsizing_review.py` → `rightsizing-reviews/` |

```bash
pytest tests/test_rightsizing.py -q
python scripts/apply_nonprod_idle_policy.py --action auto --simulate
python scripts/run_rightsizing_review.py --month 2026-07 --simulate
```
