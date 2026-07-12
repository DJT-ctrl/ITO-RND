"""Model pricing helpers for evaluation telemetry cost estimates."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

# USD per 1M tokens — approximate Google AI Studio rates (2026).
# Override via TELEMETRY_PRICING_OVERRIDES JSON env when rates change.
_DEFAULT_RATES: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {"input_per_1m": 0.30, "output_per_1m": 2.50},
    "gemini-2.5-flash-lite": {"input_per_1m": 0.10, "output_per_1m": 0.40},
    "gemini-embedding-001": {"input_per_1m": 0.025, "output_per_1m": 0.0},
}


@dataclass(frozen=True)
class ModelRates:
    input_per_1m: float
    output_per_1m: float


def _normalize_model_id(model: Optional[str]) -> str:
    if not model:
        return "gemini-2.5-flash"
    raw = model.strip()
    for prefix in ("google-gla:", "google:", "models/"):
        if raw.startswith(prefix):
            raw = raw.split(":", 1)[-1] if ":" in raw else raw[len(prefix) :]
    if raw.startswith("models/"):
        raw = raw[len("models/") :]
    return raw


def _load_rates_table() -> dict[str, ModelRates]:
    table = {
        name: ModelRates(input_per_1m=r["input_per_1m"], output_per_1m=r["output_per_1m"])
        for name, r in _DEFAULT_RATES.items()
    }
    raw = os.getenv("TELEMETRY_PRICING_OVERRIDES", "")
    if raw.strip():
        try:
            overrides: dict[str, Any] = json.loads(raw)
            for name, rates in overrides.items():
                table[name] = ModelRates(
                    input_per_1m=float(rates["input_per_1m"]),
                    output_per_1m=float(rates.get("output_per_1m", 0.0)),
                )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    return table


def get_model_rates(model: Optional[str]) -> ModelRates:
    normalized = _normalize_model_id(model)
    table = _load_rates_table()
    if normalized in table:
        return table[normalized]
    # Fuzzy match for variant model strings.
    for key, rates in table.items():
        if key in normalized or normalized in key:
            return rates
    return table["gemini-2.5-flash"]


def cost_from_tokens(
    model: Optional[str],
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    rates = get_model_rates(model)
    cost = (input_tokens / 1_000_000) * rates.input_per_1m
    cost += (output_tokens / 1_000_000) * rates.output_per_1m
    return round(cost, 8)


def cost_from_llm_usage(model: Optional[str], usage: Any) -> tuple[int, int, float]:
    """Extract tokens and USD cost from a pydantic_ai RunUsage-like object."""
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cost = cost_from_tokens(model, input_tokens=input_tokens, output_tokens=output_tokens)
    return input_tokens, output_tokens, cost


def cost_from_embedding_tokens(model: Optional[str], prompt_tokens: int) -> float:
    return cost_from_tokens(model or "gemini-embedding-001", input_tokens=prompt_tokens)
