"""Process due or selected prediction validations (re-scrape + score)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from pgvector.psycopg import register_vector

from config.settings import Settings, load_settings
from feedback.batch import try_store_feedback_after_validation
from storage.vector_store import create_schema, get_connection
from validation_pipeline.rescrape import fetch_engagement_by_urls
from validation_pipeline.schemas import ValidationBatchResult, ValidationResult
from validation_pipeline.scoring import (
    compute_validation_scores,
    corpus_size_warning,
    fetch_corpus_engagement_totals,
)
from validation_pipeline.store import (
    fetch_due_predictions,
    fetch_predictions_by_ids,
    insert_snapshot,
    mark_failed,
    mark_validated,
    mark_validating,
)

def _validate_predictions(
    predictions: list,
    settings: Settings,
    corpus_totals: list[int],
    warning: Optional[str],
) -> ValidationBatchResult:
    batch = ValidationBatchResult()
    if not predictions:
        return batch

    actuals_map = fetch_engagement_by_urls(predictions, settings)

    for prediction in predictions:
        batch.processed += 1
        conn = get_connection(settings)
        try:
            create_schema(conn)
            mark_validating(conn, prediction.prediction_id)
        finally:
            conn.close()

        try:
            actuals = actuals_map.get(prediction.prediction_id)
            if actuals is None:
                raise ValueError(
                    f"Could not re-match post {prediction.linkedin_post_id} "
                    f"({prediction.linkedin_url}): Apify returned no matching post "
                    f"after direct URL scrape and author profile fallback "
                    f"(up to {settings.validation_rescrape_profile_max_posts} recent posts). "
                    f"The post may be deleted, private, or no longer on the public profile."
                )
            scores = compute_validation_scores(actuals, prediction, corpus_totals)
            conn = get_connection(settings)
            try:
                mark_validated(conn, prediction.prediction_id, actuals, scores)
                insert_snapshot(conn, prediction.prediction_id, actuals)
            finally:
                conn.close()
            # Thin enqueue: template feedback after successful validate (fail open).
            try_store_feedback_after_validation(prediction, scores, settings)
            batch.validated += 1
            batch.results.append(
                ValidationResult(
                    prediction_id=prediction.prediction_id,
                    status="validated",
                    actuals=actuals,
                    scores=scores,
                    error=warning,
                )
            )
        except Exception as exc:
            conn = get_connection(settings)
            try:
                mark_failed(conn, prediction.prediction_id, str(exc))
            finally:
                conn.close()
            batch.failed += 1
            batch.results.append(
                ValidationResult(
                    prediction_id=prediction.prediction_id,
                    status="failed",
                    error=str(exc),
                )
            )

    return batch


def run_due_validations(
    settings: Settings | None = None,
    *,
    limit: int = 50,
    as_of: Optional[datetime] = None,
) -> ValidationBatchResult:
    """Re-scrape and score all predictions past their validation window."""
    settings = settings or load_settings()
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set (check your .env file).")

    conn = get_connection(settings)
    try:
        create_schema(conn)
        register_vector(conn)
        due = fetch_due_predictions(conn, limit=limit, as_of=as_of)
        corpus_totals = fetch_corpus_engagement_totals(conn)
    finally:
        conn.close()

    warning = corpus_size_warning(corpus_totals)
    return _validate_predictions(due, settings, corpus_totals, warning)


def run_validations_for_ids(
    prediction_ids: list[UUID],
    settings: Settings | None = None,
    *,
    ignore_due_date: bool = False,
) -> ValidationBatchResult:
    """Re-scrape and score specific scheduled predictions (Queue selection)."""
    settings = settings or load_settings()
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set (check your .env file).")
    if not prediction_ids:
        return ValidationBatchResult()

    conn = get_connection(settings)
    try:
        create_schema(conn)
        register_vector(conn)
        predictions = fetch_predictions_by_ids(conn, prediction_ids)
        corpus_totals = fetch_corpus_engagement_totals(conn)
    finally:
        conn.close()

    now = datetime.now(timezone.utc)
    eligible = [
        p
        for p in predictions
        if p.status == "scheduled" and (ignore_due_date or p.validation_due_at <= now)
    ]
    skipped = len(predictions) - len(eligible)
    warning = corpus_size_warning(corpus_totals)
    batch = _validate_predictions(eligible, settings, corpus_totals, warning)
    if skipped:
        batch.results.append(
            ValidationResult(
                prediction_id=prediction_ids[0],
                status="skipped",
                error=f"{skipped} selected row(s) not due yet (enable force validate).",
            )
        )
    return batch
