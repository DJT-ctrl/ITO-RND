"""In-memory async job tracking for long-running API work (corpus ingest, etc.).

Process-local only — fine for single-instance Compose/MVP. Restart clears jobs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal, Optional
from uuid import uuid4

JobStatus = Literal["queued", "running", "completed", "failed"]

_lock = Lock()
_jobs: dict[str, dict[str, Any]] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_job(kind: str, *, meta: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    job_id = str(uuid4())
    now = _utc_now()
    row = {
        "id": job_id,
        "kind": kind,
        "status": "queued",
        "meta": meta or {},
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "finished_at": None,
    }
    with _lock:
        _jobs[job_id] = row
    return dict(row)


def mark_running(job_id: str) -> None:
    with _lock:
        job = _jobs[job_id]
        job["status"] = "running"
        job["updated_at"] = _utc_now()


def mark_completed(job_id: str, result: dict[str, Any]) -> None:
    now = _utc_now()
    with _lock:
        job = _jobs[job_id]
        job["status"] = "completed"
        job["result"] = result
        job["error"] = None
        job["updated_at"] = now
        job["finished_at"] = now


def mark_failed(job_id: str, error: str) -> None:
    now = _utc_now()
    with _lock:
        job = _jobs[job_id]
        job["status"] = "failed"
        job["error"] = error
        job["updated_at"] = now
        job["finished_at"] = now


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None
