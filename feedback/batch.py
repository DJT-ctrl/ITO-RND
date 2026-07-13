"""Batch + single-prediction feedback generation (Phase B templates)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable
from uuid import UUID

from config.settings import Settings, load_settings
from feedback.generate import (
    FEEDBACK_VERSION,
    generate_template_feedback_from_record,
    generate_template_feedback_from_scores,
)
from feedback.schemas import FeedbackPayload, FeedbackRecord
from feedback.store import (
    fetch_validated_prediction_ids_missing_feedback,
    refresh_cluster_stats,
    upsert_prediction_feedback,
)
from storage.vector_store import create_schema, get_connection
from validation_pipeline.schemas import PredictionRecord, ValidationScores
from validation_pipeline.store import fetch_predictions_by_ids

logger = logging.getLogger(__name__)


@dataclass
class FeedbackBatchResult:
    processed: int = 0
    generated: int = 0
    failed: int = 0
    skipped: int = 0


def _timed_template_generation(
    generator: Callable[..., FeedbackPayload],
    *args: Any,
    **kwargs: Any,
) -> tuple[FeedbackPayload, float]:
    started = time.perf_counter()
    payload = generator(*args, **kwargs)
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    return payload, latency_ms


def try_store_feedback_after_validation(
    prediction: PredictionRecord,
    scores: ValidationScores,
    settings: Settings,
) -> FeedbackRecord | None:
    """Thin post-validate hook: template feedback, fail open on errors."""
    if not settings.validation_feedback_enabled:
        return None
    try:
        payload, latency_ms = _timed_template_generation(
            generate_template_feedback_from_scores,
            prediction,
            scores,
        )
        conn = get_connection(settings)
        try:
            create_schema(conn)
            record = upsert_prediction_feedback(
                conn,
                payload,
                feedback_version=FEEDBACK_VERSION,
                generation_method="template",
                generation_latency_ms=latency_ms,
            )
            try:
                refresh_cluster_stats(conn)
            except Exception:
                logger.exception("Cluster stats refresh after feedback failed")
            return record
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "Feedback generation failed for prediction %s; continuing",
            prediction.prediction_id,
        )
        return None


def run_feedback_batch(
    settings: Settings | None = None,
    *,
    limit: int = 100,
) -> FeedbackBatchResult:
    """Backfill template feedback for validated predictions missing a v1 row."""
    settings = settings or load_settings()
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set (check your .env file).")
    if not settings.validation_feedback_enabled:
        return FeedbackBatchResult(skipped=limit)

    batch = FeedbackBatchResult()
    conn = get_connection(settings)
    try:
        create_schema(conn)
        missing_ids = fetch_validated_prediction_ids_missing_feedback(
            conn, limit=limit, feedback_version=FEEDBACK_VERSION
        )
        if not missing_ids:
            return batch
        predictions = fetch_predictions_by_ids(conn, missing_ids)
    finally:
        conn.close()

    by_id = {p.prediction_id: p for p in predictions}
    for prediction_id in missing_ids:
        batch.processed += 1
        prediction = by_id.get(prediction_id)
        if prediction is None:
            batch.failed += 1
            continue
        try:
            payload, latency_ms = _timed_template_generation(
                generate_template_feedback_from_record,
                prediction,
            )
            conn = get_connection(settings)
            try:
                create_schema(conn)
                upsert_prediction_feedback(
                    conn,
                    payload,
                    feedback_version=FEEDBACK_VERSION,
                    generation_method="template",
                    generation_latency_ms=latency_ms,
                )
            finally:
                conn.close()
            batch.generated += 1
        except Exception:
            logger.exception("Feedback batch failed for %s", prediction_id)
            batch.failed += 1

    if batch.generated:
        try:
            conn = get_connection(settings)
            try:
                create_schema(conn)
                refresh_cluster_stats(conn)
            finally:
                conn.close()
        except Exception:
            logger.exception("Cluster stats refresh after feedback batch failed")

    return batch


def generate_feedback_for_prediction_id(
    prediction_id: UUID,
    settings: Settings | None = None,
) -> FeedbackRecord:
    """Generate (or regenerate) template feedback for one validated prediction."""
    settings = settings or load_settings()
    conn = get_connection(settings)
    try:
        create_schema(conn)
        rows = fetch_predictions_by_ids(conn, [prediction_id])
        if not rows:
            raise ValueError(f"Prediction not found: {prediction_id}")
        prediction = rows[0]
        if prediction.status != "validated":
            raise ValueError(
                f"Prediction {prediction_id} status is {prediction.status!r}, expected validated"
            )
        payload, latency_ms = _timed_template_generation(
            generate_template_feedback_from_record,
            prediction,
        )
        return upsert_prediction_feedback(
            conn,
            payload,
            feedback_version=FEEDBACK_VERSION,
            generation_method="template",
            generation_latency_ms=latency_ms,
        )
    finally:
        conn.close()
