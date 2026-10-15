"""Simple coverage-gap detection for Phase 19 daily refresh."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


MIN_ACCEPTED_EVIDENCE = 15
FRESHNESS_HOURS = 48.0
MAX_DOMINANT_AUTHOR_SHARE = 0.7


@dataclass(frozen=True)
class GapAssessment:
    needs_collection: bool
    reasons: tuple[str, ...]
    recommended_seeds: tuple[str, ...] = ()


def assess_gaps(
    stats: dict[str, Any],
    *,
    brief: dict[str, Any],
    now: datetime | None = None,
) -> GapAssessment:
    """Return named gaps that justify a bounded daily refresh."""
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    accepted = int(stats.get("accepted_count") or 0)
    newest = stats.get("newest_at")
    dominant = float(stats.get("dominant_author_share") or 0.0)

    if accepted < MIN_ACCEPTED_EVIDENCE:
        reasons.append(
            f"coverage_gap: accepted={accepted} < {MIN_ACCEPTED_EVIDENCE}"
        )

    if newest is None:
        reasons.append("freshness_gap: no accepted evidence yet")
    else:
        if isinstance(newest, str):
            newest_dt = datetime.fromisoformat(newest.replace("Z", "+00:00"))
        else:
            newest_dt = newest
        if newest_dt.tzinfo is None:
            newest_dt = newest_dt.replace(tzinfo=timezone.utc)
        age = now - newest_dt
        if age > timedelta(hours=FRESHNESS_HOURS):
            reasons.append(
                f"freshness_gap: newest evidence older than {FRESHNESS_HOURS:.0f}h"
            )

    if accepted >= MIN_ACCEPTED_EVIDENCE and dominant > MAX_DOMINANT_AUTHOR_SHARE:
        reasons.append(
            f"diversity_gap: dominant author share {dominant:.2f} > {MAX_DOMINANT_AUTHOR_SHARE}"
        )

    # Unusual seed recommendations are recorded only — never auto-collected.
    recommended: list[str] = []
    role = str(brief.get("role_description") or "").strip()
    if role and not brief.get("seed_accounts"):
        recommended.append(
            "operator_review: consider adding approved niche peer seed accounts"
        )

    return GapAssessment(
        needs_collection=bool(reasons),
        reasons=tuple(reasons),
        recommended_seeds=tuple(recommended),
    )
