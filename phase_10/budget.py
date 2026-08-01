"""Cost control snapshot + budget gate (T10.9 / T10.3)."""

from __future__ import annotations

import logging

from config.settings import Settings, load_settings
from phase_10.cost_ledger_store import (
    Provider,
    record_spend as _store_record_spend,
    sum_spend,
    sum_spend_month,
)
from phase_10.db import AgenticDbError, agentic_connection
from phase_10.models import BudgetDecision, BudgetSnapshot

logger = logging.getLogger(__name__)

# Paid provider per job (None = no budget gate).
JOB_PROVIDER: dict[str, Provider | None] = {
    "validation_worker": "apify",
    "multi_horizon_predict": "gemini",
    "niche_scrape": "apify",
    "general_refresh": "apify",
    "feedback_worker": "gemini",
    "pro_digest": "gemini",
}


def _caps_snapshot(settings: Settings, *, note: str = "") -> BudgetSnapshot:
    return BudgetSnapshot(
        apify_cap_usd=settings.agentic_apify_daily_cap_usd,
        gemini_cap_usd=settings.agentic_gemini_daily_cap_usd,
        apify_month_cap_usd=settings.agentic_apify_monthly_cap_usd,
        gemini_month_cap_usd=settings.agentic_gemini_monthly_cap_usd,
        note=note,
    )


def get_budget_snapshot(settings: Settings | None = None) -> BudgetSnapshot:
    settings = settings or load_settings()
    try:
        with agentic_connection(settings) as conn:
            return BudgetSnapshot(
                apify_used_usd=sum_spend(conn, provider="apify"),
                apify_cap_usd=settings.agentic_apify_daily_cap_usd,
                gemini_used_usd=sum_spend(conn, provider="gemini"),
                gemini_cap_usd=settings.agentic_gemini_daily_cap_usd,
                apify_month_used_usd=sum_spend_month(conn, provider="apify"),
                apify_month_cap_usd=settings.agentic_apify_monthly_cap_usd,
                gemini_month_used_usd=sum_spend_month(conn, provider="gemini"),
                gemini_month_cap_usd=settings.agentic_gemini_monthly_cap_usd,
            )
    except AgenticDbError as exc:
        logger.debug("Budget snapshot unavailable: %s", exc)
        return _caps_snapshot(settings, note=f"Ledger unavailable: {exc}")
    except Exception:
        logger.exception("Budget snapshot failed")
        return _caps_snapshot(settings, note="Ledger query failed; caps from settings.")


def allow_paid_step(
    job_id: str,
    provider: Provider | None = None,
    *,
    settings: Settings | None = None,
) -> BudgetDecision:
    """Return whether ``job_id`` may start a paid step under daily/monthly caps."""
    settings = settings or load_settings()
    resolved = provider if provider is not None else JOB_PROVIDER.get(job_id)
    if resolved is None:
        return BudgetDecision(allowed=True)

    if resolved == "apify":
        daily_cap = settings.agentic_apify_daily_cap_usd
        monthly_cap = settings.agentic_apify_monthly_cap_usd
    else:
        daily_cap = settings.agentic_gemini_daily_cap_usd
        monthly_cap = settings.agentic_gemini_monthly_cap_usd

    try:
        with agentic_connection(settings) as conn:
            day_used = sum_spend(conn, provider=resolved)
            month_used = sum_spend_month(conn, provider=resolved)
    except AgenticDbError as exc:
        return BudgetDecision(allowed=False, reason=f"budget unavailable: {exc}")
    except Exception as exc:
        logger.exception("Budget gate failed for %s", job_id)
        return BudgetDecision(allowed=False, reason=f"budget gate error: {exc}")

    if day_used >= daily_cap:
        return BudgetDecision(
            allowed=False,
            reason=f"over {resolved} daily cap ({day_used:.4f} >= {daily_cap:.2f})",
        )
    if month_used >= monthly_cap:
        return BudgetDecision(
            allowed=False,
            reason=f"over {resolved} monthly cap ({month_used:.4f} >= {monthly_cap:.2f})",
        )
    return BudgetDecision(allowed=True)


def record_agentic_spend(
    *,
    job_id: str,
    provider: Provider,
    cost_usd: float,
    settings: Settings | None = None,
) -> None:
    """Persist attributed spend for an agentic job (call from T10.4/T10.5/T10.10)."""
    with agentic_connection(settings or load_settings()) as conn:
        _store_record_spend(conn, provider=provider, job_id=job_id, cost_usd=cost_usd)
