"""Corpus pipeline helpers exposed over HTTP (analyse file → embed → pgvector)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from config.settings import Settings, load_settings
from processors.embedder import embed_batch
from processors.run_db_ingest import ingest_embedded_records, run_db_ingest
from processors.run_embeddings import load_and_join
from storage.vector_store import count_posts, create_schema, get_connection

CorpusMode = Literal["embed_and_ingest", "ingest_only"]


def run_corpus_ingest(
    *,
    mode: CorpusMode = "embed_and_ingest",
    processed_file: Optional[str] = None,
    embeddings_file: Optional[str] = None,
    limit: Optional[int] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """Run corpus land-in-vector-DB work and return a compact result dict."""
    settings = settings or load_settings()
    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set — cannot ingest into Postgres.")

    if mode == "ingest_only":
        upserted = run_db_ingest(
            processed_file=processed_file,
            embeddings_file=embeddings_file,
            settings=settings,
            skip_backup=True,
        )
        return {
            "mode": mode,
            "upserted": upserted,
            "skipped": 0,
            "processed_file": processed_file,
            "embeddings_file": embeddings_file,
        }

    joined, jsonl_path, _ = load_and_join(processed_file, settings)
    if limit is not None:
        joined = joined[:limit]

    vectors, skipped = embed_batch(joined, settings)
    eligible = [
        record
        for record in joined
        if (record.get("content") or "").strip() and record.get("word_count", 0) >= 10
    ]
    eligible = eligible[: len(vectors)]
    upserted = ingest_embedded_records(
        eligible,
        vectors,
        settings=settings,
        skip_backup=True,
    )
    return {
        "mode": mode,
        "upserted": upserted,
        "skipped": skipped,
        "processed_file": str(jsonl_path),
        "embeddings_file": None,
    }


def get_corpus_stats(*, settings: Optional[Settings] = None) -> dict[str, Any]:
    """Post count + optional on-disk corpus benchmark snapshot."""
    from processors.corpus_benchmarks import is_stale, load_snapshot

    settings = settings or load_settings()
    post_count = 0
    if settings.database_url:
        conn = get_connection(settings)
        try:
            create_schema(conn)
            post_count = count_posts(conn)
        finally:
            conn.close()

    snapshot = load_snapshot()
    return {
        "post_count": post_count,
        "benchmarks": snapshot,
        "benchmarks_stale": is_stale(ttl_hours=settings.corpus_benchmark_ttl_hours),
        "benchmarks_path": str(Path("data/processed/corpus_benchmarks.json")),
    }
