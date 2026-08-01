"""Job enable/disable flags (honored by T10.3 scheduler when wired)."""

from __future__ import annotations

from typing import Any

from phase_10.json_store import read_json_object, write_json_object
from phase_10.models import JOB_FLAG_KEYS, JobFlags
from phase_10.paths import JOB_FLAGS_PATH


def _coerce_flags(raw: dict[str, Any]) -> JobFlags:
    defaults = JobFlags().to_dict()
    values: dict[str, bool] = {}
    for key in JOB_FLAG_KEYS:
        if key in raw:
            values[key] = bool(raw[key])
        else:
            values[key] = defaults[key]
    return JobFlags(**values)


def load_job_flags() -> JobFlags:
    return _coerce_flags(read_json_object(JOB_FLAGS_PATH))


def save_job_flags(updates: dict[str, bool]) -> JobFlags:
    current = load_job_flags().to_dict()
    for key in JOB_FLAG_KEYS:
        if key in updates:
            current[key] = bool(updates[key])
    flags = JobFlags(**current)
    write_json_object(JOB_FLAGS_PATH, flags.to_dict())
    return flags
