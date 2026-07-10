"""Pipeline bundle registry — tracks dataset lineage from scrape through ingest.

Each *bundle* groups every artefact produced from one logical pipeline run
(or a deliberate merge of several scraper collections into one analysis).
Downstream steps only accept inputs that are registered here and whose
parent bundle(s) completed the required prior stage.

Manifest path: ``data/pipeline_manifest.json``
Sidecar meta:   ``<artefact>.meta.json`` next to analysed JSONL / embedding NPY
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from config.paths import resolve_data_path, utc_artifact_stamp

ManifestStage = Literal["scraped", "analysed", "embedded", "ingested"]

_MANIFEST_PATH = resolve_data_path("data/pipeline_manifest.json")
_RAW_DIR = resolve_data_path("data/raw")
_PROCESSED_DIR = resolve_data_path("data/processed")
_EMBEDDINGS_DIR = resolve_data_path("data/embeddings")


@dataclass
class PipelineBundle:
    """One grouped pipeline run from scraper collection through optional ingest."""

    bundle_id: str
    created_at: str
    source_scans: list[str] = field(default_factory=list)
    source_profiles: list[str] = field(default_factory=list)
    enriched_csv: Optional[str] = None
    analysed_jsonl: Optional[str] = None
    analysed_csv: Optional[str] = None
    flagged_jsonl: Optional[str] = None
    with_gemini: bool = False
    post_count: Optional[int] = None
    embeddings_npy: Optional[str] = None
    embedding_post_ids: list[str] = field(default_factory=list)
    ingested_at: Optional[str] = None
    ingested_count: Optional[int] = None

    def stage(self) -> ManifestStage:
        if self.ingested_at and self.ingested_count:
            return "ingested"
        if self.embeddings_npy:
            return "embedded"
        if self.analysed_jsonl:
            return "analysed"
        return "scraped"

    def label(self) -> str:
        scans = ", ".join(self.source_scans) if self.source_scans else "unknown source"
        return f"{self.bundle_id} — {scans} ({self.post_count or '?'} posts, {self.stage()})"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_manifest() -> dict[str, Any]:
    if not _MANIFEST_PATH.exists():
        return {"bundles": []}
    try:
        return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"bundles": []}


def _save_manifest(data: dict[str, Any]) -> None:
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MANIFEST_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _bundle_from_dict(raw: dict[str, Any]) -> PipelineBundle:
    return PipelineBundle(
        bundle_id=raw["bundle_id"],
        created_at=raw.get("created_at", ""),
        source_scans=list(raw.get("source_scans") or []),
        source_profiles=list(raw.get("source_profiles") or []),
        enriched_csv=raw.get("enriched_csv"),
        analysed_jsonl=raw.get("analysed_jsonl"),
        analysed_csv=raw.get("analysed_csv"),
        flagged_jsonl=raw.get("flagged_jsonl"),
        with_gemini=bool(raw.get("with_gemini")),
        post_count=raw.get("post_count"),
        embeddings_npy=raw.get("embeddings_npy"),
        embedding_post_ids=list(raw.get("embedding_post_ids") or []),
        ingested_at=raw.get("ingested_at"),
        ingested_count=raw.get("ingested_count"),
    )


def list_bundles(
    *,
    min_stage: Optional[ManifestStage] = None,
    require_gemini: bool = False,
) -> list[PipelineBundle]:
    """Return bundles newest-first, optionally filtered by minimum completed stage."""
    stage_order = {"scraped": 0, "analysed": 1, "embedded": 2, "ingested": 3}
    bundles = [_bundle_from_dict(b) for b in _load_manifest().get("bundles", [])]
    bundles.sort(key=lambda b: b.bundle_id, reverse=True)
    if require_gemini:
        bundles = [b for b in bundles if b.with_gemini]
    if min_stage is None:
        return bundles
    threshold = stage_order[min_stage]
    return [b for b in bundles if stage_order[b.stage()] >= threshold]


def get_bundle(bundle_id: str) -> Optional[PipelineBundle]:
    for bundle in list_bundles():
        if bundle.bundle_id == bundle_id:
            return bundle
    return None


def _upsert_bundle(bundle: PipelineBundle) -> PipelineBundle:
    data = _load_manifest()
    bundles = [_bundle_from_dict(b) for b in data.get("bundles", [])]
    replaced = False
    for index, existing in enumerate(bundles):
        if existing.bundle_id == bundle.bundle_id:
            bundles[index] = bundle
            replaced = True
            break
    if not replaced:
        bundles.append(bundle)
    bundles.sort(key=lambda b: b.bundle_id, reverse=True)
    data["bundles"] = [asdict(b) for b in bundles]
    _save_manifest(data)
    return bundle


def _basename(path: str | Path) -> str:
    return Path(path).name


def write_artefact_meta(artefact_path: Path | str, meta: dict[str, Any]) -> Path:
    """Persist a sidecar ``.meta.json`` beside an artefact file."""
    resolved = Path(artefact_path)
    meta_path = resolved.with_suffix(resolved.suffix + ".meta.json")
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta_path


def read_artefact_meta(artefact_path: Path | str) -> Optional[dict[str, Any]]:
    resolved = Path(artefact_path)
    meta_path = resolved.with_suffix(resolved.suffix + ".meta.json")
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def register_scrape_bundle(
    *,
    bundle_id: Optional[str] = None,
    source_scans: list[str],
    source_profiles: Optional[list[str]] = None,
    enriched_csv: Optional[str] = None,
    post_count: Optional[int] = None,
) -> PipelineBundle:
    """Register Step 1 output (new collection or explicit scrape paths)."""
    bundle = PipelineBundle(
        bundle_id=bundle_id or utc_artifact_stamp(),
        created_at=_now_iso(),
        source_scans=[_basename(p) for p in source_scans],
        source_profiles=[_basename(p) for p in (source_profiles or [])],
        enriched_csv=_basename(enriched_csv) if enriched_csv else None,
        post_count=post_count,
    )
    return _upsert_bundle(bundle)


def register_analysed_bundle(
    *,
    bundle_id: Optional[str] = None,
    source_scans: list[str],
    source_profiles: Optional[list[str]] = None,
    analysed_jsonl: str,
    analysed_csv: str,
    flagged_jsonl: Optional[str] = None,
    with_gemini: bool = True,
    post_count: int,
) -> PipelineBundle:
    """Register Step 2 output and link it to its scraper source(s)."""
    bid = bundle_id or utc_artifact_stamp()
    scans = [_basename(p) for p in source_scans]
    profiles = [_basename(p) for p in (source_profiles or [])]
    jsonl_name = _basename(analysed_jsonl)
    csv_name = _basename(analysed_csv)
    flagged_name = _basename(flagged_jsonl) if flagged_jsonl else None

    existing = get_bundle(bid)
    bundle = PipelineBundle(
        bundle_id=bid,
        created_at=existing.created_at if existing else _now_iso(),
        source_scans=scans,
        source_profiles=profiles,
        enriched_csv=existing.enriched_csv if existing else None,
        analysed_jsonl=jsonl_name,
        analysed_csv=csv_name,
        flagged_jsonl=flagged_name,
        with_gemini=with_gemini,
        post_count=post_count,
        embeddings_npy=existing.embeddings_npy if existing else None,
        embedding_post_ids=existing.embedding_post_ids if existing else [],
        ingested_at=existing.ingested_at if existing else None,
        ingested_count=existing.ingested_count if existing else None,
    )
    _upsert_bundle(bundle)
    write_artefact_meta(
        _PROCESSED_DIR / jsonl_name,
        {
            "bundle_id": bid,
            "source_scans": scans,
            "source_profiles": profiles,
            "with_gemini": with_gemini,
            "post_count": post_count,
        },
    )
    return bundle


def register_embeddings_bundle(
    *,
    bundle_id: str,
    embeddings_npy: str,
    embedding_post_ids: list[str],
    source_jsonl: str,
) -> PipelineBundle:
    """Register Step 4 output on an existing analysed bundle."""
    bundle = get_bundle(bundle_id)
    if bundle is None:
        raise ValueError(f"Unknown bundle_id `{bundle_id}` — register analysis first.")

    npy_path = Path(embeddings_npy)
    npy_name = npy_path.name
    bundle.embeddings_npy = npy_name
    bundle.embedding_post_ids = list(embedding_post_ids)
    _upsert_bundle(bundle)
    write_artefact_meta(
        npy_path,
        {
            "bundle_id": bundle_id,
            "source_jsonl": _basename(source_jsonl),
            "source_scans": bundle.source_scans,
            "embedding_post_ids": embedding_post_ids,
        },
    )
    return bundle


def register_ingest_bundle(*, bundle_id: str, ingested_count: int) -> PipelineBundle:
    """Mark a bundle as loaded into Postgres (Step 5+ retrieval corpus)."""
    bundle = get_bundle(bundle_id)
    if bundle is None:
        raise ValueError(f"Unknown bundle_id `{bundle_id}`.")

    bundle.ingested_at = _now_iso()
    bundle.ingested_count = ingested_count
    return _upsert_bundle(bundle)


def bundles_for_analysed_files(filenames: list[str]) -> list[PipelineBundle]:
    """Resolve registry bundles that own the given analysed JSONL filenames."""
    names = {_basename(f) for f in filenames}
    matched = [b for b in list_bundles(min_stage="analysed") if b.analysed_jsonl in names]
    if matched:
        return matched
    # Legacy files without registry entries — synthesize minimal bundles from sidecar meta.
    legacy: list[PipelineBundle] = []
    for name in sorted(names):
        meta = read_artefact_meta(_PROCESSED_DIR / name)
        if meta:
            legacy.append(
                PipelineBundle(
                    bundle_id=meta.get("bundle_id", name),
                    created_at=_now_iso(),
                    source_scans=list(meta.get("source_scans") or []),
                    source_profiles=list(meta.get("source_profiles") or []),
                    analysed_jsonl=name,
                    with_gemini=bool(meta.get("with_gemini", True)),
                    post_count=meta.get("post_count"),
                )
            )
    return legacy


def load_posts_from_scans(
    scan_filenames: list[str],
    raw_data_dir: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Load and concatenate posts from specific scraper JSON files only."""
    raw_dir = resolve_data_path(raw_data_dir or "data/raw")
    posts: list[dict[str, Any]] = []
    for name in scan_filenames:
        path = raw_dir / _basename(name)
        if path.exists():
            posts.extend(json.loads(path.read_text(encoding="utf-8")))
    return posts


def merge_source_scans_from_bundles(bundles: list[PipelineBundle]) -> list[str]:
    """Union of source scan filenames across bundles, preserving order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for bundle in bundles:
        for scan in bundle.source_scans:
            if scan not in seen:
                seen.add(scan)
                ordered.append(scan)
    return ordered


def dedupe_records_by_post_id(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first occurrence of each post_id when merging bundles."""
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for record in records:
        post_id = record.get("post_id") or ""
        if post_id in seen:
            continue
        seen.add(post_id)
        kept.append(record)
    return kept


def join_content_to_records(
    records: list[dict[str, Any]],
    *,
    source_scans: list[str],
    raw_data_dir: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Re-attach raw post text scoped to the bundle's source scraper file(s)."""
    raw_posts = load_posts_from_scans(source_scans, raw_data_dir=raw_data_dir)
    content_by_id = {post.get("id") or "": post.get("content") or "" for post in raw_posts}
    return [{**record, "content": content_by_id.get(record["post_id"], "")} for record in records]


def load_merged_analysed_records(
    analysed_filenames: list[str],
    *,
    processed_dir: Optional[str] = None,
) -> tuple[list[dict[str, Any]], list[PipelineBundle]]:
    """Load one or more analysed JSONL files and merge by post_id."""
    from processors.finalize_records import load_analysed_jsonl

    root = resolve_data_path(processed_dir or "data/processed")
    bundles = bundles_for_analysed_files(analysed_filenames)
    merged: list[dict[str, Any]] = []
    for name in analysed_filenames:
        merged.extend(load_analysed_jsonl(root / name))
    return dedupe_records_by_post_id(merged), bundles
