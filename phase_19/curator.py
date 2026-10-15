"""Deduplicate, quality-filter, and tag Phase 19 evidence candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_MIN_CONTENT_CHARS = 40


@dataclass(frozen=True)
class CuratedCandidate:
    post_id: str | None
    source_url: str | None
    source_type: str
    content_preview: str
    author_key: str
    quality_score: float
    decision: str  # accepted | rejected
    rejection_reason: str | None
    raw: dict[str, Any]


def _post_id(post: dict[str, Any]) -> str | None:
    value = post.get("id") or post.get("post_id") or post.get("urn")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _content(post: dict[str, Any]) -> str:
    for key in ("content", "text", "commentary", "postText"):
        value = post.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _author_key(post: dict[str, Any]) -> str:
    author = post.get("author") or {}
    if isinstance(author, dict):
        for key in ("publicIdentifier", "linkedinUrl", "name", "id"):
            value = author.get(key)
            if value:
                return str(value).strip()
    for key in ("author_public_id", "author_name", "author"):
        value = post.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _source_url(post: dict[str, Any]) -> str | None:
    for key in ("linkedinUrl", "url", "postUrl", "source_url"):
        value = post.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def curate_candidates(
    posts: list[dict[str, Any]],
    *,
    source_type: str,
    known_post_ids: set[str],
    max_accept: int | None = None,
) -> list[CuratedCandidate]:
    """Reject duplicates and low-content rows; cap accepts when requested."""
    seen: set[str] = set(known_post_ids)
    accepted = 0
    results: list[CuratedCandidate] = []

    for post in posts:
        pid = _post_id(post)
        content = _content(post)
        author = _author_key(post)
        url = _source_url(post)
        decision = "accepted"
        reason: str | None = None
        quality = min(1.0, len(content) / 280.0) if content else 0.0

        if not content or len(content) < _MIN_CONTENT_CHARS:
            decision = "rejected"
            reason = "low_content"
        elif pid and pid in seen:
            decision = "rejected"
            reason = "duplicate"
        elif max_accept is not None and accepted >= max_accept:
            decision = "rejected"
            reason = "candidate_cap"

        if decision == "accepted":
            accepted += 1
            if pid:
                seen.add(pid)

        results.append(
            CuratedCandidate(
                post_id=pid,
                source_url=url,
                source_type=source_type,
                content_preview=content[:280],
                author_key=author,
                quality_score=round(quality, 3),
                decision=decision,
                rejection_reason=reason,
                raw=post,
            )
        )
    return results
