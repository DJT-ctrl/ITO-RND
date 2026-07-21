"""Batch + single-prediction feedback generation (Phase B templates + Phase G hybrid)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable
from uuid import UUID

from config.settings import AGENT_GEMINI_MODEL, Settings, load_settings
from feedback.generate import (
    FEEDBACK_VERSION,
    generate_template_feedback_from_record,
    generate_template_feedback_from_scores,
)
from feedback.hybrid import generate_hybrid_feedback
from feedback.queue import enqueue_feedback_job
from feedback.schemas import FeedbackPayload, FeedbackRecord
from feedback.store import (
    count_auto_approved_feedback_today,
    count_llm_feedback_generated_today,
    fetch_validated_prediction_ids_missing_feedback,
    refresh_cluster_stats,
    upsert_prediction_feedback,
)
from storage.vector_store import create_schema, get_connection
from telemetry.pricing import cost_from_tokens
from validation_pipeline.schemas import PredictionRecord, ValidationScores
from validation_pipeline.store import fetch_predictions_by_ids

logger = logging.getLogger(__name__)


@dataclass
class FeedbackBatchResult:
    processed: int = 0
    generated: int = 0
    failed: int = 0
    skipped: int = 0
    hybrid_generated: int = 0


@dataclass
class FeedbackWorkerResult:
    claimed: int = 0
    succeeded: int = 0
    failed: int = 0
    dead_lettered: int = 0


def _timed_template_generation(
    generator: Callable[..., FeedbackPayload],
    *args: Any,
    **kwargs: Any,
) -> tuple[FeedbackPayload, float]:
    started = time.perf_counter()
    payload = generator(*args, **kwargs)
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    return payload, latency_ms


def resolve_hybrid_review_status(
    settings: Settings,
    *,
    prediction_delta: float,
    auto_approved_today: int,
) -> tuple[str, str | None]:
    """Return (status, reviewed_by) for a successful hybrid write."""
    if not settings.validation_feedback_auto_approve_enabled:
        return "pending", None
    if abs(float(prediction_delta)) > float(
        settings.validation_feedback_auto_approve_delta_max
    ):
        return "pending", None
    if auto_approved_today >= int(
        settings.validation_feedback_auto_approve_max_per_day
    ):
        return "pending", None
    return "approved", "auto_approve"


def _store_feedback_for_prediction(
    prediction: PredictionRecord,
    settings: Settings,
    *,
    scores: ValidationScores | None = None,
) -> FeedbackRecord:
    """Write template v1 always; optionally hybrid v2 when LLM flag + caps allow."""
    conn = get_connection(settings)
    try:
        create_schema(conn)
        if scores is not None:
            payload, latency_ms = _timed_template_generation(
                generate_template_feedback_from_scores,
                prediction,
                scores,
            )
        else:
            payload, latency_ms = _timed_template_generation(
                generate_template_feedback_from_record,
                prediction,
            )
        record = upsert_prediction_feedback(
            conn,
            payload,
            feedback_version=FEEDBACK_VERSION,
            generation_method="template",
            generation_latency_ms=latency_ms,
            feedback_review_status="approved",
        )

        if not settings.validation_feedback_llm_enabled:
            return record

        used_today = count_llm_feedback_generated_today(conn)
        if used_today >= settings.validation_feedback_llm_max_per_day:
            logger.info(
                "LLM feedback daily cap reached (%s); skipping hybrid for %s",
                settings.validation_feedback_llm_max_per_day,
                prediction.prediction_id,
            )
            return record

        started = time.perf_counter()
        hybrid = generate_hybrid_feedback(prediction, settings)
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        if not hybrid.used_llm:
            return record

        cost_usd = cost_from_tokens(
            AGENT_GEMINI_MODEL,
            input_tokens=hybrid.input_tokens,
            output_tokens=hybrid.output_tokens,
        )
        auto_today = count_auto_approved_feedback_today(conn)
        delta = float(
            prediction.prediction_delta
            if prediction.prediction_delta is not None
            else hybrid.payload.delta_summary.prediction_delta
        )
        review_status, reviewed_by = resolve_hybrid_review_status(
            settings,
            prediction_delta=delta,
            auto_approved_today=auto_today,
        )
        return upsert_prediction_feedback(
            conn,
            hybrid.payload,
            feedback_version=hybrid.feedback_version,
            generation_method="hybrid",  # type: ignore[arg-type]
            generation_latency_ms=latency_ms,
            input_tokens=hybrid.input_tokens,
            output_tokens=hybrid.output_tokens,
            cost_usd=cost_usd,
            feedback_review_status=review_status,  # type: ignore[arg-type]
            reviewed_by=reviewed_by,
        )
    finally:
        conn.close()


def try_enqueue_feedback_after_validation(
    prediction: PredictionRecord,
    settings: Settings,
) -> bool:
    """Enqueue async feedback job after validate (fail open). Returns True if enqueued."""
    from validation_pipeline.age_aware import is_learning_eligible

    if not settings.validation_feedback_enabled:
        return False
    if not is_learning_eligible(
        prediction.validation_mode,
        age_aware_enabled=settings.validation_age_aware_enabled,
    ):
        logger.info(
            "Skipping feedback enqueue for %s (mode=%s, age-aware filter ON)",
            prediction.prediction_id,
            prediction.validation_mode,
        )
        return False
    try:
        conn = get_connection(settings)
        try:
            create_schema(conn)
            enqueue_feedback_job(conn, prediction.prediction_id)
        finally:
            conn.close()
        return True
    except Exception:
        logger.exception(
            "Feedback enqueue failed for prediction %s; continuing",
            prediction.prediction_id,
        )
        return False


def try_store_feedback_after_validation(
    prediction: PredictionRecord,
    scores: ValidationScores,
    settings: Settings,
) -> FeedbackRecord | None:
    """Sync post-validate hook: template (+ optional hybrid), fail open on errors.

    Prefer ``try_enqueue_feedback_after_validation`` from the validation worker;
    keep this for manual/backfill paths.
    """
    from validation_pipeline.age_aware import is_learning_eligible

    if not settings.validation_feedback_enabled:
        return None
    if not is_learning_eligible(
        prediction.validation_mode,
        age_aware_enabled=settings.validation_age_aware_enabled,
    ):
        logger.info(
            "Skipping feedback store for %s (mode=%s, age-aware filter ON)",
            prediction.prediction_id,
            prediction.validation_mode,
        )
        return None
    try:
        record = _store_feedback_for_prediction(prediction, settings, scores=scores)
        try:
            conn = get_connection(settings)
            try:
                create_schema(conn)
                refresh_cluster_stats(
                    conn,
                    age_aware_enabled=settings.validation_age_aware_enabled,
                )
            finally:
                conn.close()
        except Exception:
            logger.exception("Cluster stats refresh after feedback failed")
        return record
    except Exception:
        logger.exception(
            "Feedback generation failed for prediction %s; continuing",
            prediction.prediction_id,
        )
        return None


def process_feedback_job(
    prediction_id: UUID,
    settings: Settings,
) -> FeedbackRecord | None:
    """Generate feedback for one queued prediction (raises on failure).

    Returns None when age-aware filtering excludes the row (caller should
    still mark the job done).
    """
    from validation_pipeline.age_aware import is_learning_eligible

    conn = get_connection(settings)
    try:
        create_schema(conn)
        rows = fetch_predictions_by_ids(conn, [prediction_id])
        if not rows:
            raise ValueError(f"Prediction not found: {prediction_id}")
        prediction = rows[0]
        if prediction.status != "validated":
            raise ValueError(
                f"Prediction {prediction_id} status is {prediction.status!r}, "
                "expected validated"
            )
        if not is_learning_eligible(
            prediction.validation_mode,
            age_aware_enabled=settings.validation_age_aware_enabled,
        ):
            logger.info(
                "Skipping feedback job for %s (mode=%s, age-aware filter ON)",
                prediction_id,
                prediction.validation_mode,
            )
            return None
    finally:
        conn.close()

    record = _store_feedback_for_prediction(prediction, settings)
    try:
        conn = get_connection(settings)
        try:
            create_schema(conn)
            refresh_cluster_stats(
                conn,
                age_aware_enabled=settings.validation_age_aware_enabled,
            )
        finally:
            conn.close()
    except Exception:
        logger.exception("Cluster stats refresh after feedback job failed")
    return record


def run_feedback_worker(
    settings: Settings | None = None,
    *,
    limit: int = 20,
) -> FeedbackWorkerResult:
    """Claim and process pending feedback jobs."""
    from feedback.queue import (
        claim_feedback_jobs,
        mark_feedback_job_done,
        mark_feedback_job_failed,
    )

    settings = settings or load_settings()
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set (check your .env file).")
    if not settings.validation_feedback_enabled:
        return FeedbackWorkerResult()

    result = FeedbackWorkerResult()
    conn = get_connection(settings)
    try:
        create_schema(conn)
        claimed = claim_feedback_jobs(conn, limit=limit)
    finally:
        conn.close()

    result.claimed = len(claimed)
    for prediction_id in claimed:
        try:
            process_feedback_job(prediction_id, settings)
            conn = get_connection(settings)
            try:
                create_schema(conn)
                mark_feedback_job_done(conn, prediction_id)
            finally:
                conn.close()
            result.succeeded += 1
        except Exception as exc:
            logger.exception("Feedback worker failed for %s", prediction_id)
            conn = get_connection(settings)
            try:
                create_schema(conn)
                status = mark_feedback_job_failed(conn, prediction_id, str(exc))
            finally:
                conn.close()
            result.failed += 1
            if status == "dead":
                result.dead_lettered += 1

    return result


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
            conn,
            limit=limit,
            feedback_version=FEEDBACK_VERSION,
            age_aware_enabled=settings.validation_age_aware_enabled,
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
            record = _store_feedback_for_prediction(prediction, settings)
            batch.generated += 1
            if record.generation_method == "hybrid":
                batch.hybrid_generated += 1
        except Exception:
            logger.exception("Feedback batch failed for %s", prediction_id)
            batch.failed += 1

    if batch.generated:
        try:
            conn = get_connection(settings)
            try:
                create_schema(conn)
                refresh_cluster_stats(
                    conn,
                    age_aware_enabled=settings.validation_age_aware_enabled,
                )
            finally:
                conn.close()
        except Exception:
            logger.exception("Cluster stats refresh after feedback batch failed")

    return batch


def generate_feedback_for_prediction_id(
    prediction_id: UUID,
    settings: Settings | None = None,
) -> FeedbackRecord:
    """Generate (or regenerate) feedback for one validated prediction."""
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
    finally:
        conn.close()
    return _store_feedback_for_prediction(prediction, settings)
