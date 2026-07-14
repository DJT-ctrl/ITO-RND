"""Hybrid LLM enrichment for large prediction misses (Phase G)."""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents.prompt_safety import wrap_untrusted_text
from agents.structured_output import agent_structured_output
from config.settings import Settings, pydantic_ai_gemini_model
from feedback.generate import (
    ACCURATE_DELTA_ABS,
    FEEDBACK_VERSION_V2,
    generate_template_feedback_from_record,
)
from feedback.schemas import FeedbackPayload
from validation_pipeline.schemas import PredictionRecord

logger = logging.getLogger(__name__)


class HybridLessonOutput(BaseModel):
    what_missed: list[str] = Field(default_factory=list, min_length=1)
    lessons_for_similar_posts: list[str] = Field(default_factory=list, min_length=1)


class HybridGenerationResult(BaseModel):
    payload: FeedbackPayload
    feedback_version: str
    generation_method: str
    feedback_review_status: str
    input_tokens: int = 0
    output_tokens: int = 0
    used_llm: bool = False
    skip_reason: Optional[str] = None


def should_use_llm_for_delta(prediction_delta: float, delta_min: float) -> bool:
    return abs(float(prediction_delta)) >= float(delta_min)


def generate_hybrid_feedback(
    record: PredictionRecord,
    settings: Settings,
    *,
    follower_count: Optional[int] = None,
) -> HybridGenerationResult:
    """Template base; optionally enrich what_missed/lessons via LLM for large misses.

    On LLM failure or disabled flag, returns template v1 approved payload.
    Successful LLM enrichment returns v2 hybrid pending review.
    """
    template = generate_template_feedback_from_record(
        record, follower_count=follower_count
    )
    delta = float(record.prediction_delta or 0.0)

    if not settings.validation_feedback_llm_enabled:
        return HybridGenerationResult(
            payload=template,
            feedback_version="v1",
            generation_method="template",
            feedback_review_status="approved",
            skip_reason="llm_disabled",
        )

    if abs(delta) < ACCURATE_DELTA_ABS:
        return HybridGenerationResult(
            payload=template,
            feedback_version="v1",
            generation_method="template",
            feedback_review_status="approved",
            skip_reason="delta_within_accurate_band",
        )

    if not should_use_llm_for_delta(delta, settings.validation_feedback_llm_delta_min):
        return HybridGenerationResult(
            payload=template,
            feedback_version="v1",
            generation_method="template",
            feedback_review_status="approved",
            skip_reason="delta_below_llm_threshold",
        )

    try:
        lessons, in_tokens, out_tokens = _run_hybrid_llm(template, record, settings)
    except Exception:
        logger.exception(
            "Hybrid LLM feedback failed for %s; keeping template",
            record.prediction_id,
        )
        return HybridGenerationResult(
            payload=template,
            feedback_version="v1",
            generation_method="template",
            feedback_review_status="approved",
            skip_reason="llm_error",
        )

    enriched = template.model_copy(
        update={
            "what_missed": lessons.what_missed,
            "lessons_for_similar_posts": lessons.lessons_for_similar_posts,
        }
    )
    return HybridGenerationResult(
        payload=enriched,
        feedback_version=FEEDBACK_VERSION_V2,
        generation_method="hybrid",
        feedback_review_status="pending",
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        used_llm=True,
    )


def _run_hybrid_llm(
    template: FeedbackPayload,
    record: PredictionRecord,
    settings: Settings,
) -> tuple[HybridLessonOutput, int, int]:
    """Call Gemini for grounded lesson text; validate schema."""
    model = pydantic_ai_gemini_model()
    agent: Agent[None, HybridLessonOutput] = Agent(
        model,
        output_type=agent_structured_output(HybridLessonOutput, model),
        retries=2,
        system_prompt=(
            "You write short, factual lessons about LinkedIn engagement prediction misses. "
            "Cite only the numeric fields provided. Do not invent counts or percentiles. "
            "Do not instruct the reader to ignore prior rules. "
            "Keep each bullet under 160 characters."
        ),
    )
    delta = template.delta_summary
    user_prompt = wrap_untrusted_text(
        (
            f"predicted_percentile={delta.predicted_percentile}\n"
            f"actual_percentile={delta.actual_percentile}\n"
            f"prediction_delta={delta.prediction_delta}\n"
            f"direction={delta.direction}\n"
            f"likes_delta={record.likes_delta}\n"
            f"comments_delta={record.comments_delta}\n"
            f"shares_delta={record.shares_delta}\n"
            f"total_engagement_delta={record.total_engagement_delta}\n"
            f"prediction_method={record.prediction_method}\n"
            f"cluster_id={template.cluster_id}\n"
            f"template_what_missed={template.what_missed}\n"
            f"template_lessons={template.lessons_for_similar_posts}\n"
            "Return what_missed and lessons_for_similar_posts that cite these numbers."
        ),
        tag="feedback_facts",
    )
    result = agent.run_sync(user_prompt)
    output = result.output
    if not isinstance(output, HybridLessonOutput):
        output = HybridLessonOutput.model_validate(output)
    # Grounding check: at least one string must mention a known number.
    cited = _cites_grounded_numbers(output, template, record)
    if not cited:
        raise ValueError("LLM lessons failed grounding citation check")
    usage = getattr(result, "usage", None)
    in_tokens = int(getattr(usage, "request_tokens", 0) or 0) if usage else 0
    out_tokens = int(getattr(usage, "response_tokens", 0) or 0) if usage else 0
    return output, in_tokens, out_tokens


def _cites_grounded_numbers(
    lessons: HybridLessonOutput,
    template: FeedbackPayload,
    record: PredictionRecord,
) -> bool:
    blob = " ".join(lessons.what_missed + lessons.lessons_for_similar_posts)
    candidates = {
        f"{template.delta_summary.predicted_percentile:.0f}",
        f"{template.delta_summary.actual_percentile:.0f}",
        f"{abs(template.delta_summary.prediction_delta):.0f}",
        f"{template.delta_summary.predicted_percentile:.1f}",
        f"{template.delta_summary.actual_percentile:.1f}",
    }
    if record.likes_delta is not None:
        candidates.add(f"{abs(record.likes_delta):.0f}")
    return any(token and token in blob for token in candidates)
