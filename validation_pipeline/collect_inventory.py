"""Collect page dataset inventory (meta ids, no JSONL scan)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from storage.pipeline_registry import read_artefact_meta

if TYPE_CHECKING:
    from validation_pipeline.vectorized_corpus import VectorizedDataset


@dataclass(frozen=True)
class DatasetInventoryRow:
    """Compact inventory row for the Collect dashboard."""

    label: str
    jsonl_name: str
    embeddings_name: str
    vector_count: int
    unique_ids_available: int
    has_meta_ids: bool
    bundle_id: str | None = None


def _embedding_post_ids_from_meta(embeddings_path: Path) -> list[str]:
    """Read ``embedding_post_ids`` from ``*.npy.meta.json`` when present."""
    meta = read_artefact_meta(embeddings_path)
    if not meta:
        return []
    raw_ids = meta.get("embedding_post_ids") or meta.get("post_ids") or []
    return [str(post_id) for post_id in raw_ids if post_id]


def unique_post_ids_from_vectorized_datasets(
    datasets: list[VectorizedDataset],
) -> set[str]:
    """Union post ids from embedding meta files across datasets."""
    ids: set[str] = set()
    for dataset in datasets:
        ids.update(_embedding_post_ids_from_meta(dataset.embeddings_path))
    return ids


def dataset_inventory_rows(
    datasets: list[VectorizedDataset],
) -> list[DatasetInventoryRow]:
    """Build per-dataset inventory rows (meta id count or vector_count fallback)."""
    rows: list[DatasetInventoryRow] = []
    for dataset in datasets:
        meta_ids = _embedding_post_ids_from_meta(dataset.embeddings_path)
        has_meta = bool(meta_ids)
        rows.append(
            DatasetInventoryRow(
                label=dataset.label,
                jsonl_name=dataset.jsonl_path.name,
                embeddings_name=dataset.embeddings_path.name,
                vector_count=dataset.vector_count,
                unique_ids_available=len(set(meta_ids)) if has_meta else dataset.vector_count,
                has_meta_ids=has_meta,
                bundle_id=dataset.bundle_id,
            )
        )
    return rows


def estimate_corpus_unique_count(datasets: list[VectorizedDataset]) -> int:
    """Deduped corpus size from meta ids, with vector_count fallback for gaps."""
    union: set[str] = set()
    missing_meta_vectors = 0
    for dataset in datasets:
        meta_ids = _embedding_post_ids_from_meta(dataset.embeddings_path)
        if meta_ids:
            union.update(meta_ids)
        else:
            missing_meta_vectors += dataset.vector_count
    return len(union) + missing_meta_vectors


def build_dataset_inventory_and_unique(
    datasets: list[VectorizedDataset],
) -> tuple[list[DatasetInventoryRow], int]:
    """Single-pass inventory rows + corpus unique count (reads each meta once)."""
    rows: list[DatasetInventoryRow] = []
    union: set[str] = set()
    missing_meta_vectors = 0
    for dataset in datasets:
        meta_ids = _embedding_post_ids_from_meta(dataset.embeddings_path)
        has_meta = bool(meta_ids)
        if has_meta:
            unique_local = set(meta_ids)
            union.update(unique_local)
            unique_count = len(unique_local)
        else:
            unique_count = dataset.vector_count
            missing_meta_vectors += dataset.vector_count
        rows.append(
            DatasetInventoryRow(
                label=dataset.label,
                jsonl_name=dataset.jsonl_path.name,
                embeddings_name=dataset.embeddings_path.name,
                vector_count=dataset.vector_count,
                unique_ids_available=unique_count,
                has_meta_ids=has_meta,
                bundle_id=dataset.bundle_id,
            )
        )
    return rows, len(union) + missing_meta_vectors
