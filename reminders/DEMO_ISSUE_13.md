# Demo — Issue #13 (AWS-managed secrets)

**Branch:** `feature/issue-13-aws-secrets`  
**Issue:** [intotheopen/intotheopen-backend#13](https://github.com/intotheopen/intotheopen-backend/issues/13)

| Criterion | Deliverable |
| --------- | ----------- |
| No prod secrets in repo / durable `.env` | `/run/ito/runtime.env` from SM |
| App reads managed secret store | `config/aws_secrets.py` + fetch script + `ITO_ENV_FILE` |
| Rotation playbook tested | `deploy/SECRETS.md` + `tests/test_aws_secrets.py` |

```bash
pytest tests/test_aws_secrets.py -q
```
