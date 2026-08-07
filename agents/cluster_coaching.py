"""Evidence-grounded, cluster-aware coaching for interactive evaluations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents.prompt_safety import PROMPT_DATA_PREAMBLE, wrap_untrusted_text
from agents.schemas import EvaluationDeps, PostEvaluationState
from agents.structured_output import agent_structured_output
from api.schemas import (
	ClusterCoachingResult,
	CoachingAction,
	CoachingEvidence,
	DetailedCoachingAction,
	SimilarPost,
)
from config.settings import Settings, pydantic_ai_gemini_model
from feedback.retrieve import fetch_cluster_feedback_with_fallback
from feedback.routing import assign_cluster_id, cluster_label
from feedback.store import fetch_cluster_centroids
from feedback.summarize import fetch_cluster_rollup
from storage.vector_store import create_schema, get_connection
from telemetry.collector import RunMetadataCollector
from telemetry.instrument import run_agent_step

COACHING_MODEL = "gemini-2.5-flash"
_MAX_FEEDBACK_RECORDS = 3
_MAX_NEIGHBORS = 3


@dataclass(frozen=True)
class CoachingEvidenceBundle:
	"""Trusted, bounded evidence available to the coaching model."""

	evidence: CoachingEvidence
	feedback_lines: list[str]
	neighbor_lines: list[str]
	diagnostic_lines: list[str]
	allowed_refs: frozenset[str]


class CoachingDraft(BaseModel):
	"""LLM-owned text fields; evidence metadata stays deterministic."""

	summary: str = Field(..., min_length=1, max_length=800)
	primary_action: DetailedCoachingAction
	supporting_actions: list[CoachingAction] = Field(default_factory=list, max_length=2)


def _compact(text: str, limit: int) -> str:
	collapsed = " ".join((text or "").split())
	if len(collapsed) <= limit:
		return collapsed
	return collapsed[: limit - 3].rstrip() + "..."


def _diagnostic_lines(state: PostEvaluationState) -> list[str]:
	lines: list[str] = []
	for name, output in state.diagnostics.items():
		flaws = "; ".join(output.get("flaws", [])[:2]) or "none recorded"
		improvements = "; ".join(output.get("improvements", [])[:2]) or "none recorded"
		lines.append(
			f"{name}: score {output.get('score', 'unavailable')}; "
			f"flaws: {flaws}; improvements: {improvements}"
		)
	return lines or ["No diagnostic worker output was available."]


def _neighbor_lines(posts: list[SimilarPost]) -> tuple[list[str], set[str]]:
	lines: list[str] = []
	refs: set[str] = set()
	for post in posts[:_MAX_NEIGHBORS]:
		ref = f"neighbor:{post.post_id}"
		refs.add(ref)
		lines.append(
			f"{ref}; percentile={post.engagement_percentile:.1f}; "
			f"distance={post.cosine_distance:.3f}; content="
			f"{wrap_untrusted_text(_compact(post.content, 280), tag='neighbor_post')}"
		)
	return lines, refs


def load_coaching_evidence(
	state: PostEvaluationState,
	settings: Settings,
	*,
	draft_follower_count: Optional[int] = None,
) -> CoachingEvidenceBundle:
	"""Resolve approved, relevant validation evidence for one draft.

	This function intentionally returns a diagnostic/neighbor fallback instead
	of treating sparse validated clusters as an error. The result identifies
	that lower-confidence source explicitly so the coach cannot imply proof it
	does not have.
	"""
	conn = get_connection(settings)
	try:
		create_schema(conn)
		centroids = fetch_cluster_centroids(conn)
		requested_cluster_id = assign_cluster_id(
			state.draft_content,
			draft_follower_count,
			niche=state.retrieval_prefer_niche,
			embedding=state.query_embedding,
			centroids=centroids or None,
		)
		records, resolved_cluster_id, rollup, _mean_delta, sample_count = (
			fetch_cluster_feedback_with_fallback(
				conn,
				requested_cluster_id,
				limit=_MAX_FEEDBACK_RECORDS,
				approved_only=True,
				query_embedding=state.query_embedding,
				cluster_n_min=settings.validation_cluster_n_min,
				age_aware_enabled=settings.validation_age_aware_enabled,
				multi_horizon_learning=settings.validation_multi_horizon_learning,
			)
		)
		if not rollup:
			rollup, _mean_delta, sample_count = fetch_cluster_rollup(
				conn, resolved_cluster_id
			)
	finally:
		conn.close()

	feedback_lines: list[str] = []
	feedback_refs: set[str] = set()
	for record in records:
		ref = f"feedback:{record.prediction_id}"
		feedback_refs.add(ref)
		payload = record.feedback_json
		lessons = "; ".join(payload.lessons_for_similar_posts[:2]) or "none recorded"
		missed = "; ".join(payload.what_missed[:2]) or "none recorded"
		feedback_lines.append(
			f"{ref}; direction={payload.delta_summary.direction}; "
			f"delta={payload.delta_summary.prediction_delta:+.1f}; "
			f"miss={wrap_untrusted_text(_compact(missed, 300), tag='feedback_miss')}; "
			f"lesson={wrap_untrusted_text(_compact(lessons, 300), tag='feedback_lesson')}"
		)

	neighbor_lines, neighbor_refs = _neighbor_lines(state.similar_posts)
	used_fallback = bool(records) and resolved_cluster_id != requested_cluster_id
	if records:
		confidence = "shape_fallback" if used_fallback else "cluster_validated"
		summary = (
			rollup
			or f"{len(records)} approved validated lesson(s) were retrieved from "
			f"{cluster_label(resolved_cluster_id)}."
		)
	else:
		confidence = "diagnostic_neighbor"
		summary = (
			"No approved validated lessons were available for this cluster, so coaching "
			"uses the completed diagnostics and closest historical neighbors only."
		)

	return CoachingEvidenceBundle(
		evidence=CoachingEvidence(
			cluster_id=resolved_cluster_id,
			cluster_label=cluster_label(resolved_cluster_id),
			sample_count=sample_count,
			validated_feedback_count=len(records),
			confidence=confidence,
			summary=summary,
		),
		feedback_lines=feedback_lines,
		neighbor_lines=neighbor_lines,
		diagnostic_lines=_diagnostic_lines(state),
		allowed_refs=frozenset(feedback_refs | neighbor_refs),
	)


def build_cluster_coaching_prompt(
	deps: EvaluationDeps,
	bundle: CoachingEvidenceBundle,
) -> str:
	"""Build the Flash prompt from bounded, validated evidence."""
	validated_feedback = "\n".join(bundle.feedback_lines) or "None available."
	neighbors = "\n".join(bundle.neighbor_lines) or "None available."
	diagnostics = "\n".join(bundle.diagnostic_lines)
	allowed_refs = ", ".join(sorted(bundle.allowed_refs)) or "none"
	return f"""
{PROMPT_DATA_PREAMBLE}

You are the Cluster-Aware Coach in a LinkedIn post evaluation pipeline.
Give draft-specific editorial coaching, not a list of analytics. Historical
patterns are observational evidence, never proof or a performance guarantee.

Return exactly one high-priority primary action and no more than two distinct
supporting actions. The primary action must be detailed and executable:
- quote a literal `draft_anchor` copied from the draft;
- diagnose why that exact wording or structure weakens the post;
- give a specific edit instruction and an example replacement or insertion;
- explain the expected reader-facing effect without promising engagement.

Every evidence_refs item must be one of these exact references: {allowed_refs}.
Do not invent metrics, source IDs, quote fragments, or claims about evidence.
When the confidence is `diagnostic_neighbor`, say the advice is lower-confidence
and avoid claiming a cluster-validated pattern.

Evidence scope:
- Confidence: {bundle.evidence.confidence}
- Cluster: {bundle.evidence.cluster_id or 'unavailable'}
- Cluster summary: {bundle.evidence.summary}

Draft:
{wrap_untrusted_text(deps.draft_content, tag='draft')}

Completed diagnostics:
{diagnostics}

Approved validated lessons:
{validated_feedback}

Closest historical neighbors:
{neighbors}

Return only structured data matching the required schema.
""".strip()


def build_cluster_coaching_agent(model: Any = None) -> Agent[EvaluationDeps, CoachingDraft]:
	"""Create the coach with Gemini 2.5 Flash unless a test model is supplied."""
	resolved = pydantic_ai_gemini_model(COACHING_MODEL) if model is None else model
	return Agent(
		resolved,
		deps_type=EvaluationDeps,
		output_type=agent_structured_output(CoachingDraft, resolved),
		retries=2,
	)


def _normalized(text: str) -> str:
	return " ".join((text or "").casefold().split())


def validate_coaching_output(
	output: CoachingDraft,
	*,
	draft_content: str,
	bundle: CoachingEvidenceBundle,
) -> ClusterCoachingResult:
	"""Reject advice that cannot be tied to the submitted draft and evidence."""
	anchor = _normalized(output.primary_action.draft_anchor)
	if not anchor or anchor not in _normalized(draft_content):
		raise ValueError("coaching primary draft_anchor does not appear in the draft")

	actions = [output.primary_action, *output.supporting_actions]
	for action in actions:
		unknown_refs = set(action.evidence_refs) - bundle.allowed_refs
		if unknown_refs:
			raise ValueError(
				"coaching action cites unavailable evidence: "
				+ ", ".join(sorted(unknown_refs))
			)

	return ClusterCoachingResult(
		status="ready",
		summary=output.summary,
		evidence=bundle.evidence,
		primary_action=output.primary_action,
		supporting_actions=output.supporting_actions,
	)


def build_cluster_coaching_engine(
	settings: Settings,
	*,
	model: Any = None,
	collector: Optional[RunMetadataCollector] = None,
) -> Callable[[PostEvaluationState], Awaitable[None]]:
	"""Build the optional, read-only coaching finalize hook."""
	agent = build_cluster_coaching_agent(model)

	async def finalize(state: PostEvaluationState) -> None:
		try:
			bundle = await asyncio.to_thread(
				load_coaching_evidence,
				state,
				settings,
				draft_follower_count=state.draft_follower_count,
			)
			if not bundle.allowed_refs:
				state.errors.append(
					"cluster_coaching: skipped, no validated feedback or historical neighbors available"
				)
				return
			deps = EvaluationDeps(
				draft_content=state.draft_content,
				similar_posts=state.similar_posts,
				cross_references=state.cross_references,
				voice_profile=state.voice_profile,
			)
			result = await run_agent_step(
				collector,
				step_id="agent.cluster_coaching",
				label="Cluster-aware coaching",
				stage="agent",
				agent=agent,
				prompt=build_cluster_coaching_prompt(deps, bundle),
				deps=deps,
				model=pydantic_ai_gemini_model(COACHING_MODEL),
				timeout_s=settings.agent_step_timeout_s,
			)
			output = result.output
			if not isinstance(output, CoachingDraft):
				output = CoachingDraft.model_validate(output)
			state.cluster_coaching = validate_coaching_output(
				output,
				draft_content=state.draft_content,
				bundle=bundle,
			)
		except Exception as exc:
			state.errors.append(f"cluster_coaching: {exc}")

	return finalize
