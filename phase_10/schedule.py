"""Schedule status (T10.3) — last/next runs from Postgres."""

from __future__ import annotations

from config.settings import Settings, load_settings
from phase_10.db import AgenticDbError, agentic_connection
from phase_10.job_flags import load_job_flags
from phase_10.models import JOB_FLAG_KEYS, JOB_FLAG_LABELS, ScheduleStatus
from phase_10 import schedule_store


def get_schedule_status(settings: Settings | None = None) -> ScheduleStatus:
    settings = settings or load_settings()
    flags = load_job_flags().to_dict()
    rows: dict = {}
    try:
        with agentic_connection(settings) as conn:
            rows = schedule_store.load_run_rows(conn)
    except AgenticDbError:
        pass

    jobs = tuple(
        schedule_store.row_to_status(
            key,
            label=JOB_FLAG_LABELS[key],
            enabled=bool(flags.get(key, True)),
            row=rows.get(key),
        )
        for key in JOB_FLAG_KEYS
    )
    return ScheduleStatus(jobs=jobs, stub=False)
