"""Attach coarse ``niche`` from free-text ``topic`` (T10.6)."""

from __future__ import annotations

from typing import Any

from phase_10.topics import normalize_topic_to_niche


def apply_niche(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``record`` with ``niche`` set from ``topic`` when needed."""
    out = dict(record)
    existing = out.get("niche")
    if isinstance(existing, str) and existing.strip():
        out["niche"] = normalize_topic_to_niche(existing)
        return out
    out["niche"] = normalize_topic_to_niche(
        out.get("topic") if isinstance(out.get("topic"), str) else None
    )
    return out
