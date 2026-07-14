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
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from api.schemas import SimilarPost
from telemetry.schemas import RunMetadata

SeoDiscoverabilityMode = Literal["corpus", "gemini_only"]


@dataclass
class EvaluationDeps:
    draft_content: str
    similar_posts: list[SimilarPost] = field(default_factory=list)
    # Personalization (dynamic style-profile prompting): a subscriber's
    # derived voice profile (agents/orchestrator.py fetches this via
    # storage/vector_store.get_user_voice_profile() when a user_id is
    # supplied and enough of their own posts exist). None when there's no
    # user_id or not enough data (cold start) — agents fall back to their
    # generic, non-personalized system prompt in that case.
    voice_profile: Optional[dict] = None
    # Tier 1 discoverability (T6 Point 2): pre-computed corpus evidence for
    # the SEO worker. None when seo_mode is gemini_only.
    discoverability_context: Optional[dict[str, Any]] = None
    seo_mode: SeoDiscoverabilityMode = "corpus"
    # T6 Point 1: deterministic neighbor-weighted prediction (processors/benchmark.py)
    # and optional draft-author follower count from the profiles cache.
    neighbor_prediction: Optional[dict[str, Any]] = None
    draft_follower_count: Optional[int] = None
    # Phase D feedback injection: compact validated lessons for the predictor prompt.
    feedback_context: Optional[str] = None


class PostEvaluationState(BaseModel):
    draft_content: str
    similar_posts: list[SimilarPost] = Field(default_factory=list)
    voice_profile: Optional[dict] = None
    predictor_result: Optional[dict] = None
    diagnostics: dict[str, dict] = Field(default_factory=dict)
    variants: list[dict] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    run_metadata: Optional[RunMetadata] = None
    # Phase H: query embedding from retrieval (list form for JSON/Pydantic).
    query_embedding: Optional[list[float]] = None
    embedding_model_version: Optional[str] = None


def build_voice_profile_section(voice_profile: Optional[dict]) -> str:
    """Render a subscriber's derived voice profile (personalization —
    dynamic style-profile prompting, see
    storage/vector_store.get_user_voice_profile()) as an extra prompt
    section shared by the Predictor (T3.2) and Diagnostic (T3.3) agents.

    Returns an empty string when there isn't one (no user_id supplied to
    run_evaluation_cycle, or that subscriber doesn't have enough of their
    own posts yet — cold start) so non-personalized calls get the exact
    same prompt as before this feature existed.
    """
    if not voice_profile:
        return ""
    return f"""
This subscriber's own writing style (derived from their {voice_profile.get('sample_size')} best-performing posts):
- Typical hook type: {voice_profile.get('dominant_hook_type') or 'unknown'}
- Typical tone: {voice_profile.get('dominant_tone') or 'unknown'}
- Typical writing style: {voice_profile.get('dominant_writing_style') or 'unknown'}
- Average length: {voice_profile.get('avg_word_count') or 'unknown'} words
- Average hashtag count: {voice_profile.get('avg_hashtag_count') or 'unknown'}
- Uses an explicit CTA in {voice_profile.get('cta_usage_ratio') or 'unknown'} of posts (0-1 ratio)
Factor this subscriber's established voice in — content close to their own proven style is more
likely to land, and improvement suggestions should nudge toward that voice, not away from it.
"""
