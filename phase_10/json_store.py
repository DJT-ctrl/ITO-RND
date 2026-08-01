"""Atomic JSON read/write helpers shared by agentic stub persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def read_json_object(path: Path) -> dict[str, Any]:
    """Return a JSON object from ``path``, or ``{}`` if missing/invalid."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read JSON object from %s", path)
        return {}
    return raw if isinstance(raw, dict) else {}


def write_json_object(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write ``payload`` as pretty JSON (tmp + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
