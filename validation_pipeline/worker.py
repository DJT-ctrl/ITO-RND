"""Process due prediction validations (re-scrape + score)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pgvector.psycopg import register_vector

from config.settings import Settings, load_settings
from storage.vector_store import create_schema, get_connection
from validation_pipeline.rescrape import fetch_engagement
from validation_pipeline.schemas import ValidationBatchResult, ValidationResult
from validation_pipeline.scoring import (
    compute_validation_scores,
    corpus_size_warning,
    fetch_corpus_engagement_totals,
)
from validation_pipeline.store import (
    fetch_due_predictions,
    insert_snapshot,
    mark_failed,
    mark_validated,
    mark_validating,
)


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

    batch = ValidationBatchResult()
    warning = corpus_size_warning(corpus_totals)

    for prediction in due:
        batch.processed += 1
        conn = get_connection(settings)
        try:
            create_schema(conn)
            mark_validating(conn, prediction.prediction_id)
        finally:
            conn.close()

        try:
            actuals = fetch_engagement(prediction, settings)
            scores = compute_validation_scores(actuals, prediction, corpus_totals)
            conn = get_connection(settings)
            try:
                mark_validated(conn, prediction.prediction_id, actuals, scores)
                insert_snapshot(conn, prediction.prediction_id, actuals)
            finally:
                conn.close()
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
