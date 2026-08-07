# Demo — Issue #17 (AWS WAF)

**Branch:** `feature/issue-17-aws-waf`  
**Issue:** [intotheopen/intotheopen-backend#17](https://github.com/intotheopen/intotheopen-backend/issues/17)

| Criterion | Deliverable |
| --------- | ----------- |
| WAF + ALB attach | `infra/waf` (`alb_arn` association) |
| Managed rules + rate limit + staging | COUNT default → `enable_blocking` |
| Allow/block exception runbook | `docs/ops/WAF.md` |

```bash
pytest tests/test_aws_waf.py -q
python scripts/test_waf_edge.py --simulate
cd infra/waf && terraform init -backend=false && terraform validate
```
