"""Tests for append-only feedback-loop override audit log."""

import json
from pathlib import Path

from feedback.audit import append_override_audit


def test_append_override_audit_writes_jsonl_event(tmp_path: Path):
    path = tmp_path / "telemetry" / "feedback_loop_overrides.jsonl"
    append_override_audit(
        action="save",
        previous={"validation_calibration_enabled": False},
        current={"validation_calibration_enabled": True},
        actor="test",
        path=path,
    )
    append_override_audit(
        action="reset",
        previous={"validation_calibration_enabled": True},
        current={},
        actor="test",
        path=path,
    )

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["schema_version"] == "1.0"
    assert first["action"] == "save"
    assert first["actor"] == "test"
    assert first["previous"]["validation_calibration_enabled"] is False
    assert first["current"]["validation_calibration_enabled"] is True
    assert "recorded_at" in first
    assert second["action"] == "reset"
    assert second["current"] == {}
