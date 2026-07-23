"""LLM generation for A1 post-mortems."""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from agents.structured_output import agent_structured_output
from config.settings import AGENT_GEMINI_MODEL, pydantic_ai_gemini_model
from post_mortems.prompt import build_evidence, build_post_mortem_prompt
from post_mortems.schemas import (
    AnomalyPostRow,
    PostMortemLLMOutput,
    PostMortemRecord,
)

logger = logging.getLogger(__name__)


def _build_agent(model: Any) -> Agent[None, PostMortemLLMOutput]:
    return Agent(
        model,
        output_type=agent_structured_output(PostMortemLLMOutput, model),
        system_prompt=(
            "You are a careful analyst of social engagement anomalies. "
            "Ground every claim in provided metrics."
        ),
    )


def generate_post_mortem(
    row: AnomalyPostRow,
    *,
    model: Optional[Any] = None,
) -> PostMortemRecord:
    """Call the LLM (or TestModel) and return a persistable post-mortem record."""
    resolved = model if model is not None else pydantic_ai_gemini_model()
    agent = _build_agent(resolved)
    prompt = build_post_mortem_prompt(row)
    result = agent.run_sync(prompt)
    output = result.output
    model_name = (
        "test-model"
        if isinstance(resolved, TestModel)
        else str(AGENT_GEMINI_MODEL)
    )
    return PostMortemRecord(
        post_id=row.post_id,
        machine_reasons=list(row.anomaly_reasons),
        verdict=output.verdict,
        summary=output.summary.strip(),
        evidence=build_evidence(row),
        lesson_for_models=output.lesson_for_models.strip(),
        model=model_name,
    )
