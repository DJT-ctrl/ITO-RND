"""Finalize per-post feature rows into a validated, embedding-ready dataset.

The Post Analyser dashboard merges Stage 1 Python features, optional Stage 2
Gemini tags, and optional author-profile fields. Before that output can feed
Pattern Analysis or Vectorisation it still needs the batch-only steps from
``processors/benchmark.py`` (engagement percentile/z-score, anomaly flags) and
validation against ``NormalizedPost``.

Both the dashboard-for-devs Post Analyser page and ``processors/run_pipeline.py``
call into here so every ``linkedin_analysed_*`` artifact has the same shape.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, get_args

from pydantic import ValidationError

from processors.benchmark import (
    add_audience_adjusted_benchmark,
    add_engagement_benchmark,
    flag_engagement_anomalies,
)
from processors.schemas import HookType, NormalizedPost, Tone
from phase_10.tagging import apply_niche

logger = logging.getLogger(__name__)

_ANALYSED_PREFIX = "linkedin_analysed_"
_PYTHON_PREFIX = "linkedin_python_"
_ANALYSED_SUFFIX = ".jsonl"

# Streamlit profile lookup uses display-oriented keys; map into the schema.
_PROFILE_FIELD_ALIASES = {
    "author_followers": "follower_count",
}

# Not part of NormalizedPost — stripped before validation.
_PROFILE_DISPLAY_FIELDS = ("author_followers", "author_industry", "author_company")

_REQUIRED_BENCHMARK_KEYS = ("engagement_percentile", "engagement_zscore")

_HOOK_TYPES = frozenset(get_args(HookType))
_TONES = frozenset(get_args(Tone))

# Common Gemini near-misses → closest allowed label (else coerced to None).
_HOOK_TYPE_ALIASES = {
    "curiosity": "other",
    "curious": "other",
    "clickbait": "other",
    "quote": "other",
    "quotation": "other",
    "quoted": "other",
    "how_to": "list",
    "howto": "list",
    "how-to": "list",
    "tip": "list",
    "tips": "list",
    "listicle": "list",
    "storytelling": "story",
    "narrative": "story",
    "personal_story": "story",
    "bold": "bold_statement",
    "statement": "bold_statement",
    "hot_take": "bold_statement",
    "opinion": "bold_statement",
    "cta": "announcement",
    "news": "announcement",
    "update": "announcement",
    "promo": "announcement",
    "promotion": "announcement",
}
_TONE_ALIASES = {
    "inspirational": "emotional",
    "inspiring": "emotional",
    "motivational": "emotional",
    "empathetic": "emotional",
    "friendly": "casual",
    "informal": "casual",
    "formal": "professional",
    "serious": "professional",
    "funny": "humorous",
    "witty": "humorous",
    "sarcastic": "humorous",
    "urgent_call": "urgent",
    "exciting": "urgent",
}


def is_analysed_dataset_filename(name: str) -> bool:
    """True when ``name`` is a finalized Stage-1+2 (Gemini) dataset."""
    return name.startswith(_ANALYSED_PREFIX) and name.endswith(_ANALYSED_SUFFIX)


def is_finalized_dataset_filename(name: str) -> bool:
    """True for Stage-1-only or Stage-1+2 finalized JSONL (embedding-ready)."""
    if not name.endswith(_ANALYSED_SUFFIX):
        return False
    return name.startswith(_ANALYSED_PREFIX) or name.startswith(_PYTHON_PREFIX)


def analysed_dataset_label(with_gemini: bool) -> str:
    """Filename prefix for a processed artifact given which stages ran."""
    return "linkedin_analysed" if with_gemini else "linkedin_python"


def _normalize_label(value: Any) -> Optional[str]:
    """Lowercase slug for enum / detail comparison (spaces/hyphens → underscores)."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.lower().replace(" ", "_").replace("-", "_")


def _coerce_enum(
    value: Any,
    allowed: frozenset[str],
    aliases: dict[str, str],
    *,
    unknown_default: Optional[str] = None,
) -> Optional[str]:
    key = _normalize_label(value)
    if key is None:
        return None
    if key in allowed:
        return key
    mapped = aliases.get(key)
    if mapped in allowed:
        return mapped
    if unknown_default in allowed:
        return unknown_default
    return None


def _coerce_hook_type(
    value: Any,
    *,
    existing_detail: Any = None,
) -> tuple[Optional[str], Optional[str]]:
    """Return ``(canonical_hook_type, hook_type_detail)``.

    When the input is not a first-class HookType and lands in ``other``
    (via alias or unknown_default), preserve the original slug in detail so
    we can promote it later. Known buckets (including Gemini returning
    ``other`` itself) keep detail clear unless an existing detail is already
    present on a re-sanitize of an ``other`` row.
    """
    key = _normalize_label(value)
    if key is None:
        return None, None
    if key in _HOOK_TYPES:
        if key == "other":
            detail = _normalize_label(existing_detail)
            return "other", detail
        return key, None
    mapped = _HOOK_TYPE_ALIASES.get(key)
    if mapped in _HOOK_TYPES:
        return mapped, (key if mapped == "other" else None)
    if "other" in _HOOK_TYPES:
        return "other", key
    return None, None


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0"):
            return False
    return None


def sanitize_gemini_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Coerce Gemini enums/bools so one odd label cannot kill a whole batch save.

    Near-miss / unknown ``hook_type`` values become ``other`` for bucketing,
    with the original slug kept in ``hook_type_detail`` (e.g. quote → other).
    """
    out = dict(record)
    if "hook_type" in out or out.get("hook_type") is not None or out.get("hook_type_detail") is not None:
        canonical, detail = _coerce_hook_type(
            out.get("hook_type"),
            existing_detail=out.get("hook_type_detail"),
        )
        out["hook_type"] = canonical
        out["hook_type_detail"] = detail
    if "tone" in out or out.get("tone") is not None:
        out["tone"] = _coerce_enum(out.get("tone"), _TONES, _TONE_ALIASES)
    if "has_explicit_cta" in out:
        out["has_explicit_cta"] = _coerce_optional_bool(out.get("has_explicit_cta"))
    topic = out.get("topic")
    if topic is not None and not isinstance(topic, str):
        out["topic"] = str(topic)
    writing_style = out.get("writing_style")
    if writing_style is not None and not isinstance(writing_style, str):
        out["writing_style"] = str(writing_style)
    return out


def prepare_record_for_schema(record: dict[str, Any]) -> dict[str, Any]:
    """Map profile aliases into schema fields and drop display-only columns."""
    out = sanitize_gemini_fields(record)
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
    return apply_niche(out)


def _validate_records(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate each record; skip + log individuals that still fail."""
    validated: list[dict[str, Any]] = []
    errors: list[str] = []
    for record in records:
        try:
            validated.append(NormalizedPost.model_validate(record).model_dump())
        except ValidationError as exc:
            post_id = record.get("post_id") or "?"
            msg = f"post_id={post_id}: {exc.error_count()} validation error(s)"
            errors.append(msg)
            logger.warning("Skipping invalid analysed record %s — %s", post_id, exc)
    return validated, errors


def finalize_analysed_records(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply batch benchmark, optional audience adjustment, anomaly flags, validation.

    Returns ``(clean_records, flagged_records)`` — both lists contain dicts that
    pass ``NormalizedPost`` validation. Flagged posts are held out of the main
    dataset for manual review, matching ``processors/run_pipeline.py``.

    Invalid Gemini enum labels are coerced first. Any record that still fails
    schema validation is skipped (logged) instead of aborting the whole batch.
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

    validated_clean, clean_errors = _validate_records(clean)
    validated_flagged, flagged_errors = _validate_records(flagged)
    skipped = len(clean_errors) + len(flagged_errors)
    if skipped:
        logger.warning(
            "finalize_analysed_records skipped %s invalid record(s) "
            "(%s clean-side, %s flagged-side)",
            skipped,
            len(clean_errors),
            len(flagged_errors),
        )
    if not validated_clean and not validated_flagged:
        raise ValueError(
            "No records passed NormalizedPost validation after finalize. "
            f"First errors: {'; '.join((clean_errors + flagged_errors)[:3])}"
        )
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


def _load_validated_jsonl(path: Path) -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    validate_analysed_records(records)
    return records


def load_analysed_jsonl(path: Path | str) -> list[dict[str, Any]]:
    """Load a ``linkedin_analysed_*.jsonl`` file and validate its records."""
    resolved = Path(path)
    if not is_analysed_dataset_filename(resolved.name):
        raise ValueError(
            f"Expected a `{_ANALYSED_PREFIX}*{_ANALYSED_SUFFIX}` file, got `{resolved.name}`."
        )
    return _load_validated_jsonl(resolved)


def load_finalized_jsonl(path: Path | str) -> list[dict[str, Any]]:
    """Load Stage-1 or Stage-1+2 finalized JSONL (``linkedin_python_*`` / ``linkedin_analysed_*``).

    Used by agentic corpus refresh, which may run with or without Gemini.
    """
    resolved = Path(path)
    if not is_finalized_dataset_filename(resolved.name):
        raise ValueError(
            f"Expected a finalized `linkedin_analysed_*` or `linkedin_python_*` "
            f"jsonl file, got `{resolved.name}`."
        )
    return _load_validated_jsonl(resolved)


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
