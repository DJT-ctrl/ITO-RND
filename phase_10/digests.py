"""Dev AI digests service (T10.10 Pro workflow critic)."""

from __future__ import annotations

import logging

from config.settings import Settings, load_settings
from phase_10.budget import record_agentic_spend
from phase_10.db import AgenticDbError, agentic_connection
from phase_10.digest_critic import run_critic
from phase_10.digest_snapshot import build_digest_snapshot
from phase_10 import digest_store
from phase_10.models import DigestRecord

logger = logging.getLogger(__name__)


def list_digests(
    settings: Settings | None = None,
    *,
    limit: int = 10,
) -> list[DigestRecord]:
    """Return recent Pro digests (newest first)."""
    settings = settings or load_settings()
    try:
        with agentic_connection(settings) as conn:
            return digest_store.list_digests(conn, limit=limit)
    except AgenticDbError:
        return []
    except Exception:
        logger.exception("list_digests failed")
        return []


def run_pro_digest(settings: Settings | None = None) -> str:
    """Build snapshot, call Pro critic, persist digest + spend. Tick one-liner."""
    settings = settings or load_settings()
    snapshot = build_digest_snapshot(settings)
    result = run_critic(snapshot, settings)

    with agentic_connection(settings) as conn:
        record = digest_store.insert_digest(
            conn,
            model=result.model,
            summary=result.summary_markdown,
            severity=result.severity,
            payload=result.payload,
        )

    if result.cost_usd > 0:
        try:
            record_agentic_spend(
                job_id="pro_digest",
                provider="gemini",
                cost_usd=result.cost_usd,
                settings=settings,
            )
        except Exception:
            logger.exception("Failed to record Pro digest spend")

    return (
        f"Done: severity={record.severity} findings={len(result.findings)} "
        f"id={record.id}"
    )
