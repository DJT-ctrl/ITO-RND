# Demo — Issue #15 (AWS backup / DR)

**Branch:** `feature/issue-15-aws-backup-dr`  
**Issue:** [intotheopen/intotheopen-backend#15](https://github.com/intotheopen/intotheopen-backend/issues/15)

| Criterion | Deliverable |
| --------- | ----------- |
| Scheduled + monitored backups | `ito-db-backup.timer` + textfile metrics + alerts |
| Restore drill with timings | `RESTORE_DRILL_LATEST.json` + `run_restore_drill.py` |
| RPO/RTO published | 24h / 4h in `docs/ops/BACKUP_DR.md` |

```bash
pytest tests/test_dr_backup.py tests/test_db_backup.py -q
python scripts/run_restore_drill.py --simulate
```
