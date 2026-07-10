"""Loads a previously-saved profile scrape for the optional profile-enriched
pipeline path (processors/run_pipeline.py --with-profile-enrichment).

Deliberately tiny and separate from processors/profile_enricher.py (which
does the classification/merging logic): this module's only job is "find and
read the right data/raw/linkedin_profiles_*.json file", so the merging code
doesn't need to know anything about file discovery.
"""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path
from typing import Any, Optional

_POST_SCAN_TS_RE = re.compile(
    r"^linkedin_(?P<ts>\d{8}T\d{6}Z|\d{4}-\d{2}-\d{2}_\d{6}Z)\.json$"
)


def extract_scan_timestamp(path: Path | str) -> str | None:
    """Return the UTC timestamp suffix from a linkedin_*.json post scan filename."""
    match = _POST_SCAN_TS_RE.match(Path(path).name)
    return match.group("ts") if match else None


def find_paired_profile_file(
    post_scan_path: Path | str, raw_data_dir: str | None = None
) -> Path | None:
    """Find the profile scrape paired to a post scan by shared timestamp.

    Falls back to the latest ``linkedin_profiles_*.json`` under ``raw_data_dir``
    when no exact timestamp match exists (legacy post-only scans).
    """
    post_path = Path(post_scan_path)
    raw_dir = Path(raw_data_dir) if raw_data_dir else post_path.parent
    ts = extract_scan_timestamp(post_path)
    if ts:
        paired = raw_dir / f"linkedin_profiles_{ts}.json"
        if paired.exists():
            return paired

    candidates = sorted(raw_dir.glob("linkedin_profiles_*.json"))
    return Path(candidates[-1]) if candidates else None


def load_profile_lookup_from_post_scan(
    post_scan_path: Path | str, raw_data_dir: str | None = None
) -> tuple[dict[str, dict[str, Any]], Path | None]:
    """Build author publicIdentifier → profile fields from a paired profile file."""
    profile_path = find_paired_profile_file(post_scan_path, raw_data_dir)
    if profile_path is None:
        return {}, None

    lookup: dict[str, dict[str, Any]] = {}
    for record in json.loads(profile_path.read_text()):
        pid = record.get("publicIdentifier")
        if not pid:
            continue
        lookup[pid] = {
            "author_followers": (
                record.get("followersCount")
                or record.get("followerCount")
                or record.get("connectionsCount")
            ),
            "author_industry": record.get("industryName"),
            "author_company": record.get("companyName"),
        }
    return lookup, profile_path


def load_profile_records(
    profile_file: Optional[str], raw_data_dir: str, *, allow_empty: bool = False
) -> list[dict[str, Any]]:
    """Load a saved profile scrape (list of harvestapi-shaped dicts).

    If `profile_file` is given, load exactly that file. Otherwise, load the
    most recent `linkedin_profiles_*.json` under `raw_data_dir`.

    Raises:
        ValueError: no profile file was given/found, or the resolved file
            contains an empty list — either way, there's nothing to enrich
            with, and the caller (run_pipeline's --with-profile-enrichment)
            is expected to fail clearly rather than silently proceed with
            no follower data at all.
    """
    if profile_file:
        path = Path(profile_file)
        if not path.exists():
            raise ValueError(f"Profile file not found: {profile_file}")
    else:
        candidates = sorted(glob.glob(f"{raw_data_dir}/linkedin_profiles_*.json"))
        if not candidates:
            raise ValueError(
                f"--with-profile-enrichment was requested but no profile scrape "
                f"was found under {raw_data_dir}/linkedin_profiles_*.json. "
                "Run processors/run_sample_collection.py first (or pass "
                "--profile-file pointing at a saved scrape)."
            )
        path = Path(candidates[-1])

    records = json.loads(path.read_text())
    if not records and not allow_empty:
        raise ValueError(f"Profile file {path} contains no records — nothing to enrich with.")
    return records
