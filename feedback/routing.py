"""Deterministic cluster routing (no LLM).

Phase C: metadata buckets (length, format, follower band).
Phase H: optional nearest-centroid routing when embeddings exist.
Same inputs always produce the same cluster_id.
"""

from __future__ import annotations

import math
import re
from typing import Optional, Sequence


def content_length_bucket(content: str) -> str:
    words = len((content or "").split())
    if words < 50:
        return "short"
    if words < 150:
        return "medium"
    return "long"


def format_bucket(content: str) -> str:
    text = content or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    list_like = sum(
        1
        for ln in lines
        if re.match(r"^([-*•]|\d+[.)])\s+", ln)
    )
    if list_like >= 3 or (list_like >= 2 and len(lines) >= 4):
        return "list"
    if "?" in text[:240]:
        return "question"
    return "prose"


def follower_bucket(follower_count: Optional[int]) -> str:
    if follower_count is None or follower_count <= 0:
        return "unknown"
    if follower_count < 1_000:
        return "nano"
    if follower_count < 10_000:
        return "micro"
    if follower_count < 100_000:
        return "mid"
    return "macro"


def metadata_cluster_id(
    content: str,
    follower_count: Optional[int] = None,
) -> str:
    """Stable metadata bucket id (Phase C)."""
    return (
        f"{content_length_bucket(content)}_"
        f"{format_bucket(content)}_"
        f"{follower_bucket(follower_count)}"
    )


def cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Return 1 - cosine similarity (lower is closer)."""
    if not a or not b or len(a) != len(b):
        return float("inf")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        norm_a += fx * fx
        norm_b += fy * fy
    if norm_a <= 0.0 or norm_b <= 0.0:
        return float("inf")
    similarity = dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
    return 1.0 - similarity


def nearest_centroid_cluster_id(
    embedding: Sequence[float],
    centroids: Sequence[tuple[str, Sequence[float]]],
) -> Optional[str]:
    """Return cluster_id of nearest centroid, or None if empty."""
    best_id: Optional[str] = None
    best_distance = float("inf")
    for cluster_id, centroid in centroids:
        distance = cosine_distance(embedding, centroid)
        if distance < best_distance:
            best_distance = distance
            best_id = cluster_id
    return best_id


def assign_cluster_id(
    content: str,
    follower_count: Optional[int] = None,
    *,
    embedding: Optional[Sequence[float]] = None,
    centroids: Optional[Sequence[tuple[str, Sequence[float]]]] = None,
) -> str:
    """Return a stable cluster id.

    Fallback chain: nearest centroid (when embedding + centroids) → metadata bucket.
    """
    metadata_id = metadata_cluster_id(content, follower_count)
    if embedding and centroids:
        nearest = nearest_centroid_cluster_id(embedding, centroids)
        if nearest:
            return nearest
    return metadata_id


def cluster_label(cluster_id: str) -> str:
    """Human-readable label derived from the id parts."""
    parts = cluster_id.split("_")
    if len(parts) != 3:
        return cluster_id
    length, fmt, followers = parts
    return f"{length} {fmt} posts ({followers} followers)"
