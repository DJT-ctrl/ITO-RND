#!/usr/bin/env python3
"""Run a scheduled Postgres logical backup (issue #15).

Examples:
  python scripts/run_scheduled_backup.py
  ITO_BACKUP_S3_BUCKET=my-ito-backups python scripts/run_scheduled_backup.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.settings import load_settings  # noqa: E402
from storage.dr_backup import (  # noqa: E402
    DEFAULT_BACKUP_DIR,
    DEFAULT_STATUS_JSON,
    DEFAULT_TEXTFILE,
    run_scheduled_backup,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--s3-bucket", default=os.getenv("ITO_BACKUP_S3_BUCKET", "") or None)
    parser.add_argument("--s3-prefix", default=os.getenv("ITO_BACKUP_S3_PREFIX", "ito/postgres"))
    parser.add_argument("--keep-local", type=int, default=int(os.getenv("ITO_BACKUP_KEEP_LOCAL", "7")))
    parser.add_argument("--status-json", type=Path, default=Path(DEFAULT_STATUS_JSON))
    parser.add_argument("--textfile", type=Path, default=Path(DEFAULT_TEXTFILE))
    args = parser.parse_args(argv)

    settings = load_settings()
    result = run_scheduled_backup(
        settings,
        backup_dir=args.backup_dir,
        s3_bucket=args.s3_bucket,
        s3_prefix=args.s3_prefix,
        keep_local=args.keep_local,
        status_json=args.status_json,
        textfile=args.textfile,
    )
    print(
        f"ok dump={result.dump_path} bytes={result.bytes} "
        f"s3={result.s3_uri or '-'} duration_s={result.duration_seconds}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
