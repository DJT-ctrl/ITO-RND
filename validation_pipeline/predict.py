"""Run RAG prediction for a collected post and persist the snapshot."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pgvector.psycopg import register_vector
from pydantic import BaseModel
from pydantic_ai import UnexpectedModelBehavior

from agents.cross_reference import (
    CrossReferencePolicy,
    select_cross_references,
    unavailable_cross_references,
)
from agents.orchestrator import _gather_similar_posts
from agents.predictor import PredictorOutput, build_predictor_agent, resolve_final_prediction
from agents.prompt_safety import build_evaluation_user_message
from agents.schemas import EvaluationDeps, PostEvaluationState
from config.settings import Settings, load_settings, pydantic_ai_gemini_model
from feedback.calibration import apply_calibration
from feedback.retrieve import (
    example_limit_for_format,
    fetch_cluster_feedback_with_fallback,
    format_feedback_context_block,
)
from feedback.routing import assign_cluster_id
from feedback.store import (
    fetch_cluster_centroids,
    resolve_calibration_stats,
    resolve_post_niche,
)
from processors.benchmark import compute_neighbor_prediction
from processors.gemini_retry import async_call_with_gemini_retry
from storage.vector_store import create_schema, get_connection
from validation_pipeline.prediction_telemetry import build_prediction_telemetry
from validation_pipeline.schemas import (
    CollectedPost,
    NewPrediction,
    PredictionRecord,
    PredictionTelemetry,
)
from validation_pipeline.store import insert_prediction, prediction_exists

logger = logging.getLogger(__name__)


class PredictionOutput(BaseModel):
    predicted_engagement_percentile: float
    predicted_total_engagement: Optional[int] = None
    predicted_likes: Optional[int] = None
    predicted_comments: Optional[int] = None
    predicted_shares: Optional[int] = None
    prediction_method: Optional[str] = None
    neighbor_count: Optional[int] = None
    reasoning: Optional[str] = None
    telemetry: PredictionTelemetry
    embedding: Optional[list[float]] = None
    embedding_model_version: Optional[str] = None


def _apply_calibration_to_neighbor_prediction(
    neighbor_prediction: dict[str, Any] | None,
    settings: Settings,
    *,
    content: str = "",
    follower_count: Optional[int] = None,
    niche: Optional[str] = None,
    linkedin_post_id: Optional[str] = None,
    embedding: Optional[list[float]] = None,
    query_horizon_hours: float | None = None,
) -> dict[str, Any] | None:
    """Adjust neighbor percentile using cluster→global mean_delta when enabled.

    Fail open: any DB/stats error leaves the raw neighbor prediction unchanged.
    Engagement count estimates are not adjusted in Phase A/C.
    """
    if not neighbor_prediction or not settings.validation_calibration_enabled:
        return neighbor_prediction

    raw_percentile = float(neighbor_prediction.get("percentile", 50.0))
    try:
        conn = get_connection(settings)
        try:
            create_schema(conn)
            resolved_niche = resolve_post_niche(
                niche=niche,
                linkedin_post_id=linkedin_post_id,
                conn=conn,
            )
            centroids = fetch_cluster_centroids(conn)
            cluster_id = assign_cluster_id(
                content,
                follower_count,
                niche=resolved_niche,
                embedding=embedding,
                centroids=centroids or None,
            )
            stats = resolve_calibration_stats(
                conn,
                cluster_id=cluster_id,
                cluster_n_min=settings.validation_cluster_n_min,
                age_aware_enabled=settings.validation_age_aware_enabled,
                multi_horizon_learning=settings.validation_multi_horizon_learning,
                query_horizon_hours=query_horizon_hours,
            )
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "Calibration stats fetch failed; using raw neighbor percentile"
        )
        cluster_id = assign_cluster_id(
            content, follower_count, niche=niche, embedding=embedding
        )
        calibrated = dict(neighbor_prediction)
        calibrated["raw_percentile"] = raw_percentile
        calibrated["calibrated_percentile"] = raw_percentile
        calibrated["mean_delta"] = None
        calibrated["n_validated"] = None
        calibrated["calibration_applied"] = False
        calibrated["calibration_skip_reason"] = "stats_fetch_error"
        calibrated["cluster_id"] = cluster_id
        calibrated["calibration_source"] = None
        return calibrated

    # Cluster stats use cluster_n_min; global fallback uses validation_calibration_n_min.
    n_min = (
        settings.validation_cluster_n_min
        if stats.source == "cluster"
        else settings.validation_calibration_n_min
    )
    result = apply_calibration(
        raw_percentile,
        stats.mean_delta,
        stats.n_validated,
        n_min,
    )
    calibrated = dict(neighbor_prediction)
    calibrated["percentile"] = result.calibrated_percentile
    calibrated["raw_percentile"] = result.raw_percentile
    calibrated["calibrated_percentile"] = result.calibrated_percentile
    calibrated["mean_delta"] = result.mean_delta
    calibrated["n_validated"] = result.n_validated
    calibrated["calibration_applied"] = result.applied
    calibrated["calibration_skip_reason"] = result.skip_reason
    calibrated["cluster_id"] = cluster_id
    calibrated["calibration_source"] = stats.source
    if result.applied:
        method = str(calibrated.get("method") or "neighbor")
        base = (
            method.replace("+cluster+calibrated", "")
            .replace("+calibrated", "")
        )
        if stats.source == "cluster":
            calibrated["method"] = f"{base}+cluster+calibrated"
        else:
            calibrated["method"] = f"{base}+calibrated"
    return calibrated


def _load_feedback_context(
    settings: Settings,
    *,
    content: str,
    follower_count: Optional[int] = None,
    niche: Optional[str] = None,
    linkedin_post_id: Optional[str] = None,
    exclude_prediction_id: Optional[UUID] = None,
    embedding: Optional[list[float]] = None,
    query_horizon_hours: float | None = None,
) -> tuple[Optional[str], Optional[str], int]:
    """Fetch cluster feedback for prompt injection. Fail open → empty context."""
    if not settings.validation_feedback_injection_enabled:
        return None, None, 0

    try:
        conn = get_connection(settings)
        try:
            create_schema(conn)
            resolved_niche = resolve_post_niche(
                niche=niche,
                linkedin_post_id=linkedin_post_id,
                conn=conn,
            )
            centroids = fetch_cluster_centroids(conn)
            cluster_id = assign_cluster_id(
                content,
                follower_count,
                niche=resolved_niche,
                embedding=embedding,
                centroids=centroids or None,
            )
            (
                records,
                resolved_cluster_id,
                rollup_summary,
                mean_delta,
                sample_count,
            ) = fetch_cluster_feedback_with_fallback(
                conn,
                cluster_id,
                limit=example_limit_for_format(
                    settings.validation_feedback_injection_format,
                    settings.validation_feedback_injection_limit,
                ),
                exclude_prediction_id=exclude_prediction_id,
                approved_only=True,
                query_embedding=embedding,
                cluster_n_min=settings.validation_cluster_n_min,
                age_aware_enabled=settings.validation_age_aware_enabled,
                multi_horizon_learning=settings.validation_multi_horizon_learning,
                query_horizon_hours=query_horizon_hours,
            )
        finally:
            conn.close()
    except Exception:
        logger.exception("Feedback retrieval failed; predicting without feedback block")
        cluster_id = assign_cluster_id(
            content, follower_count, niche=niche, embedding=embedding
        )
        return None, cluster_id, 0

    block = format_feedback_context_block(
        records,
        cluster_id=resolved_cluster_id,
        injection_format=settings.validation_feedback_injection_format,
        rollup_summary=rollup_summary,
        mean_delta=mean_delta,
        sample_count=sample_count,
    )
    return (block or None), cluster_id, len(records)


async def predict_for_post(
    post: CollectedPost,
    settings: Settings,
    *,
    target_horizon_hours: float | None = None,
    prediction_lane: str | None = None,
    age_hours_at_predict: float | None = None,
) -> PredictionOutput:
    """Embed, retrieve neighbors, and run the predictor agent for one post."""
    return await async_call_with_gemini_retry(
        lambda: _predict_for_post_impl(
            post,
            settings,
            target_horizon_hours=target_horizon_hours,
            prediction_lane=prediction_lane,
            age_hours_at_predict=age_hours_at_predict,
        ),
        label=f"Predict post {post.linkedin_post_id}",
    )


async def _predict_for_post_impl(
    post: CollectedPost,
    settings: Settings,
    *,
    target_horizon_hours: float | None = None,
    prediction_lane: str | None = None,
    age_hours_at_predict: float | None = None,
) -> PredictionOutput:
    """Inner predict implementation (retried by predict_for_post on 429/5xx)."""
    from validation_pipeline.age_buckets import bucket_for_hours

    horizon = (
        float(target_horizon_hours)
        if target_horizon_hours is not None
        else float(settings.validation_window_hours)
    )
    age_bucket = bucket_for_hours(horizon)
    state = PostEvaluationState(draft_content=post.content)
    retrieval_context = await _gather_similar_posts(
        state,
        settings,
        user_id=None,
        prefer_niche=post.niche,
        prefer_age_hours=horizon,
        include_global_candidates=settings.cross_reference_enabled,
        global_candidate_limit=settings.cross_reference_candidate_limit,
    )

    neighbor_prediction = compute_neighbor_prediction(
        state.similar_posts,
        draft_follower_count=post.follower_count,
    )
    neighbor_prediction = _apply_calibration_to_neighbor_prediction(
        neighbor_prediction,
        settings,
        content=post.content,
        follower_count=post.follower_count,
        niche=post.niche,
        linkedin_post_id=post.linkedin_post_id,
        embedding=state.query_embedding,
        query_horizon_hours=horizon,
    )
    feedback_context, feedback_cluster_id, feedback_count = _load_feedback_context(
        settings,
        content=post.content,
        follower_count=post.follower_count,
        niche=post.niche,
        linkedin_post_id=post.linkedin_post_id,
        embedding=state.query_embedding,
        query_horizon_hours=horizon,
    )
    if neighbor_prediction is not None:
        neighbor_prediction = dict(neighbor_prediction)
        neighbor_prediction["feedback_injected"] = bool(feedback_context)
        neighbor_prediction["feedback_count"] = feedback_count
        if feedback_cluster_id:
            neighbor_prediction.setdefault("cluster_id", feedback_cluster_id)

    cross_references = None
    if settings.cross_reference_enabled:
        if retrieval_context.global_candidate_error:
            cross_references = unavailable_cross_references(
                neighbor_prediction,
                "Global cross-reference candidate retrieval failed during validation prediction.",
            )
        else:
            cross_references = select_cross_references(
                retrieval_context.global_candidates,
                neighbor_prediction,
                policy=CrossReferencePolicy(
                    max_references=settings.cross_reference_max_references,
                    min_percentile_uplift=settings.cross_reference_min_percentile_uplift,
                    max_cosine_distance=settings.cross_reference_max_cosine_distance,
                ),
                prefer_niche=post.niche,
                prefer_age_hours=horizon,
            )

    cross_reference_status = cross_references.status if cross_references else None
    cross_reference_count = len(cross_references.references) if cross_references else 0
    cross_reference_adjusted_count = (
        sum(
            1
            for reference in cross_references.references
            if reference.comparison_metric == "audience_adjusted_percentile"
        )
        if cross_references
        else 0
    )

    deps = EvaluationDeps(
        draft_content=post.content,
        similar_posts=state.similar_posts,
        cross_references=cross_references,
        neighbor_prediction=neighbor_prediction,
        draft_follower_count=post.follower_count,
        feedback_context=feedback_context,
        posted_at=post.posted_at,
        target_horizon_hours=horizon,
        prediction_lane=prediction_lane,  # type: ignore[arg-type]
        age_hours_at_predict=age_hours_at_predict,
        age_bucket=age_bucket,
    )

    predictor = build_predictor_agent(pydantic_ai_gemini_model())
    try:
        result = await predictor.run(build_evaluation_user_message(post.content), deps=deps)
    except UnexpectedModelBehavior:
        if not neighbor_prediction:
            raise
        telemetry = build_prediction_telemetry(
            neighbor_prediction,
            calibration_enabled=settings.validation_calibration_enabled,
            feedback_injection_enabled=settings.validation_feedback_injection_enabled,
            feedback_context=feedback_context,
            feedback_count=feedback_count,
            cluster_id=feedback_cluster_id,
            injectability={
                "injectability_mode": settings.validation_injectability_mode,
                "soft_blend_weight": settings.validation_soft_blend_weight,
                "target_horizon_hours": horizon,
                "prediction_lane": prediction_lane,
                "age_bucket": age_bucket,
                "neighbor_age_prefer": True,
            },
            cross_reference_status=cross_reference_status,
            cross_reference_count=cross_reference_count,
            cross_reference_adjusted_count=cross_reference_adjusted_count,
        )
        return _deterministic_prediction_output(
            neighbor_prediction,
            telemetry=telemetry,
            reasoning=(
                "Predictor could not return structured reasoning after retries "
                "(Gemini MALFORMED_FUNCTION_CALL). Scores use deterministic "
                "neighbor weighting only."
            ),
            embedding=state.query_embedding,
            embedding_model_version=state.embedding_model_version,
        )
    output = result.output
    injectability_meta: dict[str, Any] = {
        "injectability_mode": settings.validation_injectability_mode,
        "soft_blend_weight": float(settings.validation_soft_blend_weight),
        "target_horizon_hours": horizon,
        "prediction_lane": prediction_lane,
        "age_bucket": age_bucket,
        "neighbor_age_prefer": True,
    }
    if isinstance(output, PredictorOutput):
        output, injectability_meta = resolve_final_prediction(
            output,
            neighbor_prediction,
            mode=settings.validation_injectability_mode,
            soft_blend_weight=settings.validation_soft_blend_weight,
            shadow_mode_enabled=settings.validation_shadow_mode_enabled,
        )
        injectability_meta.update(
            {
                "target_horizon_hours": horizon,
                "prediction_lane": prediction_lane,
                "age_bucket": age_bucket,
                "neighbor_age_prefer": True,
            }
        )

    telemetry = build_prediction_telemetry(
        neighbor_prediction,
        calibration_enabled=settings.validation_calibration_enabled,
        feedback_injection_enabled=settings.validation_feedback_injection_enabled,
        feedback_context=feedback_context,
        feedback_count=feedback_count,
        cluster_id=feedback_cluster_id,
        injectability=injectability_meta,
        cross_reference_status=cross_reference_status,
        cross_reference_count=cross_reference_count,
        cross_reference_adjusted_count=cross_reference_adjusted_count,
    )

    if isinstance(output, PredictorOutput):
        return PredictionOutput(
            predicted_engagement_percentile=output.predicted_engagement_percentile,
            predicted_total_engagement=output.predicted_total_engagement,
            predicted_likes=output.predicted_likes,
            predicted_comments=output.predicted_comments,
            predicted_shares=output.predicted_shares,
            prediction_method=neighbor_prediction.get("method") if neighbor_prediction else None,
            neighbor_count=neighbor_prediction.get("neighbor_count") if neighbor_prediction else None,
            reasoning=output.reasoning,
            telemetry=telemetry,
            embedding=state.query_embedding,
            embedding_model_version=state.embedding_model_version,
        )

    if isinstance(output, BaseModel):
        data = output.model_dump()
    elif isinstance(output, dict):
        data = output
    else:
        data = {}

    return PredictionOutput(
        predicted_engagement_percentile=float(
            data.get(
                "predicted_engagement_percentile",
                neighbor_prediction.get("percentile", 50.0) if neighbor_prediction else 50.0,
            )
        ),
        predicted_total_engagement=data.get("predicted_total_engagement")
        or (neighbor_prediction.get("total_engagement_estimate") if neighbor_prediction else None),
        predicted_likes=data.get(
            "predicted_likes",
            neighbor_prediction.get("predicted_likes") if neighbor_prediction else None,
        ),
        predicted_comments=data.get(
            "predicted_comments",
            neighbor_prediction.get("predicted_comments") if neighbor_prediction else None,
        ),
        predicted_shares=data.get(
            "predicted_shares",
            neighbor_prediction.get("predicted_shares") if neighbor_prediction else None,
        ),
        prediction_method=neighbor_prediction.get("method") if neighbor_prediction else None,
        neighbor_count=neighbor_prediction.get("neighbor_count") if neighbor_prediction else None,
        reasoning=data.get("reasoning"),
        telemetry=telemetry,
        embedding=state.query_embedding,
        embedding_model_version=state.embedding_model_version,
    )


def save_prediction(
    post: CollectedPost,
    prediction: PredictionOutput,
    settings: Settings,
    *,
    validation_due_at: Optional[datetime] = None,
    is_backtest: bool = False,
    validation_window_hours: float | None = None,
    prediction_lane: str | None = None,
    scraped_at_predict: Optional[datetime] = None,
) -> PredictionRecord:
    """Persist a new prediction row with scheduled validation time."""
    due_at = validation_due_at or (post.posted_at + settings.validation_window())
    horizon = (
        float(validation_window_hours)
        if validation_window_hours is not None
        else float(settings.validation_window_hours)
    )
    new_prediction = NewPrediction(
        linkedin_post_id=post.linkedin_post_id,
        linkedin_url=post.linkedin_url,
        author_public_id=post.author_public_id,
        content=post.content,
        posted_at=post.posted_at,
        predicted_engagement_percentile=prediction.predicted_engagement_percentile,
        predicted_total_engagement=prediction.predicted_total_engagement,
        predicted_likes=prediction.predicted_likes,
        predicted_comments=prediction.predicted_comments,
        predicted_shares=prediction.predicted_shares,
        baseline_likes=post.likes,
        baseline_comments=post.comments,
        baseline_shares=post.shares,
        baseline_total_engagement=post.total_engagement,
        prediction_method=prediction.prediction_method,
        neighbor_count=prediction.neighbor_count,
        telemetry=prediction.telemetry,
        embedding=prediction.embedding,
        embedding_model_version=prediction.embedding_model_version,
        validation_due_at=due_at,
        is_backtest=is_backtest,
        prediction_horizon_hours=horizon,
        prediction_lane=prediction_lane,  # type: ignore[arg-type]
        scraped_at_predict=scraped_at_predict,
    )
    conn = get_connection(settings)
    try:
        create_schema(conn)
        register_vector(conn)
        return insert_prediction(conn, new_prediction)
    finally:
        conn.close()


async def predict_and_save(
    post: CollectedPost,
    settings: Settings,
) -> PredictionRecord | None:
    """Predict and persist unless this post is already tracked."""
    conn = get_connection(settings)
    try:
        create_schema(conn)
        if prediction_exists(conn, post.linkedin_post_id):
            return None
    finally:
        conn.close()

    prediction = await predict_for_post(post, settings)
    return save_prediction(post, prediction, settings)


def _deterministic_prediction_output(
    neighbor_prediction: dict[str, Any],
    *,
    telemetry: PredictionTelemetry,
    reasoning: str,
    embedding: Optional[list[float]] = None,
    embedding_model_version: Optional[str] = None,
) -> PredictionOutput:
    return PredictionOutput(
        predicted_engagement_percentile=float(neighbor_prediction["percentile"]),
        predicted_total_engagement=int(neighbor_prediction["total_engagement_estimate"]),
        predicted_likes=int(neighbor_prediction.get("predicted_likes", 0)),
        predicted_comments=int(neighbor_prediction.get("predicted_comments", 0)),
        predicted_shares=int(neighbor_prediction.get("predicted_shares", 0)),
        prediction_method=neighbor_prediction.get("method"),
        neighbor_count=neighbor_prediction.get("neighbor_count"),
        reasoning=reasoning,
        telemetry=telemetry,
        embedding=embedding,
        embedding_model_version=embedding_model_version,
    )


def run_predict_for_post(post: CollectedPost, settings: Settings | None = None) -> PredictionRecord | None:
    """Sync wrapper for CLI and tests."""
    settings = settings or load_settings()
    return asyncio.run(predict_and_save(post, settings))
