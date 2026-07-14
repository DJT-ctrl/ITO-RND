"""Load analysed LinkedIn rows that have matching vector embeddings (Step 4 corpus)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from config.paths import resolve_data_path
from config.settings import Settings, load_settings
from storage.pipeline_registry import (
    PipelineBundle,
    bundles_for_analysed_files,
    dedupe_records_by_post_id,
    join_content_to_records,
    list_bundles,
    load_posts_from_scans,
    merge_source_scans_from_bundles,
    read_artefact_meta,
)
from validation_pipeline.collect import raw_posts_to_collected
from validation_pipeline.schemas import CollectedPost

_MIN_WORD_COUNT = 10
_LINKEDIN_JSONL_GLOB = "linkedin*.jsonl"


@dataclass(frozen=True)
class VectorizedDataset:
    """One analysed JSONL/CSV bundle paired with its embedding matrix."""

    jsonl_path: Path
    csv_path: Optional[Path]
    embeddings_path: Path
    vector_count: int
    bundle_id: Optional[str] = None
    source_scans: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        csv_name = self.csv_path.name if self.csv_path else "—"
        return (
            f"{self.jsonl_path.name} + {self.embeddings_path.name} "
            f"({self.vector_count} vectors, csv={csv_name})"
        )


def _is_linkedin_processed_jsonl(path: Path) -> bool:
    name = path.name
    return (
        name.endswith(".jsonl")
        and name.startswith("linkedin")
        and "flagged" not in name
        and not name.endswith(".meta.json")
    )


def _eligible_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if (record.get("content") or "").strip()
        and int(record.get("word_count") or 0) >= _MIN_WORD_COUNT
    ]


def _dataset_from_bundle(bundle: PipelineBundle) -> Optional[VectorizedDataset]:
    if not bundle.embeddings_npy or not bundle.analysed_jsonl:
        return None
    processed_dir = resolve_data_path("data/processed")
    embeddings_dir = resolve_data_path("data/embeddings")
    jsonl_path = processed_dir / bundle.analysed_jsonl
    npy_path = embeddings_dir / bundle.embeddings_npy
    if not jsonl_path.exists() or not npy_path.exists():
        return None
    csv_path = processed_dir / bundle.analysed_csv if bundle.analysed_csv else None
    if csv_path is not None and not csv_path.exists():
        csv_path = None
    return VectorizedDataset(
        jsonl_path=jsonl_path,
        csv_path=csv_path,
        embeddings_path=npy_path,
        vector_count=int(np.load(npy_path).shape[0]),
        bundle_id=bundle.bundle_id,
        source_scans=tuple(bundle.source_scans),
    )


def _load_jsonl_records(jsonl_path: Path) -> list[dict[str, Any]]:
    """Load any linkedin*.jsonl processed artefact (legacy or analysed_*)."""
    from processors.finalize_records import is_analysed_dataset_filename, load_analysed_jsonl

    if is_analysed_dataset_filename(jsonl_path.name):
        return load_analysed_jsonl(jsonl_path)
    records = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        raise ValueError(f"{jsonl_path.name} is empty.")
    if "post_id" not in records[0]:
        raise ValueError(f"{jsonl_path.name} is missing post_id.")
    return records


def _join_jsonl_records(
    jsonl_path: Path,
    settings: Settings,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load processed JSONL and attach raw post content for eligible embedding rows."""
    records = _load_jsonl_records(jsonl_path)
    bundles = bundles_for_analysed_files([jsonl_path.name])
    source_scans = merge_source_scans_from_bundles(bundles)
    if source_scans:
        joined = join_content_to_records(
            records,
            source_scans=source_scans,
            raw_data_dir=settings.raw_data_dir,
        )
    else:
        from processors.run_pipeline import load_raw_posts

        raw_posts = load_raw_posts(settings.raw_data_dir)
        content_by_id = {
            str(post.get("id") or ""): post.get("content") or "" for post in raw_posts
        }
        joined = [
            {**record, "content": content_by_id.get(str(record.get("post_id") or ""), "")}
            for record in records
        ]
    return joined, source_scans


def _match_jsonl_to_npy(
    jsonl_path: Path,
    npy_path: Path,
    settings: Settings,
) -> Optional[VectorizedDataset]:
    """Return a dataset when eligible joined rows match the embedding row count."""
    try:
        joined, source_scans = _join_jsonl_records(jsonl_path, settings)
    except (ValueError, OSError, json.JSONDecodeError):
        return None

    eligible = _eligible_records(joined)
    vectors = np.load(npy_path)
    if len(eligible) != vectors.shape[0]:
        return None

    csv_path = jsonl_path.with_suffix(".csv")
    if not csv_path.exists():
        csv_path = None

    meta = read_artefact_meta(jsonl_path)
    bundle_id = meta.get("bundle_id") if meta else None
    return VectorizedDataset(
        jsonl_path=jsonl_path,
        csv_path=csv_path,
        embeddings_path=npy_path,
        vector_count=vectors.shape[0],
        bundle_id=bundle_id,
        source_scans=tuple(source_scans),
    )


def discover_vectorized_datasets(settings: Settings | None = None) -> list[VectorizedDataset]:
    """Find LinkedIn analysed CSV/JSONL files that have a matching .npy embedding file."""
    settings = settings or load_settings()
    discovered: dict[str, VectorizedDataset] = {}

    for bundle in list_bundles(min_stage="embedded"):
        dataset = _dataset_from_bundle(bundle)
        if dataset is not None:
            discovered[dataset.jsonl_path.name] = dataset

    processed_dir = resolve_data_path("data/processed")
    embeddings_dir = resolve_data_path("data/embeddings")
    if not embeddings_dir.exists():
        return sorted(discovered.values(), key=lambda item: item.jsonl_path.name, reverse=True)

    jsonl_files = sorted(
        (path for path in processed_dir.glob(_LINKEDIN_JSONL_GLOB) if _is_linkedin_processed_jsonl(path)),
        key=lambda path: path.name,
        reverse=True,
    )
    npy_files = sorted(embeddings_dir.glob("linkedin_gemini_*.npy"), reverse=True)

    for npy_path in npy_files:
        for jsonl_path in jsonl_files:
            if jsonl_path.name in discovered:
                continue
            dataset = _match_jsonl_to_npy(jsonl_path, npy_path, settings)
            if dataset is not None:
                discovered[jsonl_path.name] = dataset
                break

    return sorted(discovered.values(), key=lambda item: item.jsonl_path.name, reverse=True)


def _parse_posted_at(raw_post: dict[str, Any]) -> Optional[datetime]:
    ts = (raw_post.get("postedAt") or {}).get("timestamp")
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _raw_post_index(
    source_scans: list[str],
    settings: Settings,
) -> dict[str, dict[str, Any]]:
    posts: list[dict[str, Any]] = []
    if source_scans:
        posts.extend(load_posts_from_scans(source_scans, settings.raw_data_dir))
    else:
        from processors.run_pipeline import load_raw_posts

        posts.extend(load_raw_posts(settings.raw_data_dir))

    validation_dir = resolve_data_path(settings.validation_data_dir)
    if validation_dir.exists():
        for path in sorted(validation_dir.glob("collect_*.json")):
            try:
                posts.extend(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue

    index: dict[str, dict[str, Any]] = {}
    for post in posts:
        post_id = str(post.get("id") or "")
        if post_id and post_id not in index:
            index[post_id] = post
    return index


def records_to_collected_posts(
    records: list[dict[str, Any]],
    *,
    source_scans: list[str],
    settings: Settings,
) -> list[CollectedPost]:
    """Convert joined analysed rows into validation CollectedPost objects."""
    raw_by_id = _raw_post_index(source_scans, settings)
    apify_posts: list[dict[str, Any]] = []
    for record in records:
        post_id = str(record.get("post_id") or "")
        raw = raw_by_id.get(post_id)
        if raw is None:
            continue
        apify_posts.append(
            {
                **raw,
                "content": record.get("content") or raw.get("content") or "",
            }
        )
    return raw_posts_to_collected(apify_posts, settings, skip_min_age=True)


def load_collected_posts_from_vectorized_datasets(
    datasets: list[VectorizedDataset],
    settings: Settings | None = None,
    *,
    max_posts: int | None = None,
) -> tuple[list[CollectedPost], list[VectorizedDataset]]:
    """Merge vectorized analysed rows (with content) into deduped CollectedPost rows."""
    settings = settings or load_settings()
    merged_records: list[dict[str, Any]] = []
    used_datasets: list[VectorizedDataset] = []

    for dataset in datasets:
        joined, source_scans = _join_jsonl_records(dataset.jsonl_path, settings)
        eligible = _eligible_records(joined)[: dataset.vector_count]
        if len(eligible) != dataset.vector_count:
            continue
        scans = list(source_scans or dataset.source_scans)
        merged_records.extend(eligible)
        used_datasets.append(
            VectorizedDataset(
                jsonl_path=dataset.jsonl_path,
                csv_path=dataset.csv_path,
                embeddings_path=dataset.embeddings_path,
                vector_count=dataset.vector_count,
                bundle_id=dataset.bundle_id,
                source_scans=tuple(scans),
            )
        )

    merged_records = dedupe_records_by_post_id(merged_records)
    source_scans = merge_source_scans_from_bundles(
        [
            PipelineBundle(
                bundle_id=dataset.bundle_id or dataset.jsonl_path.stem,
                created_at="",
                source_scans=list(dataset.source_scans),
                analysed_jsonl=dataset.jsonl_path.name,
                analysed_csv=dataset.csv_path.name if dataset.csv_path else None,
            )
            for dataset in used_datasets
        ]
    )
    posts = records_to_collected_posts(
        merged_records,
        source_scans=source_scans,
        settings=settings,
    )
    if max_posts is not None:
        posts = posts[:max_posts]
    return posts, used_datasets


def load_all_vectorized_collected_posts(
    settings: Settings | None = None,
    *,
    max_posts: int | None = None,
) -> tuple[list[CollectedPost], list[VectorizedDataset]]:
    """Discover every vectorized LinkedIn bundle and return deduped CollectedPost rows."""
    settings = settings or load_settings()
    datasets = discover_vectorized_datasets(settings)
    return load_collected_posts_from_vectorized_datasets(
        datasets,
        settings,
        max_posts=max_posts,
    )


async def bulk_import_vectorized_and_predict_async(
    settings: Settings,
    *,
    max_posts: int | None = None,
    due_immediately: bool = False,
    skip_existing: bool = True,
):
    """Discover vectorized bundles, predict, and schedule validation."""
    from validation_pipeline.corpus_import import CorpusImportResult, predict_on_posts_async

    posts, datasets = load_all_vectorized_collected_posts(
        settings,
        max_posts=max_posts,
    )
    result = await predict_on_posts_async(
        posts,
        settings,
        due_immediately=due_immediately,
        skip_existing=skip_existing,
    )
    result.source_files = [dataset.label for dataset in datasets]
    return result


def bulk_import_vectorized_and_predict(
    settings: Settings | None = None,
    **kwargs,
):
    """Sync wrapper for dashboard and CLI vectorized bulk import."""
    import asyncio

    settings = settings or load_settings()
    return asyncio.run(
        bulk_import_vectorized_and_predict_async(
            settings,
            max_posts=kwargs.get("max_posts"),
            due_immediately=kwargs.get("due_immediately", False),
            skip_existing=kwargs.get("skip_existing", True),
        )
    )
