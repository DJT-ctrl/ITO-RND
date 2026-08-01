# Demo — Issue #12 (AWS IaC)

**Branch:** `feature/issue-12-aws-iac`  
**Issue:** [intotheopen/intotheopen-backend#12](https://github.com/intotheopen/intotheopen-backend/issues/12)

| Criterion | Deliverable |
| --------- | ----------- |
| Provision from code | `infra/terraform` (VPC, SG, IAM, EC2, EBS) |
| Drift in CI | `.github/workflows/terraform.yml` |
| Bootstrap / teardown docs | `infra/README.md` |

```bash
pytest tests/test_aws_iac.py -q
cd infra/terraform && terraform init -backend=false && terraform validate
```
