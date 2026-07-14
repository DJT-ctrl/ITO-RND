"""Aggregate Gemini token usage and estimated USD cost across evaluation runs.

Reads persisted eval_*.json telemetry files and sums input/output tokens
and cost to give an overall Gemini spend estimate — the AI-side counterpart
to the existing Apify scraper cost tracking.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config.paths import DEFAULT_TELEMETRY_DATA_DIR, resolve_data_path
from config.settings import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeminiCostSummary:
    """Aggregated Gemini usage across one or more evaluation runs."""

    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    run_count: int
    llm_step_count: int
    embedding_step_count: int


def _telemetry_dir(settings: Settings) -> Path:
    return resolve_data_path(
        getattr(settings, "telemetry_data_dir", DEFAULT_TELEMETRY_DATA_DIR)
    )


def load_eval_runs(
    settings: Settings,
    *,
    limit: Optional[int] = None,
) -> list[dict]:
    """Load persisted eval_*.json telemetry files, newest-first.

    Returns the parsed JSON dicts so callers can inspect per-run detail
    if needed.  ``limit`` caps how many files are read (None = all).
    """
    directory = _telemetry_dir(settings)
    if not directory.exists():
        return []
    files = sorted(directory.glob("eval_*.json"), reverse=True)
    if limit is not None:
        files = files[:limit]
    runs: list[dict] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            runs.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping malformed telemetry file %s: %s", path.name, exc)
    return runs


def summarize_gemini_cost(
    settings: Settings,
    *,
    limit: Optional[int] = None,
) -> GeminiCostSummary:
    """Aggregate Gemini token/cost totals from persisted evaluation runs."""
    runs = load_eval_runs(settings, limit=limit)
    total_input = 0
    total_output = 0
    total_cost = 0.0
    llm_steps = 0
    embedding_steps = 0

    for run in runs:
        total_input += int(run.get("total_input_tokens", 0))
        total_output += int(run.get("total_output_tokens", 0))
        total_cost += float(run.get("total_cost_usd", 0.0))
        for step in run.get("steps", []):
            call_type = step.get("call_type", "")
            if call_type == "llm":
                llm_steps += 1
            elif call_type == "embedding":
                embedding_steps += 1

    return GeminiCostSummary(
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_tokens=total_input + total_output,
        total_cost_usd=round(total_cost, 6),
        run_count=len(runs),
        llm_step_count=llm_steps,
        embedding_step_count=embedding_steps,
    )
