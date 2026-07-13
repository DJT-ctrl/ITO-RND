"""Append-only audit records for feedback-loop runtime changes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from config.paths import PROJECT_ROOT

AUDIT_PATH = PROJECT_ROOT / "data" / "telemetry" / "feedback_loop_overrides.jsonl"


def append_override_audit(
    *,
    action: str,
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    actor: Optional[str] = None,
    path: Path = AUDIT_PATH,
) -> None:
    """Append one JSONL event; callers decide whether audit failure is fatal."""
    event = {
        "schema_version": "1.0",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "actor": actor or "dashboard",
        "action": action,
        "previous": dict(previous),
        "current": dict(current),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
