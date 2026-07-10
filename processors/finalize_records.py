"""Finalize per-post feature rows into a validated, embedding-ready dataset.

The Post Analyser dashboard merges Stage 1 Python features, optional Stage 2
Gemini tags, and optional author-profile fields. Before that output can feed
Pattern Analysis or Vectorisation it still needs the batch-only steps from
``processors/benchmark.py`` (engagement percentile/z-score, anomaly flags) and
validation against ``NormalizedPost``.

Both ``dashboard/pages/2_Post_Analyser.py`` and ``processors/run_pipeline.py``
call into here so every ``linkedin_analysed_*`` artifact has the same shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from processors.benchmark import (
    add_audience_adjusted_benchmark,
    add_engagement_benchmark,
    flag_engagement_anomalies,
)
from processors.schemas import NormalizedPost

_ANALYSED_PREFIX = "linkedin_analysed_"
_ANALYSED_SUFFIX = ".jsonl"

# Streamlit profile lookup uses display-oriented keys; map into the schema.
_PROFILE_FIELD_ALIASES = {
    "author_followers": "follower_count",
}

# Not part of NormalizedPost — stripped before validation.
_PROFILE_DISPLAY_FIELDS = ("author_followers", "author_industry", "author_company")

_REQUIRED_BENCHMARK_KEYS = ("engagement_percentile", "engagement_zscore")


def is_analysed_dataset_filename(name: str) -> bool:
    """True when ``name`` is a finalized Stage-1+2 dataset (not raw/python-only)."""
    return name.startswith(_ANALYSED_PREFIX) and name.endswith(_ANALYSED_SUFFIX)


def analysed_dataset_label(with_gemini: bool) -> str:
    """Filename prefix for a processed artifact given which stages ran."""
    return "linkedin_analysed" if with_gemini else "linkedin_python"


def prepare_record_for_schema(record: dict[str, Any]) -> dict[str, Any]:
    """Map profile aliases into schema fields and drop display-only columns."""
    out = dict(record)
    for src, dst in _PROFILE_FIELD_ALIASES.items():
        if out.get(dst) is None and out.get(src) is not None:
            out[dst] = out[src]
    for key in _PROFILE_DISPLAY_FIELDS:
        out.pop(key, None)
    follower_count = out.get("follower_count")
    total = out.get("total_engagement")
    if follower_count is not None and total is not None and out.get("engagement_rate") is None:
        follower_count = int(follower_count)
        out["engagement_rate"] = round(total / follower_count, 4) if follower_count > 0 else None
    return out


def finalize_analysed_records(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply batch benchmark, optional audience adjustment, anomaly flags, validation.

    Returns ``(clean_records, flagged_records)`` — both lists contain dicts that
  pass ``NormalizedPost`` validation. Flagged posts are held out of the main
  dataset for manual review, matching ``processors/run_pipeline.py``.
    """
    if not records:
        raise ValueError("records list is empty — nothing to finalize.")

    prepared = [prepare_record_for_schema(r) for r in records]
    with_benchmark = add_engagement_benchmark(prepared)
    if any((r.get("follower_count") or 0) > 0 for r in with_benchmark):
        with_benchmark = add_audience_adjusted_benchmark(with_benchmark)
    else:
        with_benchmark = [
            {**r, "audience_adjusted_percentile": None, "audience_adjusted_zscore": None}
            for r in with_benchmark
        ]

    flagged_all = flag_engagement_anomalies(with_benchmark)
    clean = [r for r in flagged_all if not r["engagement_anomaly_flag"]]
    flagged = [r for r in flagged_all if r["engagement_anomaly_flag"]]

    validated_clean = [NormalizedPost.model_validate(r).model_dump() for r in clean]
    validated_flagged = [NormalizedPost.model_validate(r).model_dump() for r in flagged]
    return validated_clean, validated_flagged


def validate_analysed_records(records: list[dict[str, Any]]) -> None:
    """Raise ValueError when records are not a finalized analysed dataset."""
    if not records:
        raise ValueError("Dataset is empty.")
    sample = records[0]
    missing = [key for key in _REQUIRED_BENCHMARK_KEYS if key not in sample]
    if missing:
        raise ValueError(
            "This dataset is missing batch benchmark fields "
            f"({', '.join(missing)}). Re-run Post Analyser (Stage 1 + 2) so "
            "engagement scores are computed before Pattern Analysis."
        )
    for record in records:
        NormalizedPost.model_validate(record)


def load_analysed_jsonl(path: Path | str) -> list[dict[str, Any]]:
    """Load a ``linkedin_analysed_*.jsonl`` file and validate its records."""
    resolved = Path(path)
    if not is_analysed_dataset_filename(resolved.name):
        raise ValueError(
            f"Expected a `{_ANALYSED_PREFIX}*{_ANALYSED_SUFFIX}` file, got `{resolved.name}`."
        )
    records = [
        json.loads(line)
        for line in resolved.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    validate_analysed_records(records)
    return records


def list_analysed_datasets(processed_dir: Path | str) -> list[Path]:
    """Return analysed JSONL files under ``processed_dir``, newest first."""
    root = Path(processed_dir)
    if not root.exists():
        return []
    return sorted(
        (p for p in root.glob(f"{_ANALYSED_PREFIX}*{_ANALYSED_SUFFIX}")),
        key=lambda p: p.name,
        reverse=True,
    )
