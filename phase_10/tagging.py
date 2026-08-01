"""Attach coarse ``niche`` from free-text ``topic`` (T10.6)."""

from __future__ import annotations

from typing import Any

from phase_10.topics import DEFAULT_NICHE, normalize_topic_to_niche


def apply_niche(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``record`` with ``niche`` set from ``topic`` when needed.

    Unmatched free-text topics land in the catch-all ``niche="other"`` while
    preserving the original ``topic`` string so finer tags can be activated
    later (expand taxonomy + re-normalize) without re-analysing posts.
    Only blank/missing topics are filled with ``"other"``.
    """
    out = dict(record)
    raw_topic = out.get("topic") if isinstance(out.get("topic"), str) else None
    existing = out.get("niche")
    if isinstance(existing, str) and existing.strip():
        out["niche"] = normalize_topic_to_niche(existing)
    else:
        out["niche"] = normalize_topic_to_niche(raw_topic)
    if out["niche"] == DEFAULT_NICHE:
        topic_text = " ".join(str(raw_topic or "").strip().split())
        out["topic"] = topic_text or DEFAULT_NICHE
    return out
