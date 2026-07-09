"""Compose Tier 1 + optional Tier 2 discoverability context for the SEO agent."""

from __future__ import annotations

from typing import Any, Optional

from agents.discoverability import run_deterministic_checks, summarize_neighbors_for_seo
from api.schemas import SimilarPost
from config.settings import Settings
from processors.corpus_benchmarks import (
    corpus_norms_from_snapshot,
    format_snapshot_for_prompt,
    get_or_refresh_benchmarks,
)
from processors.trend_signals.google_trends import fetch_trend_signals, format_trends_for_prompt
from processors.trend_signals.keywords import extract_trend_keywords


def gather_discoverability_context(
    draft: str,
    similar_posts: list,
    settings: Settings,
    *,
    use_google_trends: bool,
) -> tuple[dict[str, Any], list[str]]:
    """Pre-compute corpus-grounded evidence and optional Google Trends signals."""
    snapshot, warnings = get_or_refresh_benchmarks(settings)
    norms = corpus_norms_from_snapshot(snapshot)
    deterministic = run_deterministic_checks(draft, norms)

    posts = [post if isinstance(post, SimilarPost) else SimilarPost(**post) for post in similar_posts]
    neighbor_summary = summarize_neighbors_for_seo(posts)

    context_warnings = list(warnings)
    if snapshot is None:
        context_warnings.append(
            "No corpus benchmark available — using neighbor patterns and deterministic checks only."
        )

    context: dict[str, Any] = {
        "corpus_benchmark_text": format_snapshot_for_prompt(snapshot) if snapshot else None,
        "deterministic": deterministic,
        "neighbor_summary": neighbor_summary,
        "warnings": context_warnings,
    }

    if use_google_trends:
        corpus_topics = (snapshot or {}).get("top_topics")
        keywords = extract_trend_keywords(draft, corpus_top_topics=corpus_topics)
        trends, trend_warnings = fetch_trend_signals(keywords, settings, corpus_top_topics=corpus_topics)
        context_warnings.extend(trend_warnings)
        if trends is not None:
            context["trends"] = trends
            context["trends_text"] = format_trends_for_prompt(trends)
        elif keywords:
            context_warnings.append(
                "Google Trends enabled but no trend signals were retrieved for draft keywords."
            )

    context["warnings"] = context_warnings
    return context, context_warnings


def resolve_use_google_trends(
    seo_mode: str,
    settings: Settings,
    use_google_trends: Optional[bool] = None,
) -> bool:
    """Trends are always off in gemini_only mode; otherwise honor request or settings."""
    if seo_mode == "gemini_only":
        return False
    if use_google_trends is not None:
        return use_google_trends
    return settings.google_trends_enabled
