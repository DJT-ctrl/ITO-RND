"""Tests for feedback loop dashboard runtime flag overrides."""

from dataclasses import dataclass
from pathlib import Path

import feedback.runtime_flags as rf


@dataclass(frozen=True)
class _FakeSettings:
    validation_calibration_enabled: bool = True
    validation_feedback_enabled: bool = True
    validation_feedback_injection_enabled: bool = True
    validation_feedback_injection_limit: int = 5
    validation_calibration_n_min: int = 30
    validation_cluster_n_min: int = 50
    other_field: str = "keep"


def test_save_and_apply_overrides(tmp_path: Path, monkeypatch):
    path = tmp_path / "overrides.json"
    monkeypatch.setattr(rf, "OVERRIDE_PATH", path)

    assert rf.load_overrides() == {}

    rf.save_overrides(
        {
            "validation_calibration_enabled": False,
            "validation_feedback_injection_limit": 3,
            "not_allowed": "ignored",
        }
    )
    loaded = rf.load_overrides()
    assert loaded["validation_calibration_enabled"] is False
    assert loaded["validation_feedback_injection_limit"] == 3
    assert "not_allowed" not in loaded

    updated = rf.apply_overrides_to_settings(_FakeSettings())
    assert updated.validation_calibration_enabled is False
    assert updated.validation_feedback_injection_limit == 3
    assert updated.other_field == "keep"
    assert updated.validation_feedback_enabled is True

    rf.clear_overrides()
    assert rf.load_overrides() == {}
    assert not path.exists()
    audit_path = tmp_path / "telemetry" / "feedback_loop_overrides.jsonl"
    assert len(audit_path.read_text(encoding="utf-8").splitlines()) == 2
