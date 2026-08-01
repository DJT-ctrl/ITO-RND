"""Gather ops signals for the T10.10 Pro workflow critic."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from config.settings import Settings, load_settings
from phase_10.budget import get_budget_snapshot
from phase_10.db import AgenticDbError, agentic_connection
from phase_10.job_flags import load_job_flags
from phase_10.models import BudgetSnapshot, ScrapeProof, SearchPlan
from phase_10 import scrape_proof_store, schedule_store
from phase_10.search_plan import SearchPlanError, get_search_plan

logger = logging.getLogger(__name__)

OPS_LOOKBACK_HOURS = 24
PROOF_ROLLUP_DAYS = 7
PROOF_LIST_LIMIT = 20
APIFY_RUN_LIMIT = 50
MAX_SNAPSHOT_CHARS = 80_000


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _within(dt: datetime | None, *, since: datetime) -> bool:
    return dt is not None and dt >= since


def _budget_section(snap: BudgetSnapshot) -> dict[str, Any]:
    return {
        "apify_used_usd": snap.apify_used_usd,
        "apify_cap_usd": snap.apify_cap_usd,
        "gemini_used_usd": snap.gemini_used_usd,
        "gemini_cap_usd": snap.gemini_cap_usd,
        "apify_month_used_usd": snap.apify_month_used_usd,
        "apify_month_cap_usd": snap.apify_month_cap_usd,
        "gemini_month_used_usd": snap.gemini_month_used_usd,
        "gemini_month_cap_usd": snap.gemini_month_cap_usd,
        "note": snap.note or None,
        "apify_daily_pct": (
            round(100.0 * snap.apify_used_usd / snap.apify_cap_usd, 1)
            if snap.apify_cap_usd > 0
            else None
        ),
        "gemini_daily_pct": (
            round(100.0 * snap.gemini_used_usd / snap.gemini_cap_usd, 1)
            if snap.gemini_cap_usd > 0
            else None
        ),
    }


def _classify_result(last_result: str | None) -> str:
    text = (last_result or "").strip().lower()
    if text.startswith("failed:"):
        return "failed"
    if text.startswith("skipped:"):
        return "skipped"
    if text.startswith("done:") or text.startswith("ok"):
        return "ok"
    if not text:
        return "unknown"
    return "other"


def _job_runs_section(
    rows: dict[str, dict[str, Any]],
    flags: dict[str, bool],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for job_id, row in sorted(rows.items()):
        last_result = row.get("last_result")
        last_run_at = row.get("last_run_at")
        next_run_at = row.get("next_run_at")
        out.append(
            {
                "job_id": job_id,
                "enabled": bool(flags.get(job_id, True)),
                "last_run_at": (
                    last_run_at.isoformat()
                    if isinstance(last_run_at, datetime)
                    else last_run_at
                ),
                "next_run_at": (
                    next_run_at.isoformat()
                    if isinstance(next_run_at, datetime)
                    else next_run_at
                ),
                "last_result": last_result,
                "result_class": _classify_result(
                    str(last_result) if last_result is not None else None
                ),
            }
        )
    return out


def _search_plan_section(plan: SearchPlan) -> dict[str, Any]:
    return {
        "terms": list(plan.terms),
        "term_count": len(plan.terms),
        "seed_account_count": len(plan.seed_accounts),
        "weights_by_niche": dict(plan.weights_by_niche),
        "updated_at": plan.updated_at,
        "stub": plan.stub,
    }


def _trim_proof_payload(payload: dict[str, Any]) -> dict[str, Any]:
    keep_keys = (
        "summary",
        "health",
        "ok",
        "queries",
        "new_posts",
        "already_in_db",
        "overlap_pct",
        "waste_pct",
        "apify_usd",
        "cost_usd",
        "niche_mix",
        "freshness",
        "skipped",
        "skips",
        "error",
    )
    trimmed: dict[str, Any] = {}
    for key in keep_keys:
        if key in payload:
            trimmed[key] = payload[key]
    # Cap large nested structures.
    for key in ("queries", "skips", "skipped"):
        value = trimmed.get(key)
        if isinstance(value, list) and len(value) > 12:
            trimmed[key] = value[:12] + [f"...(+{len(value) - 12} more)"]
    return trimmed


def _proofs_section(
    proofs: list[ScrapeProof],
    *,
    now: datetime,
) -> dict[str, Any]:
    since_24h = now - timedelta(hours=OPS_LOOKBACK_HOURS)
    since_7d = now - timedelta(days=PROOF_ROLLUP_DAYS)

    recent: list[dict[str, Any]] = []
    rollup_ok = 0
    rollup_fail = 0
    niches: dict[str, int] = {}
    overlap_vals: list[float] = []
    waste_vals: list[float] = []
    apify_usd = 0.0

    for proof in proofs:
        created = _parse_iso(proof.created_at)
        in_7d = _within(created, since=since_7d)
        in_24h = _within(created, since=since_24h)
        if in_7d:
            if proof.ok:
                rollup_ok += 1
            else:
                rollup_fail += 1
            if proof.niche:
                niches[proof.niche] = niches.get(proof.niche, 0) + 1
            payload = proof.payload or {}
            for key, bucket in (("overlap_pct", overlap_vals), ("waste_pct", waste_vals)):
                raw = payload.get(key)
                try:
                    if raw is not None:
                        bucket.append(float(raw))
                except (TypeError, ValueError):
                    pass
            for key in ("apify_usd", "cost_usd"):
                raw = payload.get(key)
                try:
                    if raw is not None:
                        apify_usd += float(raw)
                except (TypeError, ValueError):
                    pass

        if in_24h or len(recent) < 10:
            recent.append(
                {
                    "id": proof.id,
                    "job_id": proof.job_id,
                    "niche": proof.niche,
                    "created_at": proof.created_at,
                    "ok": proof.ok,
                    "summary": proof.summary,
                    "payload": _trim_proof_payload(proof.payload or {}),
                }
            )

    return {
        "recent": recent[:PROOF_LIST_LIMIT],
        "rollup_7d": {
            "ok": rollup_ok,
            "fail": rollup_fail,
            "niches": niches,
            "apify_usd_sum": round(apify_usd, 4),
            "avg_overlap_pct": (
                round(sum(overlap_vals) / len(overlap_vals), 2) if overlap_vals else None
            ),
            "avg_waste_pct": (
                round(sum(waste_vals) / len(waste_vals), 2) if waste_vals else None
            ),
        },
    }


def _validation_section(settings: Settings) -> dict[str, Any]:
    if not settings.database_url:
        return {"error": "DATABASE_URL not set"}
    try:
        from storage.vector_store import get_connection
        from validation_pipeline.store import fetch_accuracy_aggregates

        conn = get_connection(settings)
        try:
            agg = fetch_accuracy_aggregates(conn)
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Validation aggregates unavailable: %s", exc)
        return {"error": str(exc)}

    return {
        "total_validated": agg.total_validated,
        "mae": agg.mean_absolute_error,
        "raw_mae": agg.raw_mean_absolute_error,
        "calibrated_mae": agg.calibrated_mean_absolute_error,
        "median_ae": agg.median_absolute_error,
        "pct_within_10": agg.pct_within_10,
        "mean_accuracy_score": agg.mean_accuracy_score,
        "mae_likes": agg.mae_likes,
        "mae_comments": agg.mae_comments,
        "mae_shares": agg.mae_shares,
        "mae_total_engagement": agg.mae_total_engagement,
        "note": "Global aggregates over validated predictions (not a strict 7d window).",
    }


def _feedback_section(settings: Settings) -> dict[str, Any]:
    if not settings.database_url:
        return {"error": "DATABASE_URL not set"}
    try:
        from feedback.queue import count_feedback_queue_backlog
        from storage.vector_store import get_connection

        conn = get_connection(settings)
        try:
            backlog = count_feedback_queue_backlog(conn)
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Feedback backlog unavailable: %s", exc)
        return {"error": str(exc)}

    return {
        "pending": backlog.pending,
        "processing": backlog.processing,
        "done": backlog.done,
        "dead": backlog.dead,
        "open_count": backlog.open_count,
    }


def _apify_section(settings: Settings, *, now: datetime) -> dict[str, Any]:
    try:
        from telemetry.apify import load_apify_runs, summarize_apify_runs
    except Exception as exc:
        return {"error": str(exc)}

    since = now - timedelta(hours=OPS_LOOKBACK_HOURS)
    try:
        runs = load_apify_runs(settings, limit=APIFY_RUN_LIMIT)
    except Exception as exc:
        return {"error": str(exc)}

    recent = []
    for run in runs:
        ts = run.finished_at or run.started_at or run.recorded_at
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts is not None and ts < since:
            continue
        recent.append(run)

    if not recent:
        # Fall back to last N if none in window (sparse telemetry).
        recent = list(runs)[-20:]

    summary = summarize_apify_runs(recent)
    return {
        "run_count": summary.run_count,
        "total_cost_usd": summary.total_cost_usd,
        "post_search_cost_usd": summary.post_search_cost_usd,
        "profile_scrape_cost_usd": summary.profile_scrape_cost_usd,
        "runs": [
            {
                "run_id": r.run_id,
                "scraper": r.scraper,
                "status": r.status,
                "cost_usd": r.cost_usd,
                "item_count": r.item_count,
                "context": r.context,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
            }
            for r in recent[:20]
        ],
    }


def _errors_section(
    job_runs: list[dict[str, Any]],
    proofs: dict[str, Any],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for job in job_runs:
        cls = job.get("result_class")
        if cls in {"failed", "skipped"}:
            errors.append(
                {
                    "source": "job_runs",
                    "job_id": job.get("job_id"),
                    "class": cls,
                    "detail": job.get("last_result"),
                }
            )
    for proof in proofs.get("recent") or []:
        if not proof.get("ok", True):
            errors.append(
                {
                    "source": "scrape_proof",
                    "job_id": proof.get("job_id"),
                    "class": "failed",
                    "detail": proof.get("summary"),
                    "id": proof.get("id"),
                }
            )
    return errors[:40]


def _truncate_snapshot(snapshot: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    raw = json.dumps(snapshot, default=str)
    if len(raw) <= max_chars:
        snapshot["meta"] = {
            **(snapshot.get("meta") or {}),
            "truncated": False,
            "char_count": len(raw),
        }
        return snapshot

    # Drop bulky lists first.
    if "apify" in snapshot and isinstance(snapshot["apify"], dict):
        snapshot["apify"] = {
            k: v for k, v in snapshot["apify"].items() if k != "runs"
        } | {"runs_omitted": True}
    if "scrape_proofs" in snapshot and isinstance(snapshot["scrape_proofs"], dict):
        recent = snapshot["scrape_proofs"].get("recent") or []
        snapshot["scrape_proofs"]["recent"] = recent[:5]

    raw2 = json.dumps(snapshot, default=str)
    snapshot["meta"] = {
        **(snapshot.get("meta") or {}),
        "truncated": True,
        "char_count": len(raw2),
        "max_chars": max_chars,
    }
    if len(raw2) > max_chars:
        # Hard clip string form of search terms if still huge.
        plan = snapshot.get("search_plan")
        if isinstance(plan, dict) and isinstance(plan.get("terms"), list):
            plan["terms"] = plan["terms"][:20]
            plan["terms_truncated"] = True
    return snapshot


def build_digest_snapshot(settings: Settings | None = None) -> dict[str, Any]:
    """Collect a structured ops snapshot for the Pro critic."""
    settings = settings or load_settings()
    now = _utc_now()
    flags = load_job_flags().to_dict()
    budget = get_budget_snapshot(settings)

    job_rows: dict[str, dict[str, Any]] = {}
    proofs: list[ScrapeProof] = []
    plan: SearchPlan | None = None
    section_errors: dict[str, str] = {}

    try:
        with agentic_connection(settings) as conn:
            job_rows = schedule_store.load_run_rows(conn)
            proofs = scrape_proof_store.list_proofs(conn, limit=PROOF_LIST_LIMIT)
    except AgenticDbError as exc:
        section_errors["agentic_db"] = str(exc)
    except Exception as exc:
        logger.exception("Agentic snapshot DB read failed")
        section_errors["agentic_db"] = str(exc)

    try:
        plan = get_search_plan(settings)
    except SearchPlanError as exc:
        section_errors["search_plan"] = str(exc)
    except Exception as exc:
        section_errors["search_plan"] = str(exc)

    job_runs = _job_runs_section(job_rows, flags)
    proofs_section = _proofs_section(proofs, now=now)
    snapshot: dict[str, Any] = {
        "budget": _budget_section(budget),
        "job_runs": job_runs,
        "search_plan": (
            _search_plan_section(plan)
            if plan is not None
            else {"error": section_errors.get("search_plan", "unavailable")}
        ),
        "scrape_proofs": proofs_section,
        "validation": _validation_section(settings),
        "feedback_queue": _feedback_section(settings),
        "apify": _apify_section(settings, now=now),
        "errors": _errors_section(job_runs, proofs_section),
        "meta": {
            "generated_at": now.replace(microsecond=0).isoformat(),
            "ops_lookback_hours": OPS_LOOKBACK_HOURS,
            "proof_rollup_days": PROOF_ROLLUP_DAYS,
            "flags": flags,
            "model": settings.agentic_pro_digest_model,
            "intervals": {
                "general_refresh_hours": settings.agentic_general_refresh_interval_hours,
                "niche_scrape_hours": settings.agentic_niche_scrape_interval_hours,
                "pro_digest_hours": settings.agentic_pro_digest_interval_hours,
            },
            "section_errors": section_errors or None,
            "policy": "read_only_advisory",
        },
    }
    return _truncate_snapshot(snapshot, max_chars=MAX_SNAPSHOT_CHARS)
