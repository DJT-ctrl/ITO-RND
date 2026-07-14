"""Backfill predictions.embedding for pre-Phase-H validated rows."""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

from config.settings import Settings, load_settings
from feedback.store import (
    fetch_predictions_missing_embeddings,
    update_prediction_embedding,
)
from processors.embedder import EMBEDDING_MODEL_VERSION, embed_batch
from storage.vector_store import create_schema, get_connection

logger = logging.getLogger(__name__)

_MIN_WORD_COUNT = 10


@dataclass
class EmbeddingBackfillResult:
    considered: int = 0
    embedded: int = 0
    skipped_short: int = 0
    failed: int = 0


def run_embedding_backfill(
    settings: Settings | None = None,
    *,
    limit: int = 50,
    dry_run: bool = False,
) -> EmbeddingBackfillResult:
    """Embed validated predictions that still have NULL embedding.

    Uses the same gemini-embedding-001 path as live predict. Skips posts with
    fewer than 10 words (embed_batch contract). Supports --limit / --dry-run
    to control API spend.
    """
    settings = settings or load_settings()
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set (check your .env file).")
    if not dry_run and not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set (check your .env file).")

    result = EmbeddingBackfillResult()
    conn = get_connection(settings)
    try:
        create_schema(conn)
        missing = fetch_predictions_missing_embeddings(conn, limit=limit)
    finally:
        conn.close()

    result.considered = len(missing)
    if not missing:
        return result

    records: list[dict] = []
    ids_for_batch: list = []
    for prediction_id, content in missing:
        word_count = len((content or "").split())
        if word_count < _MIN_WORD_COUNT or not (content or "").strip():
            result.skipped_short += 1
            continue
        records.append({"content": content, "word_count": word_count})
        ids_for_batch.append(prediction_id)

    if dry_run:
        result.embedded = len(records)
        logger.info(
            "Dry run: would embed %s predictions (%s skipped short)",
            result.embedded,
            result.skipped_short,
        )
        return result

    if not records:
        return result

    try:
        vectors, skipped = embed_batch(records, settings)
    except Exception:
        logger.exception("Embedding API call failed")
        result.failed = len(records)
        return result

    # embed_batch may skip additional rows; map only returned vectors in order.
    valid_ids = ids_for_batch
    if skipped:
        # Recompute which records survived the same filter embed_batch uses.
        valid_ids = [
            prediction_id
            for prediction_id, record in zip(ids_for_batch, records)
            if (record.get("content") or "").strip()
            and record.get("word_count", 0) >= _MIN_WORD_COUNT
        ]
        result.skipped_short += skipped

    if len(vectors) != len(valid_ids):
        logger.error(
            "Embedding count mismatch: got %s vectors for %s ids",
            len(vectors),
            len(valid_ids),
        )
        result.failed = len(valid_ids)
        return result

    conn = get_connection(settings)
    try:
        create_schema(conn)
        for prediction_id, vector in zip(valid_ids, vectors):
            try:
                update_prediction_embedding(
                    conn,
                    prediction_id,
                    [float(x) for x in vector.tolist()],
                    embedding_model_version=EMBEDDING_MODEL_VERSION,
                )
                result.embedded += 1
            except Exception:
                logger.exception("Failed to write embedding for %s", prediction_id)
                result.failed += 1
    finally:
        conn.close()

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max predictions to consider (default 50). Raise carefully — API cost.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count eligible rows without calling Gemini or writing embeddings.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run_embedding_backfill(limit=args.limit, dry_run=args.dry_run)
    print(
        f"considered={result.considered} embedded={result.embedded} "
        f"skipped_short={result.skipped_short} failed={result.failed}"
        + (" (dry-run)" if args.dry_run else "")
    )


if __name__ == "__main__":
    main()
