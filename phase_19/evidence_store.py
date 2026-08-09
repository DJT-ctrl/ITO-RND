"""Postgres persistence for Phase 19 subscriber evidence briefs, plans, and jobs."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

import psycopg

from phase_19.models import BaselinePlanProposal, SubscriberEvidenceBrief


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _iso(value: Any) -> Optional[str]:
    if not isinstance(value, datetime):
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _brief_record(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        brief_id,
        subscriber_id,
        public_profile_url,
        profile_authorized,
        role_description,
        primary_niche,
        sub_niche,
        target_audience,
        objectives,
        locale,
        seed_accounts,
        status,
        created_at,
        updated_at,
    ) = row
    return {
        "id": brief_id,
        "subscriber_id": subscriber_id,
        "public_profile_url": public_profile_url,
        "profile_authorized": bool(profile_authorized),
        "role_description": role_description,
        "primary_niche": primary_niche,
        "sub_niche": sub_niche,
        "target_audience": target_audience,
        "objectives": list(objectives or ()),
        "locale": locale,
        "seed_accounts": list(seed_accounts or ()),
        "status": status,
        "created_at": _iso(created_at),
        "updated_at": _iso(updated_at),
    }


def _plan_record(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        plan_id,
        brief_id,
        provider,
        baseline_budget_usd,
        daily_candidate_limit,
        source_priorities,
        proposed_queries,
        rationale,
        status,
        created_at,
        approved_at,
    ) = row
    return {
        "id": plan_id,
        "brief_id": brief_id,
        "provider": provider,
        "baseline_budget_usd": float(baseline_budget_usd),
        "daily_candidate_limit": int(daily_candidate_limit),
        "source_priorities": list(source_priorities or ()),
        "proposed_queries": list(proposed_queries or ()),
        "rationale": rationale,
        "status": status,
        "created_at": _iso(created_at),
        "approved_at": _iso(approved_at),
    }


_BRIEF_COLUMNS = """
    id, subscriber_id, public_profile_url, profile_authorized, role_description,
    primary_niche, sub_niche, target_audience, objectives, locale, seed_accounts,
    status, created_at, updated_at
"""
_PLAN_COLUMNS = """
    id, brief_id, provider, baseline_budget_usd, daily_candidate_limit,
    source_priorities, proposed_queries, rationale, status, created_at, approved_at
"""
_JOB_COLUMNS = """
    id, subscriber_id, brief_id, plan_id, job_kind, gap_reason, status,
    estimated_cost_usd, actual_cost_usd, candidate_count, accepted_count,
    rejected_count, recommended_seeds, error_detail, created_at, started_at, finished_at
"""
_RECEIPT_COLUMNS = """
    id, subscriber_id, collection_job_id, collected_count, rejected_count,
    actual_cost_usd, coverage_gaps, next_refresh_at, summary, created_at
"""


def _job_record(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        job_id,
        subscriber_id,
        brief_id,
        plan_id,
        job_kind,
        gap_reason,
        status,
        estimated_cost_usd,
        actual_cost_usd,
        candidate_count,
        accepted_count,
        rejected_count,
        recommended_seeds,
        error_detail,
        created_at,
        started_at,
        finished_at,
    ) = row
    return {
        "id": job_id,
        "subscriber_id": subscriber_id,
        "brief_id": brief_id,
        "plan_id": plan_id,
        "job_kind": job_kind,
        "gap_reason": gap_reason,
        "status": status,
        "estimated_cost_usd": float(estimated_cost_usd or 0),
        "actual_cost_usd": float(actual_cost_usd or 0),
        "candidate_count": int(candidate_count or 0),
        "accepted_count": int(accepted_count or 0),
        "rejected_count": int(rejected_count or 0),
        "recommended_seeds": list(recommended_seeds or ()),
        "error_detail": error_detail,
        "created_at": _iso(created_at),
        "started_at": _iso(started_at),
        "finished_at": _iso(finished_at),
    }


def _receipt_record(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        receipt_id,
        subscriber_id,
        collection_job_id,
        collected_count,
        rejected_count,
        actual_cost_usd,
        coverage_gaps,
        next_refresh_at,
        summary,
        created_at,
    ) = row
    return {
        "id": receipt_id,
        "subscriber_id": subscriber_id,
        "collection_job_id": collection_job_id,
        "collected_count": int(collected_count or 0),
        "rejected_count": int(rejected_count or 0),
        "actual_cost_usd": float(actual_cost_usd or 0),
        "coverage_gaps": list(coverage_gaps or ()),
        "next_refresh_at": _iso(next_refresh_at),
        "summary": summary,
        "created_at": _iso(created_at),
    }


def save_brief_and_plan(
    conn: psycopg.Connection,
    brief: SubscriberEvidenceBrief,
    plan: BaselinePlanProposal,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Upsert a subscriber brief and insert a new proposed baseline plan."""
    now = _utc_now()
    brief_id = str(uuid4())
    plan_id = str(uuid4())
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO subscriber_evidence_briefs ({_BRIEF_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s)
            ON CONFLICT (subscriber_id) DO UPDATE SET
                public_profile_url = EXCLUDED.public_profile_url,
                profile_authorized = EXCLUDED.profile_authorized,
                role_description = EXCLUDED.role_description,
                primary_niche = EXCLUDED.primary_niche,
                sub_niche = EXCLUDED.sub_niche,
                target_audience = EXCLUDED.target_audience,
                objectives = EXCLUDED.objectives,
                locale = EXCLUDED.locale,
                seed_accounts = EXCLUDED.seed_accounts,
                status = 'draft',
                updated_at = EXCLUDED.updated_at
            RETURNING {_BRIEF_COLUMNS}
            """,
            (
                brief_id,
                brief.subscriber_id,
                brief.public_profile_url,
                brief.profile_authorized,
                brief.role_description,
                brief.primary_niche,
                brief.sub_niche,
                brief.target_audience,
                list(brief.objectives),
                brief.locale,
                list(brief.seed_accounts),
                now,
                now,
            ),
        )
        saved_brief = _brief_record(cur.fetchone())
        cur.execute(
            "UPDATE subscriber_baseline_plans SET status = 'superseded' WHERE brief_id = %s",
            (saved_brief["id"],),
        )
        cur.execute(
            f"""
            INSERT INTO subscriber_baseline_plans ({_PLAN_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'proposed', %s, NULL)
            RETURNING {_PLAN_COLUMNS}
            """,
            (
                plan_id,
                saved_brief["id"],
                plan.provider,
                plan.baseline_budget_usd,
                plan.daily_candidate_limit,
                list(plan.source_priorities),
                list(plan.proposed_queries),
                plan.rationale,
                now,
            ),
        )
        saved_plan = _plan_record(cur.fetchone())
    conn.commit()
    return saved_brief, saved_plan


def get_brief_with_plan(
    conn: psycopg.Connection,
    subscriber_id: str,
) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
    """Load a brief with its newest plan (any status)."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_BRIEF_COLUMNS} FROM subscriber_evidence_briefs WHERE subscriber_id = %s",
            (subscriber_id,),
        )
        brief_row = cur.fetchone()
        if brief_row is None:
            return None
        brief = _brief_record(brief_row)
        cur.execute(
            f"""
            SELECT {_PLAN_COLUMNS}
            FROM subscriber_baseline_plans
            WHERE brief_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (brief["id"],),
        )
        plan_row = cur.fetchone()
    return brief, _plan_record(plan_row) if plan_row is not None else None


def approve_baseline_plan(
    conn: psycopg.Connection,
    subscriber_id: str,
) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
    """Approve a proposed plan; collection is started later by the worker."""
    current = get_brief_with_plan(conn, subscriber_id)
    if current is None:
        return None
    brief, plan = current
    if plan is None or plan["status"] != "proposed":
        return current

    now = _utc_now()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE subscriber_evidence_briefs SET status = 'approved', updated_at = %s WHERE id = %s",
            (now, brief["id"]),
        )
        cur.execute(
            "UPDATE subscriber_baseline_plans SET status = 'approved', approved_at = %s WHERE id = %s",
            (now, plan["id"]),
        )
    conn.commit()
    return get_brief_with_plan(conn, subscriber_id)


def set_brief_status(
    conn: psycopg.Connection,
    subscriber_id: str,
    status: str,
) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
    """Pause or resume an approved brief. Resume restores status to approved."""
    if status not in {"paused", "approved"}:
        raise ValueError("Brief status must be 'paused' or 'approved'.")
    current = get_brief_with_plan(conn, subscriber_id)
    if current is None:
        return None
    brief, plan = current
    if status == "approved" and (plan is None or plan["status"] != "approved"):
        raise ValueError("Cannot resume a brief without an approved plan.")
    now = _utc_now()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE subscriber_evidence_briefs SET status = %s, updated_at = %s WHERE id = %s",
            (status, now, brief["id"]),
        )
    conn.commit()
    return get_brief_with_plan(conn, subscriber_id)


def list_approved_briefs(
    conn: psycopg.Connection,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return approved, non-paused briefs with their current approved plan."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_BRIEF_COLUMNS}
            FROM subscriber_evidence_briefs
            WHERE status = 'approved'
            ORDER BY updated_at ASC
            """
        )
        briefs = [_brief_record(row) for row in cur.fetchall()]
    results: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for brief in briefs:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_PLAN_COLUMNS}
                FROM subscriber_baseline_plans
                WHERE brief_id = %s AND status = 'approved'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (brief["id"],),
            )
            plan_row = cur.fetchone()
        if plan_row is None:
            continue
        results.append((brief, _plan_record(plan_row)))
    return results


def baseline_completed(conn: psycopg.Connection, plan_id: str) -> bool:
    """True when a completed baseline job exists for the plan."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM subscriber_collection_jobs
            WHERE plan_id = %s AND job_kind = 'baseline' AND status = 'completed'
            LIMIT 1
            """,
            (plan_id,),
        )
        return cur.fetchone() is not None


def create_collection_job(
    conn: psycopg.Connection,
    *,
    subscriber_id: str,
    brief_id: str,
    plan_id: str,
    job_kind: str,
    gap_reason: str = "",
    estimated_cost_usd: float = 0.0,
    recommended_seeds: list[str] | None = None,
) -> dict[str, Any]:
    job_id = str(uuid4())
    now = _utc_now()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO subscriber_collection_jobs ({_JOB_COLUMNS})
            VALUES (
                %s, %s, %s, %s, %s, %s, 'planned', %s, 0, 0, 0, 0, %s, NULL, %s, NULL, NULL
            )
            RETURNING {_JOB_COLUMNS}
            """,
            (
                job_id,
                subscriber_id,
                brief_id,
                plan_id,
                job_kind,
                gap_reason,
                estimated_cost_usd,
                list(recommended_seeds or ()),
                now,
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return _job_record(row)


def mark_job_running(conn: psycopg.Connection, job_id: str) -> None:
    now = _utc_now()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE subscriber_collection_jobs
            SET status = 'running', started_at = %s
            WHERE id = %s
            """,
            (now, job_id),
        )
    conn.commit()


def finish_collection_job(
    conn: psycopg.Connection,
    job_id: str,
    *,
    status: str,
    actual_cost_usd: float = 0.0,
    candidate_count: int = 0,
    accepted_count: int = 0,
    rejected_count: int = 0,
    error_detail: str | None = None,
    recommended_seeds: list[str] | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE subscriber_collection_jobs SET
                status = %s,
                actual_cost_usd = %s,
                candidate_count = %s,
                accepted_count = %s,
                rejected_count = %s,
                error_detail = %s,
                recommended_seeds = COALESCE(%s, recommended_seeds),
                finished_at = %s
            WHERE id = %s
            RETURNING {_JOB_COLUMNS}
            """,
            (
                status,
                actual_cost_usd,
                candidate_count,
                accepted_count,
                rejected_count,
                error_detail,
                list(recommended_seeds) if recommended_seeds is not None else None,
                now,
                job_id,
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return _job_record(row)


def save_receipt(
    conn: psycopg.Connection,
    *,
    subscriber_id: str,
    collection_job_id: str,
    collected_count: int,
    rejected_count: int,
    actual_cost_usd: float,
    coverage_gaps: list[str],
    summary: str,
    next_refresh_hours: float = 24.0,
) -> dict[str, Any]:
    receipt_id = str(uuid4())
    now = _utc_now()
    next_refresh = now + timedelta(hours=next_refresh_hours)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO subscriber_evidence_receipts ({_RECEIPT_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_RECEIPT_COLUMNS}
            """,
            (
                receipt_id,
                subscriber_id,
                collection_job_id,
                collected_count,
                rejected_count,
                actual_cost_usd,
                list(coverage_gaps),
                next_refresh,
                summary,
                now,
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return _receipt_record(row)


def list_receipts(
    conn: psycopg.Connection,
    subscriber_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_RECEIPT_COLUMNS}
            FROM subscriber_evidence_receipts
            WHERE subscriber_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (subscriber_id, limit),
        )
        return [_receipt_record(row) for row in cur.fetchall()]


def list_jobs(
    conn: psycopg.Connection,
    subscriber_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_JOB_COLUMNS}
            FROM subscriber_collection_jobs
            WHERE subscriber_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (subscriber_id, limit),
        )
        return [_job_record(row) for row in cur.fetchall()]


def save_evidence_item(
    conn: psycopg.Connection,
    *,
    post_id: str | None,
    source_url: str | None,
    source_type: str,
    content_preview: str,
    primary_niche: str,
    sub_niche: str,
    target_audience: str,
    author_key: str,
    quality_score: float | None,
    decision: str,
    rejection_reason: str | None,
    provider_run_id: str | None,
    collection_job_id: str,
    subscriber_id: str,
    scope: str,
) -> str:
    evidence_id = str(uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO subscriber_evidence_items (
                id, post_id, source_url, source_type, content_preview,
                primary_niche, sub_niche, target_audience, author_key,
                quality_score, decision, rejection_reason, provider_run_id,
                collection_job_id, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                evidence_id,
                post_id,
                source_url,
                source_type,
                content_preview[:500],
                primary_niche,
                sub_niche,
                target_audience,
                author_key,
                quality_score,
                decision,
                rejection_reason,
                provider_run_id,
                collection_job_id,
                _utc_now(),
            ),
        )
        if decision == "accepted":
            cur.execute(
                """
                INSERT INTO subscriber_evidence_membership (
                    subscriber_id, evidence_id, scope, created_at
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (subscriber_id, evidence_id, scope, _utc_now()),
            )
    conn.commit()
    return evidence_id


def known_post_ids_for_subscriber(
    conn: psycopg.Connection,
    subscriber_id: str,
) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT i.post_id
            FROM subscriber_evidence_items i
            JOIN subscriber_evidence_membership m ON m.evidence_id = i.id
            WHERE m.subscriber_id = %s AND i.post_id IS NOT NULL
            """,
            (subscriber_id,),
        )
        return {str(row[0]) for row in cur.fetchall() if row[0]}


def coverage_stats(
    conn: psycopg.Connection,
    subscriber_id: str,
) -> dict[str, Any]:
    """Simple coverage metrics for gap detection."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE i.decision = 'accepted'),
                MAX(i.created_at),
                COUNT(DISTINCT NULLIF(i.author_key, ''))
            FROM subscriber_evidence_items i
            JOIN subscriber_evidence_membership m ON m.evidence_id = i.id
            WHERE m.subscriber_id = %s
            """,
            (subscriber_id,),
        )
        accepted, newest, authors = cur.fetchone()
        cur.execute(
            """
            SELECT i.author_key, COUNT(*) AS n
            FROM subscriber_evidence_items i
            JOIN subscriber_evidence_membership m ON m.evidence_id = i.id
            WHERE m.subscriber_id = %s AND i.decision = 'accepted'
              AND i.author_key <> ''
            GROUP BY i.author_key
            ORDER BY n DESC
            LIMIT 1
            """,
            (subscriber_id,),
        )
        top = cur.fetchone()
    accepted_n = int(accepted or 0)
    top_share = 0.0
    if accepted_n and top:
        top_share = float(top[1]) / accepted_n
    return {
        "accepted_count": accepted_n,
        "newest_at": newest,
        "distinct_authors": int(authors or 0),
        "dominant_author_share": top_share,
    }


def budget_snapshot(
    conn: psycopg.Connection,
    *,
    subscriber_id: str,
    plan_id: str,
    day: date | None = None,
) -> dict[str, float | int]:
    day = day or _utc_today()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(baseline_spent_usd), 0), COALESCE(SUM(daily_candidates), 0)
            FROM subscriber_evidence_budget_ledger
            WHERE subscriber_id = %s AND plan_id = %s
            """,
            (subscriber_id, plan_id),
        )
        lifetime_spent, _ = cur.fetchone()
        cur.execute(
            """
            SELECT COALESCE(daily_candidates, 0), COALESCE(baseline_spent_usd, 0)
            FROM subscriber_evidence_budget_ledger
            WHERE subscriber_id = %s AND plan_id = %s AND day = %s
            """,
            (subscriber_id, plan_id, day),
        )
        row = cur.fetchone()
    day_candidates = int(row[0]) if row else 0
    day_spent = float(row[1]) if row else 0.0
    return {
        "lifetime_baseline_spent_usd": float(lifetime_spent or 0),
        "day_candidates": day_candidates,
        "day_spent_usd": day_spent,
    }


def record_budget_usage(
    conn: psycopg.Connection,
    *,
    subscriber_id: str,
    plan_id: str,
    cost_usd: float,
    candidates: int,
    day: date | None = None,
) -> None:
    day = day or _utc_today()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO subscriber_evidence_budget_ledger (
                subscriber_id, plan_id, day, baseline_spent_usd, daily_candidates, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (subscriber_id, plan_id, day) DO UPDATE SET
                baseline_spent_usd = subscriber_evidence_budget_ledger.baseline_spent_usd
                    + EXCLUDED.baseline_spent_usd,
                daily_candidates = subscriber_evidence_budget_ledger.daily_candidates
                    + EXCLUDED.daily_candidates,
                updated_at = EXCLUDED.updated_at
            """,
            (subscriber_id, plan_id, day, float(cost_usd), int(candidates), _utc_now()),
        )
    conn.commit()


def member_post_ids(
    conn: psycopg.Connection,
    subscriber_id: str,
    *,
    scope: str | None = None,
    limit: int = 500,
) -> list[str]:
    """Return accepted evidence post_ids visible to a subscriber."""
    params: list[Any] = [subscriber_id]
    scope_clause = ""
    if scope is not None:
        scope_clause = "AND m.scope = %s"
        params.append(scope)
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT i.post_id
            FROM subscriber_evidence_items i
            JOIN subscriber_evidence_membership m ON m.evidence_id = i.id
            WHERE m.subscriber_id = %s
              AND i.decision = 'accepted'
              AND i.post_id IS NOT NULL
              {scope_clause}
            ORDER BY i.created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [str(row[0]) for row in cur.fetchall() if row[0]]
