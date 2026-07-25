"""Agentic tick: decide due jobs, gate on budget, run or skip (T10.3)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

import psycopg

from config.settings import Settings, load_settings
from phase_10.budget import JOB_PROVIDER, allow_paid_step
from phase_10.db import AgenticDbError, agentic_connection
from phase_10.job_flags import load_job_flags
from phase_10.models import JOB_FLAG_KEYS
from phase_10 import schedule_store
from phase_10.schedule_store import utc_now

logger = logging.getLogger(__name__)

# validation rescrape > niche > general; then feedback / digest.
TICK_PRIORITY: tuple[str, ...] = (
    "validation_worker",
    "niche_scrape",
    "general_refresh",
    "feedback_worker",
    "pro_digest",
)

STUB_REASONS: dict[str, str] = {
    "pro_digest": "not implemented — T10.10",
}

_INTERVAL_ATTR = {
    "general_refresh": "agentic_general_refresh_interval_hours",
    "niche_scrape": "agentic_niche_scrape_interval_hours",
    "pro_digest": "agentic_pro_digest_interval_hours",
}

Handler = Callable[[Settings], str]


@dataclass(frozen=True)
class TickJobResult:
    job_id: str
    action: str  # ran | skipped
    detail: str


@dataclass(frozen=True)
class TickResult:
    results: tuple[TickJobResult, ...]


def _interval_hours(job_id: str, settings: Settings) -> float | None:
    """Hours between runs. None = every tick when enabled."""
    attr = _INTERVAL_ATTR.get(job_id)
    return getattr(settings, attr) if attr else None


def _aware(dt: datetime | None, tz) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def _is_due(
    now: datetime,
    next_run_at: datetime | None,
    last_run_at: datetime | None,
    interval_hours: float | None,
) -> bool:
    if interval_hours is None:
        return True
    next_at = _aware(next_run_at, now.tzinfo)
    if next_at is not None:
        return now >= next_at
    last = _aware(last_run_at, now.tzinfo)
    return last is None or now >= last + timedelta(hours=interval_hours)


def _next_run(now: datetime, interval_hours: float | None) -> datetime:
    if interval_hours is None:
        return now
    return now + timedelta(hours=interval_hours)


def _run_validation(settings: Settings) -> str:
    from validation_pipeline.worker import run_due_validations

    batch = run_due_validations(settings, limit=settings.agentic_validation_limit)
    return (
        f"Done: processed={batch.processed} validated={batch.validated} "
        f"failed={batch.failed}"
    )


def _run_feedback(settings: Settings) -> str:
    from feedback.batch import run_feedback_worker

    result = run_feedback_worker(settings, limit=settings.agentic_feedback_limit)
    return (
        f"Done: claimed={result.claimed} succeeded={result.succeeded} "
        f"failed={result.failed} dead_lettered={result.dead_lettered}"
    )


def _run_general_refresh(settings: Settings) -> str:
    from phase_10.corpus_refresh import run_general_refresh

    return run_general_refresh(settings).summary


def _run_niche_scrape(settings: Settings) -> str:
    from phase_10.corpus_refresh import run_niche_scrape

    return run_niche_scrape(settings).summary


HANDLERS: dict[str, Handler] = {
    "validation_worker": _run_validation,
    "feedback_worker": _run_feedback,
    "general_refresh": _run_general_refresh,
    "niche_scrape": _run_niche_scrape,
}


def _save(
    conn: psycopg.Connection,
    job_id: str,
    *,
    detail: str,
    now: datetime | None = None,
    interval: float | None = None,
    advance: bool = False,
) -> None:
    kwargs: dict = {"job_id": job_id, "last_result": detail}
    if advance and now is not None:
        kwargs["last_run_at"] = now
        kwargs["next_run_at"] = _next_run(now, interval)
    schedule_store.upsert_run(conn, **kwargs)


def run_agentic_tick(
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
    handlers: dict[str, Handler] | None = None,
) -> TickResult:
    """Evaluate each job once; run or skip with a logged reason."""
    settings = settings or load_settings()
    now = now or utc_now()
    handlers = HANDLERS if handlers is None else handlers
    flags = load_job_flags().to_dict()

    try:
        with agentic_connection(settings) as conn:
            rows = schedule_store.load_run_rows(conn)
            results: list[TickJobResult] = []

            for job_id in TICK_PRIORITY:
                if job_id not in JOB_FLAG_KEYS:
                    continue
                row = rows.get(job_id, {})
                interval = _interval_hours(job_id, settings)

                if not flags.get(job_id, True):
                    detail = "skipped: disabled"
                    _save(conn, job_id, detail=detail)
                    results.append(TickJobResult(job_id, "skipped", detail))
                    continue

                if not _is_due(
                    now, row.get("next_run_at"), row.get("last_run_at"), interval
                ):
                    results.append(
                        TickJobResult(job_id, "skipped", "skipped: not due")
                    )
                    continue

                handler = handlers.get(job_id)
                stub = STUB_REASONS.get(job_id)
                if handler is None:
                    detail = f"skipped: {stub}" if stub else f"skipped: no handler for {job_id}"
                    _save(
                        conn, job_id, detail=detail, now=now, interval=interval, advance=True
                    )
                    results.append(TickJobResult(job_id, "skipped", detail))
                    continue

                provider = JOB_PROVIDER.get(job_id)
                if provider is not None:
                    decision = allow_paid_step(job_id, provider, settings=settings)
                    if not decision.allowed:
                        detail = f"skipped: {decision.reason}"
                        _save(conn, job_id, detail=detail)
                        results.append(TickJobResult(job_id, "skipped", detail))
                        continue

                try:
                    detail = handler(settings)
                    action = "ran"
                except Exception as exc:
                    logger.exception("Agentic job %s failed", job_id)
                    detail = f"failed: {exc}"
                    action = "skipped"

                _save(
                    conn, job_id, detail=detail, now=now, interval=interval, advance=True
                )
                results.append(TickJobResult(job_id, action, detail))

            return TickResult(results=tuple(results))
    except AgenticDbError as exc:
        logger.error("Agentic tick aborted: %s", exc)
        return TickResult(
            results=(TickJobResult("_tick", "skipped", f"aborted: {exc}"),),
        )
