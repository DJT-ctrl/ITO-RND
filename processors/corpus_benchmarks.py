"""Cached corpus benchmark snapshot for Tier 1 discoverability (T6 Point 2).

Builds a small JSON summary from posts in the database (or from pipeline
records) using deterministic statistics in processors/pattern_analysis.py.
The SEO agent receives a human-readable rendering of this snapshot — never
the raw post rows.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import psycopg

from config.settings import Settings
from processors.pattern_analysis import correlate_numeric_features, group_engagement_by_tag
from storage.vector_store import fetch_posts_for_analysis, get_connection

DEFAULT_SNAPSHOT_PATH = Path("data/processed/corpus_benchmarks.json")
DEFAULT_TTL_HOURS = 24


def build_snapshot(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive a compact benchmark summary from normalized post records."""
    if not records:
        raise ValueError("records list is empty — nothing to benchmark.")

    df = pd.DataFrame.from_records(records)
    target = _resolve_target(df)

    top_quartile = df[df["engagement_percentile"] >= 75] if "engagement_percentile" in df.columns else df
    if top_quartile.empty:
        top_quartile = df

    hashtag_median = float(top_quartile["hashtag_count"].median()) if "hashtag_count" in top_quartile else 2.0
    word_median = float(top_quartile["word_count"].median()) if "word_count" in top_quartile else 250.0

    hashtag_lo = max(0, int(round(hashtag_median - 1)))
    hashtag_hi = max(hashtag_lo, int(round(hashtag_median + 1)))

    word_lo = max(50, int(round(word_median * 0.7)))
    word_hi = max(word_lo, int(round(word_median * 1.3)))

    correlations: dict[str, float] = {}
    try:
        corr = correlate_numeric_features(records)
        for key in ("hashtag_count", "word_count", "emoji_count", "has_explicit_cta"):
            if key in corr.index and pd.notna(corr[key]):
                correlations[key] = round(float(corr[key]), 3)
    except ValueError:
        pass

    top_topics: list[dict[str, Any]] = []
    try:
        grouped = group_engagement_by_tag(records)
        if "topic" in grouped:
            topic_df = grouped["topic"].head(5)
            for topic, row in topic_df.iterrows():
                top_topics.append(
                    {
                        "topic": str(topic),
                        "mean_zscore": round(float(row["mean"]), 2),
                        "count": int(row["count"]),
                    }
                )
    except ValueError:
        pass

    uses_audience_adjusted = bool(
        "audience_adjusted_zscore" in df.columns and df["audience_adjusted_zscore"].notna().any()
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_size": len(records),
        "target_metric": target,
        "uses_audience_adjusted": uses_audience_adjusted,
        "optimal_hashtag_range": [hashtag_lo, hashtag_hi],
        "optimal_word_count_range": [word_lo, word_hi],
        "high_performer_median_hashtags": round(hashtag_median, 1),
        "high_performer_median_words": round(word_median, 1),
        "correlations": correlations,
        "top_topics": top_topics,
    }


def save_snapshot(snapshot: dict[str, Any], path: Optional[Path] = None) -> Path:
    resolved = path or DEFAULT_SNAPSHOT_PATH
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved


def load_snapshot(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    resolved = path or DEFAULT_SNAPSHOT_PATH
    if not resolved.exists():
        return None
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def is_stale(path: Optional[Path] = None, ttl_hours: int = DEFAULT_TTL_HOURS) -> bool:
    resolved = path or DEFAULT_SNAPSHOT_PATH
    snapshot = load_snapshot(resolved)
    if snapshot is None:
        return True
    generated_at = snapshot.get("generated_at")
    if not generated_at:
        return True
    try:
        created = datetime.fromisoformat(generated_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
        return age_hours >= ttl_hours
    except ValueError:
        return True


def refresh_snapshot_from_db(
    settings: Settings,
    limit: int = 500,
    path: Optional[Path] = None,
) -> dict[str, Any]:
    """Rebuild the benchmark snapshot from the database."""
    resolved = path or DEFAULT_SNAPSHOT_PATH
    conn = get_connection(settings)
    try:
        records = fetch_posts_for_analysis(conn, limit=limit)
    finally:
        conn.close()

    if not records:
        raise ValueError("No posts in database — cannot build corpus benchmarks.")

    snapshot = build_snapshot(records)
    save_snapshot(snapshot, resolved)
    return snapshot


def get_or_refresh_benchmarks(
    settings: Settings,
    *,
    force: bool = False,
    path: Optional[Path] = None,
    ttl_hours: Optional[int] = None,
) -> tuple[Optional[dict[str, Any]], list[str]]:
    """Load cached benchmarks or refresh from DB when stale.

    Returns (snapshot, warnings). Snapshot is None when refresh cannot produce
    data and no usable cache file exists (empty DB, missing DATABASE_URL, or
    DB/network outage). Never raises on connectivity failures — callers get a
    warning and may continue evaluation without corpus benchmarks.
    """
    resolved_path = path or DEFAULT_SNAPSHOT_PATH
    warnings: list[str] = []
    ttl = ttl_hours if ttl_hours is not None else settings.corpus_benchmark_ttl_hours

    if not force and not is_stale(resolved_path, ttl_hours=ttl):
        cached = load_snapshot(resolved_path)
        if cached is not None:
            return cached, warnings

    if not settings.database_url:
        cached = load_snapshot(resolved_path)
        if cached is not None:
            warnings.append("DATABASE_URL not set — using stale corpus benchmark cache.")
            return cached, warnings
        warnings.append("DATABASE_URL not set and no corpus benchmark cache found.")
        return None, warnings

    try:
        return refresh_snapshot_from_db(settings, path=resolved_path), warnings
    except (ValueError, psycopg.Error, OSError, TimeoutError) as exc:
        cached = load_snapshot(resolved_path)
        if cached is not None:
            warnings.append(f"{exc} — using stale corpus benchmark cache.")
            return cached, warnings
        warnings.append(str(exc))
        return None, warnings


def format_snapshot_for_prompt(snapshot: dict[str, Any]) -> str:
    """Render a benchmark snapshot as compact prompt text."""
    lines = [
        f"- Corpus size: {snapshot.get('sample_size', 'unknown')} posts",
        f"- Ranking metric: {snapshot.get('target_metric', 'engagement_zscore')}",
    ]
    if snapshot.get("uses_audience_adjusted"):
        lines.append("- Audience-adjusted engagement scores are in use (follower-normalized).")

    lo, hi = snapshot.get("optimal_hashtag_range", [1, 3])
    w_lo, w_hi = snapshot.get("optimal_word_count_range", [150, 350])
    lines.append(f"- High-performer hashtag sweet spot: {lo}-{hi} tags")
    lines.append(f"- High-performer word-count sweet spot: {w_lo}-{w_hi} words")

    correlations = snapshot.get("correlations") or {}
    for key, value in correlations.items():
        direction = "positively" if value > 0 else "negatively"
        lines.append(f"- {key} {direction} correlates with engagement ({value:+.2f})")

    top_topics = snapshot.get("top_topics") or []
    if top_topics:
        topic_bits = [
            f'"{t["topic"]}" (mean zscore {t["mean_zscore"]:+.2f}, n={t["count"]})'
            for t in top_topics[:5]
        ]
        lines.append("- Top topics by engagement: " + "; ".join(topic_bits))

    return "\n".join(lines)


def corpus_norms_from_snapshot(snapshot: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Extract numeric norms for deterministic draft checks."""
    if snapshot is None:
        return {}
    hashtag_range = snapshot.get("optimal_hashtag_range") or [1, 3]
    word_range = snapshot.get("optimal_word_count_range") or [150, 350]
    return {
        "optimal_hashtag_range": tuple(hashtag_range),
        "optimal_word_count_range": tuple(word_range),
    }


def _resolve_target(df: pd.DataFrame) -> str:
    if "audience_adjusted_zscore" in df.columns and df["audience_adjusted_zscore"].notna().any():
        return "audience_adjusted_zscore"
    return "engagement_zscore"
