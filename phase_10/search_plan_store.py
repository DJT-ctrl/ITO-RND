"""Postgres CRUD for the singleton agentic search plan (T10.2)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from phase_10.json_store import read_json_object
from phase_10.models import SearchPlan, SeedConfig
from phase_10.paths import SEEDS_PATH

logger = logging.getLogger(__name__)

_SINGLETON_ID = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _clean_lines(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        lines = raw.splitlines()
    else:
        lines = list(raw)
    cleaned: list[str] = []
    seen: set[str] = set()
    for line in lines:
        value = line.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def _weights_from_db(raw: Any) -> dict[str, float]:
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _row_to_plan(row: tuple[Any, ...]) -> SearchPlan:
    seed_terms, seed_accounts, weights_raw, updated_at = row
    updated = None
    if isinstance(updated_at, datetime):
        updated = updated_at.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return SearchPlan(
        terms=tuple(seed_terms or ()),
        seed_accounts=tuple(seed_accounts or ()),
        weights_by_niche=_weights_from_db(weights_raw),
        updated_at=updated,
        stub=False,
    )


def ensure_plan_row(conn: psycopg.Connection) -> None:
    """Insert the singleton row if missing; migrate JSON seeds once when empty."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT seed_terms, seed_accounts FROM agentic_search_plan WHERE id = %s",
            (_SINGLETON_ID,),
        )
        existing = cur.fetchone()
        if existing is None:
            seeds = _load_json_seeds()
            cur.execute(
                """
                INSERT INTO agentic_search_plan (
                    id, seed_terms, seed_accounts, weights_by_niche, updated_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    _SINGLETON_ID,
                    list(seeds.seed_terms),
                    list(seeds.seed_accounts),
                    Jsonb({}),
                    _utc_now(),
                ),
            )
            conn.commit()
            logger.info(
                "Created agentic_search_plan singleton (migrated %s term(s) from JSON)",
                len(seeds.seed_terms),
            )
            return

        terms, accounts = existing
        if (not terms) and (not accounts):
            seeds = _load_json_seeds()
            if seeds.seed_terms or seeds.seed_accounts:
                cur.execute(
                    """
                    UPDATE agentic_search_plan
                    SET seed_terms = %s,
                        seed_accounts = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (list(seeds.seed_terms), list(seeds.seed_accounts), _utc_now(), _SINGLETON_ID),
                )
                conn.commit()
                logger.info("Migrated JSON seeds into empty agentic_search_plan row")


def _load_json_seeds() -> SeedConfig:
    data = read_json_object(SEEDS_PATH)
    updated = data.get("updated_at")
    return SeedConfig(
        seed_terms=tuple(_clean_lines(data.get("seed_terms", []))),
        seed_accounts=tuple(_clean_lines(data.get("seed_accounts", []))),
        updated_at=updated if isinstance(updated, str) else None,
    )


def load_plan(conn: psycopg.Connection) -> SearchPlan:
    ensure_plan_row(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT seed_terms, seed_accounts, weights_by_niche, updated_at
            FROM agentic_search_plan
            WHERE id = %s
            """,
            (_SINGLETON_ID,),
        )
        row = cur.fetchone()
    if row is None:
        return SearchPlan(stub=False)
    return _row_to_plan(row)


def save_seeds(
    conn: psycopg.Connection,
    *,
    seed_terms: str | list[str] | tuple[str, ...],
    seed_accounts: str | list[str] | tuple[str, ...],
) -> SeedConfig:
    ensure_plan_row(conn)
    terms = _clean_lines(seed_terms)
    accounts = _clean_lines(seed_accounts)
    now = _utc_now()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agentic_search_plan
            SET seed_terms = %s,
                seed_accounts = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (terms, accounts, now, _SINGLETON_ID),
        )
    conn.commit()
    return SeedConfig(
        seed_terms=tuple(terms),
        seed_accounts=tuple(accounts),
        updated_at=now.isoformat(),
    )


def save_weights(
    conn: psycopg.Connection,
    weights_by_niche: dict[str, float],
) -> SearchPlan:
    ensure_plan_row(conn)
    now = _utc_now()
    cleaned = {str(k): float(v) for k, v in weights_by_niche.items() if float(v) > 0}
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agentic_search_plan
            SET weights_by_niche = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (Jsonb(cleaned), now, _SINGLETON_ID),
        )
    conn.commit()
    return load_plan(conn)
