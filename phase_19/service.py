"""Application service for Phase 19 subscriber evidence workflow."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from config.settings import Settings, load_settings
from phase_19 import evidence_store
from phase_19.models import SubscriberEvidenceBrief
from phase_19.planner import build_baseline_plan
from storage.vector_store import create_schema, get_connection


class SubscriberEvidenceError(RuntimeError):
    """Raised when a subscriber evidence brief cannot be loaded or saved."""


class SubscriberEvidenceNotFoundError(SubscriberEvidenceError):
    """Raised when a subscriber does not have an evidence brief."""


@contextmanager
def _evidence_connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    resolved_settings = settings or load_settings()
    if not resolved_settings.database_url:
        raise SubscriberEvidenceError("DATABASE_URL is not set.")
    conn = get_connection(resolved_settings)
    try:
        create_schema(conn)
        yield conn
    finally:
        conn.close()


def propose_baseline(
    brief: SubscriberEvidenceBrief,
    *,
    settings: Settings | None = None,
) -> tuple[dict, dict]:
    """Save a draft brief and its new subscriber-reviewable baseline plan."""
    plan = build_baseline_plan(brief)
    with _evidence_connection(settings) as conn:
        return evidence_store.save_brief_and_plan(conn, brief, plan)


def get_baseline(
    subscriber_id: str,
    *,
    settings: Settings | None = None,
) -> tuple[dict, dict]:
    """Return the current brief and active baseline plan for one subscriber."""
    with _evidence_connection(settings) as conn:
        result = evidence_store.get_brief_with_plan(conn, subscriber_id)
    if result is None:
        raise SubscriberEvidenceNotFoundError(f"No evidence brief exists for subscriber {subscriber_id!r}.")
    brief, plan = result
    if plan is None:
        raise SubscriberEvidenceError(f"Evidence brief for subscriber {subscriber_id!r} has no plan.")
    return brief, plan


def approve_baseline(
    subscriber_id: str,
    *,
    settings: Settings | None = None,
) -> tuple[dict, dict]:
    """Approve the current proposed plan. Enables the worker; does not scrape inline."""
    with _evidence_connection(settings) as conn:
        result = evidence_store.approve_baseline_plan(conn, subscriber_id)
    if result is None:
        raise SubscriberEvidenceNotFoundError(f"No evidence brief exists for subscriber {subscriber_id!r}.")
    brief, plan = result
    if plan is None:
        raise SubscriberEvidenceError(f"Evidence brief for subscriber {subscriber_id!r} has no plan.")
    return brief, plan


def pause_baseline(
    subscriber_id: str,
    *,
    settings: Settings | None = None,
) -> tuple[dict, dict]:
    """Pause collection for an approved brief."""
    with _evidence_connection(settings) as conn:
        result = evidence_store.set_brief_status(conn, subscriber_id, "paused")
    if result is None:
        raise SubscriberEvidenceNotFoundError(f"No evidence brief exists for subscriber {subscriber_id!r}.")
    return result


def resume_baseline(
    subscriber_id: str,
    *,
    settings: Settings | None = None,
) -> tuple[dict, dict]:
    """Resume a paused brief that still has an approved plan."""
    try:
        with _evidence_connection(settings) as conn:
            result = evidence_store.set_brief_status(conn, subscriber_id, "approved")
    except ValueError as exc:
        raise SubscriberEvidenceError(str(exc)) from exc
    if result is None:
        raise SubscriberEvidenceNotFoundError(f"No evidence brief exists for subscriber {subscriber_id!r}.")
    return result


def list_receipts(
    subscriber_id: str,
    *,
    settings: Settings | None = None,
    limit: int = 20,
) -> list[dict]:
    with _evidence_connection(settings) as conn:
        if evidence_store.get_brief_with_plan(conn, subscriber_id) is None:
            raise SubscriberEvidenceNotFoundError(
                f"No evidence brief exists for subscriber {subscriber_id!r}."
            )
        return evidence_store.list_receipts(conn, subscriber_id, limit=limit)


def list_jobs(
    subscriber_id: str,
    *,
    settings: Settings | None = None,
    limit: int = 20,
) -> list[dict]:
    with _evidence_connection(settings) as conn:
        if evidence_store.get_brief_with_plan(conn, subscriber_id) is None:
            raise SubscriberEvidenceNotFoundError(
                f"No evidence brief exists for subscriber {subscriber_id!r}."
            )
        return evidence_store.list_jobs(conn, subscriber_id, limit=limit)
