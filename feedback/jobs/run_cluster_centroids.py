"""Compute mean embedding centroids per metadata cluster (Phase H)."""

from __future__ import annotations

import argparse
import logging
from typing import Sequence

from config.settings import load_settings
from feedback.store import (
    fetch_validated_embeddings_by_metadata_cluster,
    refresh_cluster_stats,
    upsert_cluster_centroid,
)
from storage.vector_store import create_schema, get_connection

logger = logging.getLogger(__name__)


def mean_vector(vectors: Sequence[Sequence[float]]) -> list[float]:
    if not vectors:
        raise ValueError("Cannot average empty vector list")
    dim = len(vectors[0])
    sums = [0.0] * dim
    for vector in vectors:
        if len(vector) != dim:
            raise ValueError("Inconsistent embedding dimensions")
        for index, value in enumerate(vector):
            sums[index] += float(value)
    count = float(len(vectors))
    return [value / count for value in sums]


def refresh_cluster_centroids() -> int:
    """Upsert centroid_embedding for each metadata cluster with embeddings.

    Returns number of centroids written.
    """
    settings = load_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set.")

    conn = get_connection(settings)
    try:
        create_schema(conn)
        refresh_cluster_stats(conn)
        grouped = fetch_validated_embeddings_by_metadata_cluster(conn)
        written = 0
        for cluster_id, vectors in grouped.items():
            if not vectors:
                continue
            centroid = mean_vector(vectors)
            upsert_cluster_centroid(
                conn,
                cluster_id,
                centroid,
                sample_count=len(vectors),
            )
            written += 1
            logger.info(
                "Centroid for %s from %s embeddings",
                cluster_id,
                len(vectors),
            )
        return written
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    count = refresh_cluster_centroids()
    print(f"Updated {count} cluster centroids")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
