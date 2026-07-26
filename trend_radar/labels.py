"""Optional LLM labels for A2 trend clusters."""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents.prompt_safety import PROMPT_DATA_PREAMBLE, wrap_untrusted_text
from agents.structured_output import agent_structured_output
from config.settings import pydantic_ai_gemini_model
from trend_radar.clustering import keyword_fallback_label
from trend_radar.schemas import ClusterSnapshot

logger = logging.getLogger(__name__)


class ClusterLabelOutput(BaseModel):
    label: str = Field(min_length=1, max_length=80)


def _build_agent(model: Any) -> Agent[None, ClusterLabelOutput]:
    return Agent(
        model,
        output_type=agent_structured_output(ClusterLabelOutput, model),
        system_prompt=(
            "You name LinkedIn topic clusters in 2-6 words. "
            "No quotes, no hashtags, no marketing fluff."
        ),
    )


def label_cluster(
    snap: ClusterSnapshot,
    *,
    model: Optional[Any] = None,
) -> str:
    """Return an LLM label, falling back to topic keywords on failure."""
    fallback = keyword_fallback_label(snap)
    snippets = "\n".join(
        wrap_untrusted_text(text, tag="post_excerpt")
        for text in snap.example_snippets
        if text
    )
    if not snippets:
        return fallback

    prompt = f"""{PROMPT_DATA_PREAMBLE}

Name this topic cluster (2-6 words) from the excerpts and topic hints.
Topic hints: {", ".join(snap.topic_hints) or "(none)"}
Post count: {snap.post_count}

{snippets}
"""
    try:
        resolved = model if model is not None else pydantic_ai_gemini_model()
        agent = _build_agent(resolved)
        result = agent.run_sync(prompt)
        label = (result.output.label or "").strip().strip('"')
        if not label:
            return fallback
        return label[:80]
    except Exception:
        logger.exception("Cluster label LLM failed for %s", snap.cluster_id)
        return fallback
