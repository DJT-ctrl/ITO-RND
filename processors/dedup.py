"""Removes exact-duplicate posts (identical content) from a raw post batch.

Why this matters
-----------------
The same post occasionally gets scraped twice under different LinkedIn
post IDs (e.g. a genuine repost, or an artifact of overlapping scrape
windows — see repo memory: 290 raw posts but only 250 unique post_id
values). Left in, duplicate content:
  - inflates whichever engagement bucket that content happens to fall in,
    skewing processors/benchmark.py's percentile/z-score AND the anomaly-
    detection MAD baseline (add_engagement_benchmark / flag_engagement_
    anomalies) since the same text is counted multiple times,
  - wastes an embedding call and a retrieval-corpus slot on content that
    adds no new semantic information.

This module only removes EXACT matches (identical content string after
whitespace trimming) — no fuzzy/near-duplicate detection. It must run
before Stage 1 features / the benchmark step (see
processors/run_pipeline.py), since both are indexed 1:1 off the raw post
list.
"""

from typing import Any


def dedupe_posts(raw_posts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Return (deduped_posts, num_removed).

    Posts with blank/whitespace-only content are never deduped against each
    other — there's nothing meaningful to compare, and the existing
    word_count >= 10 filter downstream already drops those separately.

    When two or more posts share identical (trimmed) content, the one with
    the highest raw engagement (likes + comments + shares) is kept as the
    representative — treated as the best real-world outcome for that exact
    content. Ties keep whichever appeared first in the input list.
    """
    if not raw_posts:
        return [], 0

    # First pass: for each distinct non-blank content string, find the
    # index of the post with the highest raw engagement.
    best_index_by_content: dict[str, int] = {}
    best_score_by_content: dict[str, int] = {}
    for index, post in enumerate(raw_posts):
        content = (post.get("content") or "").strip()
        if not content:
            continue
        engagement = post.get("engagement") or {}
        score = (
            int(engagement.get("likes") or 0)
            + int(engagement.get("comments") or 0)
            + int(engagement.get("shares") or 0)
        )
        if content not in best_score_by_content or score > best_score_by_content[content]:
            best_score_by_content[content] = score
            best_index_by_content[content] = index

    # Second pass: preserve original order, keeping only the winning index
    # for each duplicated content string (and every blank-content post).
    kept: list[dict[str, Any]] = []
    for index, post in enumerate(raw_posts):
        content = (post.get("content") or "").strip()
        if not content or best_index_by_content[content] == index:
            kept.append(post)

    return kept, len(raw_posts) - len(kept)
