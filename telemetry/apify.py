"""Apify run cost extraction and persistence."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config.paths import resolve_data_path
from config.settings import Settings
from telemetry.apify_schemas import ApifyCostSummary, ApifyRunRecord, ApifyScraperKind

logger = logging.getLogger(__name__)

_APIFY_LOG_NAME = "apify_runs.jsonl"


def _parse_apify_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def apify_run_record_from_response(
    run: dict[str, Any],
    *,
    actor_id: str,
    scraper: ApifyScraperKind,
    item_count: int,
    context: Optional[str] = None,
) -> ApifyRunRecord:
    """Build a run record from an Apify actor .call() response dict."""
    stats = run.get("stats") or {}
    usage_total = run.get("usageTotalUsd")
    cost_usd = float(usage_total) if usage_total is not None else 0.0
    compute_units = stats.get("computeUnits")
    return ApifyRunRecord(
        run_id=str(run.get("id") or ""),
        actor_id=actor_id,
        scraper=scraper,
        status=str(run.get("status") or "UNKNOWN"),
        cost_usd=round(cost_usd, 6),
        compute_units=float(compute_units) if compute_units is not None else None,
        started_at=_parse_apify_datetime(run.get("startedAt")),
        finished_at=_parse_apify_datetime(run.get("finishedAt")),
        item_count=item_count,
        context=context,
        recorded_at=datetime.now(timezone.utc),
    )


def _apify_log_path(settings: Settings) -> Path:
    return resolve_data_path(settings.telemetry_data_dir) / _APIFY_LOG_NAME


def save_apify_run(record: ApifyRunRecord, settings: Settings) -> Optional[Path]:
    """Append one Apify run record to the JSONL log."""
    path = _apify_log_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return path
    except OSError as exc:
        logger.warning("Failed to persist Apify telemetry to %s: %s", path, exc)
        return None


def save_apify_runs(records: list[ApifyRunRecord], settings: Settings) -> None:
    for record in records:
        save_apify_run(record, settings)


def load_apify_runs(settings: Settings, *, limit: int = 100) -> list[ApifyRunRecord]:
    """Load the most recent Apify run records from the JSONL log."""
    path = _apify_log_path(settings)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[ApifyRunRecord] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(ApifyRunRecord.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValueError):
            continue
    return records


def summarize_apify_runs(runs: list[ApifyRunRecord]) -> ApifyCostSummary:
    post_cost = sum(r.cost_usd for r in runs if r.scraper == "linkedin_posts")
    profile_cost = sum(r.cost_usd for r in runs if r.scraper == "linkedin_profiles")
    return ApifyCostSummary(
        run_count=len(runs),
        total_cost_usd=round(sum(r.cost_usd for r in runs), 6),
        post_search_cost_usd=round(post_cost, 6),
        profile_scrape_cost_usd=round(profile_cost, 6),
        runs=runs,
    )
