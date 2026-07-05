"""Shared state + dependency models for the Phase 3 evaluation cycle (T3.1).

`PostEvaluationState` is the result object returned by the orchestrator
(agents/orchestrator.py) once a cycle finishes. Only `draft_content` and
`similar_posts` are populated by T3.1 itself — the other three fields are
placeholders that future tasks will fill in:

  - `predictor_result` — T3.2 (Predictor Agent Development)
  - `diagnostics`      — T3.3 (Diagnostic Worker Agents), keyed by check name
                         (e.g. "seo", "clarity", "tone")
  - `variants`         — T3.4 (Variant Optimisation Engine)

`errors` collects non-fatal failures from individual agents (see
orchestrator.run_evaluation_cycle's use of asyncio.gather(return_exceptions=True))
so one failing agent doesn't drop the rest of the cycle's results.

`EvaluationDeps` is what gets passed to every PydanticAI `Agent.run(...,
deps=...)` call in the concurrent evaluation stage — it's the *read-only*
context (draft text + retrieved neighbors) that T3.2's Predictor Agent and
T3.3's Diagnostic Worker Agents will use to build their system prompts /
tool calls. It's a plain dataclass (not a BaseModel) because that's what
PydanticAI's `deps_type` expects.
"""

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field

from api.schemas import SimilarPost


@dataclass
class EvaluationDeps:
    draft_content: str
    similar_posts: list[SimilarPost] = field(default_factory=list)


class PostEvaluationState(BaseModel):
    draft_content: str
    similar_posts: list[SimilarPost] = Field(default_factory=list)
    predictor_result: Optional[dict] = None
    diagnostics: dict[str, dict] = Field(default_factory=dict)
    variants: list[dict] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
