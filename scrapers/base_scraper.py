"""Contract every platform scraper must follow.

Downstream code (storage, dashboard, and the future "make sense of samples"
pipeline stage) only ever depends on this interface, never on a specific
platform's implementation. Adding a new platform (TikTok, Instagram, X...)
later means writing one new subclass here - nothing else in the project
needs to change.
"""

from abc import ABC, abstractmethod
from typing import Any

from scrapers.result import ScrapeResult


class BaseScraper(ABC):
    platform_name: str

    @abstractmethod
    def fetch_samples(self, params: dict[str, Any]) -> ScrapeResult:
        """Fetch raw samples for the given search/run params.

        Must return a list of plain dicts exactly as received from the
        source - no normalization or schema enforcement here. Making sense
        of the data is a later pipeline stage's job, kept deliberately out
        of scrapers so this module stays simple and swappable.
        """
        raise NotImplementedError
