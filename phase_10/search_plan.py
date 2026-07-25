"""Search plan service stub (T10.2).

Today: persist operator seeds; derived niche weights stay empty until T10.2/T10.6.
"""

from __future__ import annotations

from datetime import datetime, timezone

from phase_10.json_store import read_json_object, write_json_object
from phase_10.models import SearchPlan, SeedConfig
from phase_10.paths import SEEDS_PATH


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_lines(raw: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
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
    return tuple(cleaned)


def load_seeds() -> SeedConfig:
    data = read_json_object(SEEDS_PATH)
    return SeedConfig(
        seed_terms=_clean_lines(data.get("seed_terms", [])),
        seed_accounts=_clean_lines(data.get("seed_accounts", [])),
        updated_at=data.get("updated_at") if isinstance(data.get("updated_at"), str) else None,
    )


def save_seeds(
    *,
    seed_terms: str | list[str] | tuple[str, ...],
    seed_accounts: str | list[str] | tuple[str, ...],
) -> SeedConfig:
    config = SeedConfig(
        seed_terms=_clean_lines(seed_terms),
        seed_accounts=_clean_lines(seed_accounts),
        updated_at=_utc_now_iso(),
    )
    write_json_object(SEEDS_PATH, config.to_dict())
    return config


def get_search_plan() -> SearchPlan:
    """Return the current plan.

    Weights are empty until T10.2 merges user-derived niches (T10.6).
    Terms/accounts come from saved seeds so jobs can already read a shape.
    """
    seeds = load_seeds()
    return SearchPlan(
        terms=seeds.seed_terms,
        seed_accounts=seeds.seed_accounts,
        weights_by_niche={},
        updated_at=seeds.updated_at,
        stub=True,
    )
