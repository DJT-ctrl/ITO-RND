"""List scrape proof reports for the Agentic Layer (T10.5.5)."""

from __future__ import annotations

from config.settings import Settings, load_settings
from phase_10.db import AgenticDbError, agentic_connection
from phase_10.models import ScrapeProof
from phase_10 import scrape_proof_store


def list_scrape_proofs(
    settings: Settings | None = None,
    *,
    limit: int = 20,
) -> list[ScrapeProof]:
    settings = settings or load_settings()
    try:
        with agentic_connection(settings) as conn:
            return scrape_proof_store.list_proofs(conn, limit=limit)
    except AgenticDbError:
        return []
