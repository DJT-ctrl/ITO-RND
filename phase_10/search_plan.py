"""Search plan service (T10.2) — seeds, derived niche weights, job helpers.

Persistence is Postgres (``agentic_search_plan``). JSON seeds are migrated
once when the singleton row is empty.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from config.settings import Settings, load_settings
from phase_10.models import SearchPlan, SeedConfig
from phase_10 import search_plan_store
from phase_10.user_niches import refresh_user_niches
from storage.vector_store import create_schema, get_connection


class SearchPlanError(RuntimeError):
    """Raised when the search plan cannot be read or written."""


@contextmanager
def _plan_connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    settings = settings or load_settings()
    if not settings.database_url:
        raise SearchPlanError("DATABASE_URL is not set.")
    conn = get_connection(settings)
    try:
        create_schema(conn)
        yield conn
    finally:
        conn.close()


def load_seeds(settings: Settings | None = None) -> SeedConfig:
    with _plan_connection(settings) as conn:
        plan = search_plan_store.load_plan(conn)
    return SeedConfig(
        seed_terms=plan.terms,
        seed_accounts=plan.seed_accounts,
        updated_at=plan.updated_at,
    )


def save_seeds(
    *,
    seed_terms: str | list[str] | tuple[str, ...],
    seed_accounts: str | list[str] | tuple[str, ...],
    settings: Settings | None = None,
) -> SeedConfig:
    with _plan_connection(settings) as conn:
        return search_plan_store.save_seeds(
            conn,
            seed_terms=seed_terms,
            seed_accounts=seed_accounts,
        )


def get_search_plan(settings: Settings | None = None) -> SearchPlan:
    with _plan_connection(settings) as conn:
        return search_plan_store.load_plan(conn)


def rebuild_search_plan(settings: Settings | None = None) -> SearchPlan:
    """Refresh ``user_niches`` from posts and write global weights onto the plan."""
    with _plan_connection(settings) as conn:
        weights = refresh_user_niches(conn)
        return search_plan_store.save_weights(conn, weights)


def queries_for_general_refresh(settings: Settings | None = None) -> list[str]:
    return list(get_search_plan(settings).terms)


def active_niches(
    *,
    min_weight: float = 0.0,
    settings: Settings | None = None,
) -> list[str]:
    plan = get_search_plan(settings)
    return sorted(
        niche
        for niche, weight in plan.weights_by_niche.items()
        if weight > min_weight
    )


def seed_profile_urls(settings: Settings | None = None) -> list[str]:
    return list(get_search_plan(settings).seed_accounts)
