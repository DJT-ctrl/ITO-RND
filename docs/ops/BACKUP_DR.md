# AWS backup, restore, and disaster recovery

Issue **#15** — backup strategy, published RPO/RTO, scheduled jobs with
monitoring, and a restore drill with documented timings.

Related: pre-ingest rollback dumps remain in [`storage/db_backup.py`](../../storage/db_backup.py);
this playbook covers **off-instance DR** for the Compose-on-EC2 MVP.

## Published RPO / RTO (MVP agreement)

| Objective | Target | How measured |
| --------- | ------ | ------------ |
| **RPO** (max data loss) | **≤ 24 hours** | Age of newest successful logical dump (and/or EBS snapshot) |
| **RTO** (max downtime to restore) | **≤ 4 hours** | Wall clock from restore start → `/health` + smoke query OK |

These are the working targets for Milestone 4 low-cost MVP. Tighten after
managed RDS / Multi-AZ if product requires it. Sign-off for go-live: **#27**.

## Backup strategy

| Layer | What | Schedule | Retention | Tooling |
| ----- | ---- | -------- | --------- | ------- |
| **A. Logical dump** | Full `pg_dump -F c` via Compose `db` | Daily 03:15 UTC (systemd timer) | 7 local dumps; S3 lifecycle 30 days (ops-owned) | `scripts/run_scheduled_backup.py` |
| **B. EBS snapshot** | Volume tagged `ito:role=postgres-data` (`DB_DATA_PATH`) | Daily 03:00 UTC | 14 snapshots | AWS DLM — [`dlm-ebs-snapshot-policy.example.json`](../../deploy/dlm-ebs-snapshot-policy.example.json) |
| **C. Pre-ingest** | Dump before upsert | On each `run_db_ingest` | Local only | `storage.db_backup.create_backup` |

Offsite: set `ITO_BACKUP_S3_BUCKET` so daily dumps are copied with `aws s3 cp`.
Instance role needs `s3:PutObject` (and list/get for restores) on that bucket.

```
systemd timer ito-db-backup.timer
        │
        ▼
scripts/run_scheduled_backup.py
        ├─ pg_dump → data/db_backups/posts_daily_*.dump
        ├─ aws s3 cp → s3://$ITO_BACKUP_S3_BUCKET/ito/postgres/
        ├─ prune local (keep 7)
        └─ metrics → data/telemetry/node-exporter-textfile/ito_backup.prom
```

## Scheduling & monitoring

Install on the EC2 host:

```bash
sudo cp deploy/ito-db-backup.service deploy/ito-db-backup.timer /etc/systemd/system/
# ensure /etc/ito/ito.env has ITO_BACKUP_S3_BUCKET=… (optional but recommended)
sudo systemctl daemon-reload
sudo systemctl enable --now ito-db-backup.timer
systemctl list-timers | grep ito-db-backup
```

**Monitoring signals**

| Signal | Source |
| ------ | ------ |
| `ito_backup_last_ok` / `ito_backup_last_success_timestamp` | node-exporter textfile |
| `BackupJobFailed` / `BackupJobStale` | [`deploy/telemetry/alerts/backup.yml`](../../deploy/telemetry/alerts/backup.yml) |
| Unit failure | `systemctl status ito-db-backup`; `journalctl -u ito-db-backup` |

Alert if last success older than **36h** (missed daily + buffer) or last run `ok=0`.

## Restore procedures

### Logical dump (preferred for logical corruption / bad ingest)

```bash
# From S3 (example)
aws s3 cp s3://$ITO_BACKUP_S3_BUCKET/ito/postgres/posts_daily_YYYYMMDDThhmmssZ.dump \
  data/db_backups/

# Destructive to current DB — non-prod first
python scripts/run_restore_drill.py --dump data/db_backups/posts_daily_….dump
curl -s localhost:8000/health
```

### EBS snapshot (preferred for disk failure)

1. Stop stack: `systemctl stop ito-stack`
2. Create volume from snapshot; attach; mount at `DB_DATA_PATH`
3. Start stack; verify migrate/health
4. Record wall time toward RTO

## Restore drill (documented timings)

### Simulated drill (CI / always in repo)

```bash
python scripts/run_restore_drill.py --simulate
# writes docs/ops/RESTORE_DRILL_LATEST.json
```

Latest simulated report: [`RESTORE_DRILL_LATEST.json`](RESTORE_DRILL_LATEST.json).

### Live non-prod drill (required once before #27)

1. Use a non-prod Compose stack with a known dump age **≤ RPO**.
2. `time python scripts/run_restore_drill.py --dump …`
3. Confirm RPO/RTO flags in the JSON report are `true`.
4. Attach timings to the #27 go-live checklist.

## Acceptance mapping (#15)

| Criterion | Deliverable |
| --------- | ----------- |
| Automated backup jobs scheduled and monitored | `ito-db-backup.timer` + textfile metrics + Prometheus alerts |
| Restore drill succeeds in non-prod with timings | `scripts/run_restore_drill.py` + `RESTORE_DRILL_LATEST.json` |
| RPO/RTO agreed and published | Table above (24h / 4h) |
