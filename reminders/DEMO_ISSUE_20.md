# Demo — Issue #20 (deploy & rollback runbook)

**Branch:** `feature/issue-20-deploy-rollback-runbook`  
**Issue:** [intotheopen/intotheopen-backend#20](https://github.com/intotheopen/intotheopen-backend/issues/20)

| Criterion | Deliverable |
| --------- | ----------- |
| Executable runbook | `docs/ops/DEPLOY_ROLLBACK.md` |
| Pre/post smoke + rolling restart | `scripts/deploy_release.py` |
| Rollback + decision criteria | `scripts/rollback_release.py` + runbook table |
| Drill evidence | `scripts/run_deploy_drill.py` → `DEPLOY_DRILL_LATEST.json` |
| Downtime expectations | ≤ 10 minutes documented |

```bash
pytest tests/test_deploy_runbook.py -q
python scripts/run_deploy_drill.py --simulate
python scripts/deploy_release.py --dry-run --skip-git
```
