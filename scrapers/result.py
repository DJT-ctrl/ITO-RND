"""Result object returned by platform scrapers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from telemetry.apify_schemas import ApifyRunRecord


@dataclass
class ScrapeResult:
    """Raw items from a scraper run plus optional Apify billing metadata."""

    items: list[dict[str, Any]]
    run_record: Optional[ApifyRunRecord] = None
