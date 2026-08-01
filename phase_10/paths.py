"""Filesystem locations for agentic-layer JSON state (pre-Postgres stubs)."""

from __future__ import annotations

from pathlib import Path

from config.paths import project_root

_DATA = project_root() / "data"

SEEDS_PATH = _DATA / "agentic_layer_seeds.json"
JOB_FLAGS_PATH = _DATA / "agentic_job_flags.json"
DIGESTS_PATH = _DATA / "agentic_digests.jsonl"


def ensure_data_dir() -> Path:
    _DATA.mkdir(parents=True, exist_ok=True)
    return _DATA
