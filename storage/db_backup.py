"""Pre-ingestion Postgres backup/restore via docker-compose (T1.4/T1.5 rollback).

Why this exists
-----------------
storage/vector_store.py's insert_posts() upserts (``ON CONFLICT ... DO
UPDATE``) — safe for re-running the same dataset, but it means a bad
ingestion run overwrites existing rows in place with no way to recover the
previous values afterwards. A dump taken immediately before each ingestion
run is the simplest reliable rollback: if a batch turns out to be
corrupted, just restore the dump from right before it ran.

Why `docker compose exec pg_dump/pg_restore` instead of a local client
-------------------------------------------------------------------------
Postgres runs via colima + docker-compose (service name "db", see
docker-compose.yml), not a local Postgres install. Shelling out to
`docker compose exec db pg_dump` always uses the exact pg_dump binary
bundled in the pgvector/pg16 image — guaranteed to match the server
version, with no extra local install required.

Usage:
    python -m storage.db_backup --list
    python -m storage.db_backup --restore data/db_backups/posts_pre_ingest_<timestamp>.dump
"""

import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from config.settings import Settings, load_settings

_DEFAULT_BACKUP_DIR = "data/db_backups"
_COMPOSE_SERVICE = "db"


def _parse_dsn(database_url: str) -> tuple[str, str]:
    """Extract (user, dbname) from a DATABASE_URL DSN.

    Kept as a separate, pure function (no subprocess) so it's easy to unit
    test without shelling out to docker.
    """
    if not database_url:
        raise ValueError("DATABASE_URL is not set (check your .env file).")
    parsed = urlparse(database_url)
    user = parsed.username or ""
    dbname = parsed.path.lstrip("/")
    if not user or not dbname:
        raise ValueError(f"Could not parse user/dbname out of DATABASE_URL: {database_url!r}")
    return user, dbname


def create_backup(settings: Settings, backup_dir: str = _DEFAULT_BACKUP_DIR) -> Path:
    """Dump the whole database via `docker compose exec db pg_dump` (custom format).

    Returns the path to the new timestamped .dump file. Raises RuntimeError
    if the docker compose subprocess exits non-zero (e.g. the db container
    isn't running) — callers (processors/run_db_ingest.py) should let this
    propagate rather than silently skipping the backup.
    """
    user, dbname = _parse_dsn(settings.database_url)

    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_path = directory / f"posts_pre_ingest_{timestamp}.dump"

    command = [
        "docker", "compose", "exec", "-T", _COMPOSE_SERVICE,
        "pg_dump", "-U", user, "-d", dbname, "-F", "c",
    ]
    with dump_path.open("wb") as dump_file:
        result = subprocess.run(command, stdout=dump_file, stderr=subprocess.PIPE)

    if result.returncode != 0:
        dump_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"pg_dump failed (exit {result.returncode}): {result.stderr.decode(errors='replace')}"
        )
    return dump_path


def restore_backup(settings: Settings, backup_path: Path) -> None:
    """Restore a .dump file created by create_backup() via `docker compose exec db pg_restore`.

    Uses --clean --if-exists so existing objects are dropped/recreated
    rather than erroring out on conflicts with what's currently in the DB.
    """
    user, dbname = _parse_dsn(settings.database_url)
    backup_path = Path(backup_path)
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    command = [
        "docker", "compose", "exec", "-T", _COMPOSE_SERVICE,
        "pg_restore", "-U", user, "-d", dbname, "--clean", "--if-exists",
    ]
    with backup_path.open("rb") as dump_file:
        result = subprocess.run(command, stdin=dump_file, stderr=subprocess.PIPE)

    if result.returncode != 0:
        raise RuntimeError(
            f"pg_restore failed (exit {result.returncode}): {result.stderr.decode(errors='replace')}"
        )


def list_backups(backup_dir: str = _DEFAULT_BACKUP_DIR) -> list[Path]:
    """Return every backup under backup_dir, oldest first (filenames sort chronologically)."""
    directory = Path(backup_dir)
    if not directory.exists():
        return []
    return sorted(directory.glob("posts_pre_ingest_*.dump"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List available backups and exit.")
    parser.add_argument("--restore", default=None, help="Path to a .dump file to restore.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    settings = load_settings()

    if args.list:
        backups = list_backups()
        if not backups:
            print("No backups found.")
        for backup in backups:
            print(backup)
    elif args.restore:
        restore_backup(settings, Path(args.restore))
        print(f"Restored {args.restore}")
    else:
        print("Nothing to do — pass --list or --restore <path>. See --help.")
