"""Deterministic cluster routing (no LLM).

Phase C starts with metadata buckets (length, format, follower band).
Same inputs always produce the same cluster_id. Embedding centroids can be
added later without changing the assign_cluster_id contract for callers.
"""

from __future__ import annotations

import re
from typing import Optional


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


def assign_cluster_id(
    content: str,
    follower_count: Optional[int] = None,
) -> str:
    """Return a stable cluster id from content (+ optional follower count)."""
    return (
        f"{content_length_bucket(content)}_"
        f"{format_bucket(content)}_"
        f"{follower_bucket(follower_count)}"
    )


def cluster_label(cluster_id: str) -> str:
    """Human-readable label derived from the id parts."""
    parts = cluster_id.split("_")
    if len(parts) != 3:
        return cluster_id
    length, fmt, followers = parts
    return f"{length} {fmt} posts ({followers} followers)"
