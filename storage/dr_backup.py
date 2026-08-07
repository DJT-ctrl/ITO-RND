"""Scheduled logical backups + S3 offsite + restore-drill helpers (issue #15).

Builds on ``storage.db_backup`` (Compose ``pg_dump`` / ``pg_restore``) and adds:
- daily dump prefix ``posts_daily_*``
- optional ``aws s3 cp`` upload
- local retention pruning
- Prometheus textfile + JSON status for monitoring
- restore-drill timing report writer
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config.settings import Settings
from storage.db_backup import create_backup, list_backups, restore_backup

DEFAULT_BACKUP_DIR = "data/db_backups"
DEFAULT_STATUS_JSON = "data/telemetry/backup_status.json"
DEFAULT_TEXTFILE = "data/telemetry/node-exporter-textfile/ito_backup.prom"
DEFAULT_DRILL_REPORT = "docs/ops/RESTORE_DRILL_LATEST.json"
SCHEDULED_PREFIX = "posts_daily"


@dataclass
class BackupRunResult:
    ok: bool
    dump_path: Optional[str]
    s3_uri: Optional[str]
    bytes: int
    duration_seconds: float
    error: Optional[str]
    finished_at: str
    pruned_local: list[str]


@dataclass
class RestoreDrillResult:
    ok: bool
    dump_path: str
    dump_age_seconds: float
    restore_duration_seconds: float
    rpo_target_seconds: int
    rto_target_seconds: int
    rpo_met: bool
    rto_met: bool
    finished_at: str
    notes: str
    error: Optional[str] = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def upload_dump_to_s3(
    dump_path: Path,
    *,
    bucket: str,
    prefix: str = "ito/postgres",
    aws_cli: str = "aws",
) -> str:
    """Upload a dump with AWS CLI. Returns the ``s3://`` URI."""
    key = f"{prefix.rstrip('/')}/{dump_path.name}"
    uri = f"s3://{bucket}/{key}"
    result = subprocess.run(
        [aws_cli, "s3", "cp", str(dump_path), uri],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"aws s3 cp failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return uri


def prune_local_dumps(
    backup_dir: str | Path,
    *,
    keep: int = 7,
    pattern: str = f"{SCHEDULED_PREFIX}_*.dump",
) -> list[str]:
    """Keep the newest ``keep`` scheduled dumps; delete older ones."""
    dumps = list_backups(str(backup_dir), pattern=pattern)
    if keep < 0:
        raise ValueError("keep must be >= 0")
    to_delete = dumps[:-keep] if keep > 0 else dumps
    removed: list[str] = []
    for path in to_delete:
        path.unlink(missing_ok=True)
        removed.append(str(path))
    return removed


def write_backup_status(
    result: BackupRunResult,
    *,
    status_json: Path,
    textfile: Path,
) -> None:
    """Persist JSON status + Prometheus textfile gauge for monitoring."""
    status_json.parent.mkdir(parents=True, exist_ok=True)
    textfile.parent.mkdir(parents=True, exist_ok=True)
    status_json.write_text(json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8")

    finished = datetime.fromisoformat(result.finished_at)
    success_ts = int(finished.timestamp()) if result.ok else 0
    lines = [
        "# HELP ito_backup_last_success_timestamp Unix time of last successful DB backup.",
        "# TYPE ito_backup_last_success_timestamp gauge",
        f"ito_backup_last_success_timestamp {success_ts}",
        "# HELP ito_backup_last_ok 1 if last backup succeeded else 0.",
        "# TYPE ito_backup_last_ok gauge",
        f"ito_backup_last_ok {1 if result.ok else 0}",
        "# HELP ito_backup_last_duration_seconds Wall time of last backup attempt.",
        "# TYPE ito_backup_last_duration_seconds gauge",
        f"ito_backup_last_duration_seconds {result.duration_seconds}",
        "",
    ]
    textfile.write_text("\n".join(lines), encoding="utf-8")


def run_scheduled_backup(
    settings: Settings,
    *,
    backup_dir: str = DEFAULT_BACKUP_DIR,
    s3_bucket: Optional[str] = None,
    s3_prefix: str = "ito/postgres",
    keep_local: int = 7,
    status_json: Path = Path(DEFAULT_STATUS_JSON),
    textfile: Path = Path(DEFAULT_TEXTFILE),
    aws_cli: str = "aws",
) -> BackupRunResult:
    """Create a logical dump, optionally upload to S3, prune, and emit status."""
    started = time.perf_counter()
    dump_path: Optional[Path] = None
    s3_uri: Optional[str] = None
    pruned: list[str] = []
    try:
        dump_path = create_backup(settings, backup_dir=backup_dir, prefix=SCHEDULED_PREFIX)
        size = dump_path.stat().st_size
        bucket = s3_bucket if s3_bucket is not None else os.getenv("ITO_BACKUP_S3_BUCKET", "").strip()
        if bucket:
            s3_uri = upload_dump_to_s3(
                dump_path, bucket=bucket, prefix=s3_prefix, aws_cli=aws_cli
            )
        pruned = prune_local_dumps(backup_dir, keep=keep_local)
        result = BackupRunResult(
            ok=True,
            dump_path=str(dump_path),
            s3_uri=s3_uri,
            bytes=size,
            duration_seconds=round(time.perf_counter() - started, 3),
            error=None,
            finished_at=_iso(_utc_now()),
            pruned_local=pruned,
        )
    except Exception as exc:  # noqa: BLE001 — status file must record failure
        result = BackupRunResult(
            ok=False,
            dump_path=str(dump_path) if dump_path else None,
            s3_uri=s3_uri,
            bytes=0,
            duration_seconds=round(time.perf_counter() - started, 3),
            error=str(exc),
            finished_at=_iso(_utc_now()),
            pruned_local=pruned,
        )
    write_backup_status(result, status_json=status_json, textfile=textfile)
    if not result.ok:
        raise RuntimeError(result.error or "scheduled backup failed")
    return result


def dump_age_seconds(dump_path: Path, *, now: Optional[datetime] = None) -> float:
    """Best-effort age from mtime (restore-drill RPO evidence)."""
    now = now or _utc_now()
    mtime = datetime.fromtimestamp(dump_path.stat().st_mtime, tz=timezone.utc)
    return max(0.0, (now - mtime).total_seconds())


def run_restore_drill(
    settings: Settings,
    dump_path: Path,
    *,
    rpo_target_seconds: int = 24 * 3600,
    rto_target_seconds: int = 4 * 3600,
    report_path: Path = Path(DEFAULT_DRILL_REPORT),
    notes: str = "Non-prod restore drill",
    perform_restore: bool = True,
) -> RestoreDrillResult:
    """Time a restore (or dry timing) and publish a drill report."""
    dump_path = Path(dump_path)
    age = dump_age_seconds(dump_path)
    started = time.perf_counter()
    error: Optional[str] = None
    ok = True
    try:
        if perform_restore:
            restore_backup(settings, dump_path)
    except Exception as exc:  # noqa: BLE001
        ok = False
        error = str(exc)
    duration = round(time.perf_counter() - started, 3)
    result = RestoreDrillResult(
        ok=ok,
        dump_path=str(dump_path),
        dump_age_seconds=round(age, 3),
        restore_duration_seconds=duration,
        rpo_target_seconds=rpo_target_seconds,
        rto_target_seconds=rto_target_seconds,
        rpo_met=age <= rpo_target_seconds,
        rto_met=duration <= rto_target_seconds,
        finished_at=_iso(_utc_now()),
        notes=notes,
        error=error,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8")
    if not ok:
        raise RuntimeError(error or "restore drill failed")
    return result


def simulate_restore_drill_timings(
    *,
    dump_path: str = "data/db_backups/posts_daily_simulated.dump",
    dump_age_seconds: float = 3600.0,
    restore_duration_seconds: float = 42.5,
    rpo_target_seconds: int = 24 * 3600,
    rto_target_seconds: int = 4 * 3600,
) -> dict[str, Any]:
    """Build a documented drill report without touching Postgres (CI / docs)."""
    result = RestoreDrillResult(
        ok=True,
        dump_path=dump_path,
        dump_age_seconds=dump_age_seconds,
        restore_duration_seconds=restore_duration_seconds,
        rpo_target_seconds=rpo_target_seconds,
        rto_target_seconds=rto_target_seconds,
        rpo_met=dump_age_seconds <= rpo_target_seconds,
        rto_met=restore_duration_seconds <= rto_target_seconds,
        finished_at=_iso(_utc_now()),
        notes=(
            "Simulated non-prod restore drill for issue #15 CI. "
            "Replace with a live timed restore before go-live (#27)."
        ),
        error=None,
    )
    return asdict(result)
