"""Global pause + last-tick heartbeat for the agentic scheduler (UI + CLI)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from phase_10.json_store import read_json_object, write_json_object
from phase_10.paths import TICK_CONTROL_PATH, ensure_data_dir


@dataclass(frozen=True)
class TickControl:
    """Operator-visible scheduler state (shared by dashboard and tick CLI)."""

    paused: bool = False
    last_tick_at: str | None = None
    last_tick_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "paused": self.paused,
            "last_tick_at": self.last_tick_at,
            "last_tick_summary": self.last_tick_summary,
        }


def _coerce(raw: dict[str, Any]) -> TickControl:
    return TickControl(
        paused=bool(raw.get("paused", False)),
        last_tick_at=raw.get("last_tick_at")
        if isinstance(raw.get("last_tick_at"), str)
        else None,
        last_tick_summary=raw.get("last_tick_summary")
        if isinstance(raw.get("last_tick_summary"), str)
        else None,
    )


def load_tick_control() -> TickControl:
    ensure_data_dir()
    return _coerce(read_json_object(TICK_CONTROL_PATH))


def save_tick_control(control: TickControl) -> TickControl:
    ensure_data_dir()
    write_json_object(TICK_CONTROL_PATH, control.to_dict())
    return control


def is_tick_paused() -> bool:
    return load_tick_control().paused


def set_tick_paused(paused: bool) -> TickControl:
    current = load_tick_control()
    return save_tick_control(
        TickControl(
            paused=paused,
            last_tick_at=current.last_tick_at,
            last_tick_summary=current.last_tick_summary,
        )
    )


def record_tick_heartbeat(summary: str) -> TickControl:
    """Persist when a tick attempt finished (ran, skipped, or paused)."""
    current = load_tick_control()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return save_tick_control(
        TickControl(
            paused=current.paused,
            last_tick_at=now,
            last_tick_summary=summary,
        )
    )
