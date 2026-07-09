"""Loads a previously-saved profile scrape for the optional profile-enriched
pipeline path (processors/run_pipeline.py --with-profile-enrichment).

Deliberately tiny and separate from processors/profile_enricher.py (which
does the classification/merging logic): this module's only job is "find and
read the right data/raw/linkedin_profiles_*.json file", so the merging code
doesn't need to know anything about file discovery.
"""

import glob
import json
from pathlib import Path
from typing import Any, Optional


def load_profile_records(
    profile_file: Optional[str], raw_data_dir: str
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
                "Run processors/run_profile_enrichment.py's scraper step first "
                "(or dashboard/pages/2_Profile_Scraper.py), then re-run with "
                "--profile-file pointing at the saved scrape if needed."
            )
        path = Path(candidates[-1])

    records = json.loads(path.read_text())
    if not records:
        raise ValueError(f"Profile file {path} contains no records — nothing to enrich with.")
    return records
