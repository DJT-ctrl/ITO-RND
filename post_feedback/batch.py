"""Offline batch orchestration for stored-post feedback."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from config.settings import Settings
from post_feedback.generate import generate_post_feedback
from post_feedback.prompt import build_neighbor_notes
from post_feedback.store import (
    fetch_eligible_posts,
    fetch_neighbor_rows,
    insert_post_feedback,
)
from storage.vector_store import create_schema, get_connection

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 50


@dataclass
class PostFeedbackBatchResult:
    processed: int = 0
    generated: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def run_post_feedback_batch(
    settings: Settings,
    *,
    limit: int = DEFAULT_LIMIT,
    dry_run: bool = False,
    model: Optional[Any] = None,
) -> PostFeedbackBatchResult:
    """Write detailed feedback for clean labelled posts that do not have it yet."""
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set")

    result = PostFeedbackBatchResult()
    with get_connection(settings) as conn:
        create_schema(conn)
        rows = fetch_eligible_posts(conn, limit=limit)
        result.processed = len(rows)
        if dry_run:
            result.skipped = len(rows)
            return result

        for post, embedding in rows:
            try:
                neighbors = fetch_neighbor_rows(conn, embedding, post.post_id)
                cta_by_id = {
                    str(row.get("post_id")): row.get("has_explicit_cta")
                    for row in neighbors
                }
                notes = build_neighbor_notes(post, neighbors, cta_by_id=cta_by_id)
                record = generate_post_feedback(post, notes, model=model)
                inserted = insert_post_feedback(conn, record)
                if inserted is None:
                    result.skipped += 1
                else:
                    result.generated += 1
            except Exception as exc:  # noqa: BLE001 — batch continues
                logger.exception("Post feedback failed for %s", post.post_id)
                result.failed += 1
                result.errors.append(f"{post.post_id}: {exc}")
    return result
