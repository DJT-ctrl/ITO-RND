"""Apify client response normalization (no settings / DB imports)."""

from __future__ import annotations

from typing import Any


def apify_run_as_dict(run: Any) -> dict[str, Any]:
    """Normalize an Apify ``.call()`` result to a camelCase dict.

    apify-client 1.x returned plain dicts; 3.x returns a Pydantic ``Run``
    model (attribute access / snake_case). Call sites and telemetry still
    expect camelCase keys like ``defaultDatasetId``.
    """
    if run is None:
        raise RuntimeError("Apify actor call returned no run.")
    if isinstance(run, dict):
        return run
    model_dump = getattr(run, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(by_alias=True, mode="python")
        if isinstance(dumped, dict):
            return dumped
    raise TypeError(f"Unexpected Apify run type: {type(run)!r}")
