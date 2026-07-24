"""Offline batch orchestration for A1 post-mortems."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from config.settings import Settings
from post_mortems.generate import generate_post_mortem
from post_mortems.store import fetch_flagged_posts_without_mortems, insert_post_mortem
from storage.vector_store import create_schema, get_connection

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 50


@dataclass
class PostMortemBatchResult:
    processed: int = 0
    generated: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def run_post_mortem_batch(
    settings: Settings,
    *,
    limit: int = DEFAULT_LIMIT,
    dry_run: bool = False,
    model: Optional[Any] = None,
) -> PostMortemBatchResult:
    """Sweep flagged posts missing post-mortems and generate explanations."""
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set")

    result = PostMortemBatchResult()
    with get_connection(settings) as conn:
        create_schema(conn)
        rows = fetch_flagged_posts_without_mortems(conn, limit=limit)
        result.processed = len(rows)
        if dry_run:
            result.skipped = len(rows)
            return result

        for row in rows:
            try:
                record = generate_post_mortem(row, model=model)
                inserted = insert_post_mortem(conn, record)
                if inserted is None:
                    result.skipped += 1
                else:
                    result.generated += 1
            except Exception as exc:  # noqa: BLE001 — batch continues
                logger.exception("Post-mortem failed for %s", row.post_id)
                result.failed += 1
                result.errors.append(f"{row.post_id}: {exc}")
    return result
