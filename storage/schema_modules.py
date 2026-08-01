"""Apply modular SQL schemas without bloating storage/schema.sql.

Module files live in storage/schema_modules/*.sql and are executed after the
core schema so they may reference posts / pgvector types.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

_MODULES_DIR = Path(__file__).resolve().parent / "schema_modules"


def module_sql_paths() -> list[Path]:
    if not _MODULES_DIR.is_dir():
        return []
    return sorted(_MODULES_DIR.glob("*.sql"))


def apply_module_schemas(conn: psycopg.Connection) -> list[str]:
    """Run every *.sql in schema_modules/. Returns filenames applied."""
    applied: list[str] = []
    with conn.cursor() as cur:
        for path in module_sql_paths():
            cur.execute(path.read_text(encoding="utf-8"))
            applied.append(path.name)
    conn.commit()
    return applied
