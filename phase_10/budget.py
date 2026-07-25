"""Cost control snapshot stub (T10.9 ledger + agentic attribution later)."""

from __future__ import annotations

import logging

from config.settings import Settings, load_settings
from phase_10.models import BudgetSnapshot

logger = logging.getLogger(__name__)

# Placeholder caps until T10.9 persists configurable ceilings.
_DEFAULT_APIFY_DAILY_CAP_USD = 25.0
_DEFAULT_GEMINI_DAILY_CAP_USD = 10.0


def get_budget_snapshot(settings: Settings | None = None) -> BudgetSnapshot:
    settings = settings or load_settings()
    apify_used = 0.0
    gemini_used = 0.0
    notes: list[str] = [
        "Caps are placeholders until T10.9; spend is file telemetry, not agentic-attributed.",
    ]

    try:
        from telemetry.apify import load_apify_runs, summarize_apify_runs

        apify_used = summarize_apify_runs(load_apify_runs(settings, limit=200)).total_cost_usd
    except Exception:
        logger.debug("Apify spend unavailable for budget snapshot", exc_info=True)
        notes.append("Apify spend unavailable.")

    try:
        from telemetry.gemini_cost import summarize_gemini_cost

        gemini_used = summarize_gemini_cost(settings, limit=200).total_cost_usd
    except Exception:
        logger.debug("Gemini spend unavailable for budget snapshot", exc_info=True)
        notes.append("Gemini spend unavailable.")

    return BudgetSnapshot(
        apify_used_usd=apify_used,
        apify_cap_usd=_DEFAULT_APIFY_DAILY_CAP_USD,
        gemini_used_usd=gemini_used,
        gemini_cap_usd=_DEFAULT_GEMINI_DAILY_CAP_USD,
        stub_caps=True,
        note=" ".join(notes),
    )
