"""Run RAG prediction for a collected post and persist the snapshot."""

from __future__ import annotations

import asyncio
from typing import Optional

from pgvector.psycopg import register_vector
from pydantic import BaseModel

from agents.orchestrator import _gather_similar_posts
from agents.predictor import PredictorOutput, apply_deterministic_prediction, build_predictor_agent
from agents.prompt_safety import build_evaluation_user_message
from agents.schemas import EvaluationDeps, PostEvaluationState
from config.settings import Settings, load_settings, pydantic_ai_gemini_model
from processors.benchmark import compute_neighbor_prediction
from storage.vector_store import create_schema, get_connection
from validation_pipeline.schemas import CollectedPost, NewPrediction, PredictionRecord
from validation_pipeline.store import insert_prediction, prediction_exists


class PredictionOutput(BaseModel):
    predicted_engagement_percentile: float
    predicted_total_engagement: Optional[int] = None
    prediction_method: Optional[str] = None
    neighbor_count: Optional[int] = None
    reasoning: Optional[str] = None


async def predict_for_post(
    post: CollectedPost,
    settings: Settings,
) -> PredictionOutput:
    """Embed, retrieve neighbors, and run the predictor agent for one post."""
    state = PostEvaluationState(draft_content=post.content)
    await _gather_similar_posts(state, settings, user_id=None)

    neighbor_prediction = compute_neighbor_prediction(
        state.similar_posts,
        draft_follower_count=post.follower_count,
    )
    deps = EvaluationDeps(
        draft_content=post.content,
        similar_posts=state.similar_posts,
        neighbor_prediction=neighbor_prediction,
        draft_follower_count=post.follower_count,
    )

    predictor = build_predictor_agent(pydantic_ai_gemini_model())
    result = await predictor.run(build_evaluation_user_message(post.content), deps=deps)
    output = result.output
    if isinstance(output, PredictorOutput) and neighbor_prediction:
        output = apply_deterministic_prediction(output, neighbor_prediction)

    if isinstance(output, PredictorOutput):
        return PredictionOutput(
            predicted_engagement_percentile=output.predicted_engagement_percentile,
            predicted_total_engagement=output.predicted_total_engagement,
            prediction_method=neighbor_prediction.get("method") if neighbor_prediction else None,
            neighbor_count=neighbor_prediction.get("neighbor_count") if neighbor_prediction else None,
            reasoning=output.reasoning,
        )

    if isinstance(output, BaseModel):
        data = output.model_dump()
    elif isinstance(output, dict):
        data = output
    else:
        data = {}

    return PredictionOutput(
        predicted_engagement_percentile=float(
            data.get("predicted_engagement_percentile", neighbor_prediction.get("percentile", 50.0))
        ),
        predicted_total_engagement=data.get("predicted_total_engagement")
        or neighbor_prediction.get("total_engagement_estimate"),
        prediction_method=neighbor_prediction.get("method") if neighbor_prediction else None,
        neighbor_count=neighbor_prediction.get("neighbor_count") if neighbor_prediction else None,
        reasoning=data.get("reasoning"),
    )


def save_prediction(
    post: CollectedPost,
    prediction: PredictionOutput,
    settings: Settings,
) -> PredictionRecord:
    """Persist a new prediction row with scheduled validation time."""
    validation_due_at = post.posted_at + settings.validation_window()
    new_prediction = NewPrediction(
        linkedin_post_id=post.linkedin_post_id,
        linkedin_url=post.linkedin_url,
        author_public_id=post.author_public_id,
        content=post.content,
        posted_at=post.posted_at,
        predicted_engagement_percentile=prediction.predicted_engagement_percentile,
        predicted_total_engagement=prediction.predicted_total_engagement,
        prediction_method=prediction.prediction_method,
        neighbor_count=prediction.neighbor_count,
        validation_due_at=validation_due_at,
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


def run_predict_for_post(post: CollectedPost, settings: Settings | None = None) -> PredictionRecord | None:
    """Sync wrapper for CLI and tests."""
    settings = settings or load_settings()
    return asyncio.run(predict_and_save(post, settings))
