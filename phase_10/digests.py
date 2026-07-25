"""Dev AI digests stub (T10.10 writes Pro digests here later)."""

from __future__ import annotations

from phase_10.models import DigestRecord


def list_digests(*, limit: int = 10) -> list[DigestRecord]:
    """Return recent Pro digests. Empty until T10.10 persists digests."""
    _ = limit
    return []
