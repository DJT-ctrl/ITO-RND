"""Schedule status stub (T10.3 fills last/next run timestamps)."""

from __future__ import annotations

from phase_10.job_flags import load_job_flags
from phase_10.models import JOB_FLAG_LABELS, JOB_FLAG_KEYS, JobRunStatus, ScheduleStatus


def get_schedule_status() -> ScheduleStatus:
    flags = load_job_flags().to_dict()
    jobs = tuple(
        JobRunStatus(
            job_id=key,
            label=JOB_FLAG_LABELS[key],
            enabled=bool(flags.get(key, True)),
            last_run_at=None,
            next_run_at=None,
            last_result="not scheduled yet (T10.3)",
        )
        for key in JOB_FLAG_KEYS
    )
    return ScheduleStatus(jobs=jobs, stub=True)
