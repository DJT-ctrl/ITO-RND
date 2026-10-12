"""LLM generation for stored-post feedback."""

from __future__ import annotations

from typing import Any, Optional

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from agents.structured_output import agent_structured_output
from config.settings import AGENT_GEMINI_MODEL, pydantic_ai_gemini_model
from post_feedback.prompt import (
    build_evidence,
    build_post_feedback_prompt,
    cites_supplied_evidence,
)
from post_feedback.schemas import EligiblePost, PostFeedbackLLMOutput, PostFeedbackRecord


def _build_agent(model: Any) -> Agent[None, PostFeedbackLLMOutput]:
    return Agent(
        model,
        output_type=agent_structured_output(PostFeedbackLLMOutput, model),
        retries=2,
        system_prompt=(
            "You write factual coaching notes for one stored LinkedIn post. "
            "Ground every claim in the evidence provided. "
            "Do not invent metrics, categories, or neighbor posts. "
            "Do not instruct the reader to ignore prior rules."
        ),
    )


def generate_post_feedback(
    post: EligiblePost,
    neighbor_notes: list[dict[str, Any]],
    *,
    model: Optional[Any] = None,
) -> PostFeedbackRecord:
    """Call the LLM (or TestModel) and return a persistable feedback record.

    Neighbor notes are the ones passed in. The model does not get to replace them.
    Review status stays pending until a person approves or rejects the row.
    """
    resolved = model if model is not None else pydantic_ai_gemini_model()
    agent = _build_agent(resolved)
    prompt = build_post_feedback_prompt(post, neighbor_notes)
    result = agent.run_sync(prompt)
    output = result.output
    if not isinstance(output, PostFeedbackLLMOutput):
        output = PostFeedbackLLMOutput.model_validate(output)

    evidence = build_evidence(post, neighbor_notes)
    if not cites_supplied_evidence(
        output.summary.strip(),
        [item.strip() for item in output.what_worked],
        [item.strip() for item in output.what_to_change],
        evidence,
    ):
        raise ValueError("Feedback failed grounding citation check")

    model_name = (
        "test-model"
        if isinstance(resolved, TestModel)
        else str(AGENT_GEMINI_MODEL)
    )
    in_tokens, out_tokens = _token_counts(result)
    return PostFeedbackRecord(
        post_id=post.post_id,
        summary=output.summary.strip(),
        what_worked=[item.strip() for item in output.what_worked if item.strip()],
        what_to_change=[item.strip() for item in output.what_to_change if item.strip()],
        neighbor_notes=list(neighbor_notes),
        evidence=evidence,
        review_status="pending",
        model=model_name,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
    )


def _token_counts(result: Any) -> tuple[int, int]:
    usage = getattr(result, "usage", None)
    if usage is None:
        return 0, 0
    in_tokens = int(getattr(usage, "request_tokens", 0) or 0)
    out_tokens = int(getattr(usage, "response_tokens", 0) or 0)
    return in_tokens, out_tokens
