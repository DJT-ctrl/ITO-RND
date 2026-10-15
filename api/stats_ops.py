"""Read-only product stats for the frontend dashboard."""

from __future__ import annotations

from typing import Any, Optional

from config.settings import Settings, load_settings
from feedback.dashboard_queries import count_feedback_coverage, fetch_learning_status
from phase_10.budget import get_budget_snapshot
from storage.vector_store import create_schema, get_connection

from api.corpus_ops import get_corpus_stats


def get_feedback_stats(*, settings: Optional[Settings] = None) -> dict[str, Any]:
    settings = settings or load_settings()
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set.")
    conn = get_connection(settings)
    try:
        create_schema(conn)
        coverage = count_feedback_coverage(conn)
        learning = fetch_learning_status(conn)
    finally:
        conn.close()
    return {
        "coverage": coverage,
        "learning": learning.model_dump(mode="json"),
        "feedback_enabled": settings.validation_feedback_enabled,
        "injection_enabled": settings.validation_feedback_injection_enabled,
    }


def get_budget_stats(*, settings: Optional[Settings] = None) -> dict[str, Any]:
    settings = settings or load_settings()
    snap = get_budget_snapshot(settings)
    return {
        "apify_used_usd": snap.apify_used_usd,
        "apify_cap_usd": snap.apify_cap_usd,
        "gemini_used_usd": snap.gemini_used_usd,
        "gemini_cap_usd": snap.gemini_cap_usd,
        "apify_month_used_usd": snap.apify_month_used_usd,
        "apify_month_cap_usd": snap.apify_month_cap_usd,
        "gemini_month_used_usd": snap.gemini_month_used_usd,
        "gemini_month_cap_usd": snap.gemini_month_cap_usd,
        "note": snap.note,
    }


def get_all_stats(*, settings: Optional[Settings] = None) -> dict[str, Any]:
    settings = settings or load_settings()
    corpus = get_corpus_stats(settings=settings)
    try:
        feedback = get_feedback_stats(settings=settings)
    except ValueError as exc:
        feedback = {
            "coverage": {"validated": 0, "with_feedback": 0, "missing_feedback": 0},
            "learning": {},
            "feedback_enabled": settings.validation_feedback_enabled,
            "injection_enabled": settings.validation_feedback_injection_enabled,
            "error": str(exc),
        }
    budget = get_budget_stats(settings=settings)
    return {"corpus": corpus, "feedback": feedback, "budget": budget}
