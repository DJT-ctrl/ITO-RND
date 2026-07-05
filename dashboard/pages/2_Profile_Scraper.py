"""Throwaway visual test harness for the profile-enrichment module.

Loads a previously saved post scan, extracts each unique author's LinkedIn
URL, and runs them through the profile scraper. This closes the "who is
posting and how big is their audience" gap the post-search scraper leaves
open - needed so engagement can later be normalized by audience size
instead of just rewarding whoever already has the biggest following.

Not the product UI - same spirit as dashboard/app.py's Step 1 harness.
"""

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from scrapers.linkedin_profile_scraper import LinkedInProfileScraper  # noqa: E402
from storage.sample_store import SampleStore  # noqa: E402

st.set_page_config(page_title="Profile Enrichment Test Harness", layout="wide")
st.title("Step 1b: Enrich Authors — Profile Scraper")
st.caption(
    "Throwaway visual tool for testing the profile scraper module. Not the product UI."
)

settings = load_settings()

if "profile_samples" not in st.session_state:
    st.session_state.profile_samples = []
if "profile_saved_path" not in st.session_state:
    st.session_state.profile_saved_path = None

with st.sidebar:
    st.header("1. Load a post scan")

    data_dir = Path(settings.raw_data_dir)
    post_scans = sorted(data_dir.glob("linkedin_*.json"), reverse=True) if data_dir.exists() else []

    authors_from_scan: list[str] = []
    if post_scans:
        selected_scan = st.selectbox(
            "Saved post scans",
            ["-- Select a saved scan --"] + [f.name for f in post_scans],
            help="Author URLs are pulled straight out of this file.",
        )
        if selected_scan != "-- Select a saved scan --":
            posts = json.loads((data_dir / selected_scan).read_text())
            authors_from_scan = sorted(
                {
                    p.get("author", {}).get("linkedinUrl", "")
                    for p in posts
                    if p.get("author", {}).get("linkedinUrl")
                }
            )
            st.info(f"Found {len(authors_from_scan)} unique author(s) in this scan.")
    else:
        st.info("No saved post scans found. Run Step 1 first.")

    st.markdown("---")
    st.header("2. Run profile scrape")
    manual_urls_raw = st.text_area(
        "Or paste extra profile URLs (one per line)",
        help="Added on top of any authors found in the scan above.",
    )
    manual_urls = {u.strip() for u in manual_urls_raw.splitlines() if u.strip()}
    profile_urls = sorted(set(authors_from_scan) | manual_urls)

    st.caption(f"**{len(profile_urls)} profile(s)** queued for this run.")
    run_clicked = st.button(
        "Run Profile Scraper", type="primary", disabled=not profile_urls
    )

status_area = st.empty()
results_area = st.container()

if run_clicked:
    if not settings.apify_api_token or not settings.apify_profile_actor_id:
        status_area.error(
            "Missing APIFY_API_TOKEN or APIFY_PROFILE_ACTOR_ID. Check your .env file."
        )
    elif not settings.linkedin_cookies:
        status_area.error("Missing LINKEDIN_COOKIES. Check your .env file.")
    else:
        try:
            status_area.info(f"Scraping {len(profile_urls)} profile(s)...")
            scraper = LinkedInProfileScraper(settings)
            samples = scraper.fetch_samples({"profileUrls": profile_urls})

            status_area.info(f"Fetched {len(samples)} profiles. Saving to disk...")
            store = SampleStore(settings.raw_data_dir)
            saved_path = store.save("linkedin_profiles", samples)

            st.session_state.profile_samples = samples
            st.session_state.profile_saved_path = saved_path

            status_area.success(f"Done. Saved {len(samples)} profiles to `{saved_path}`.")
        except Exception as exc:  # surfaced in the UI on purpose for a test harness
            status_area.error(f"Profile scrape failed: {exc}")

if st.session_state.profile_samples:
    with results_area:
        st.subheader("Results")

        display_rows = []
        for profile in st.session_state.profile_samples:
            # Field name for follower count isn't confirmed against a live
            # actor run yet - try the likely candidates so the harness still
            # shows something useful either way.
            followers = (
                profile.get("followersCount")
                or profile.get("followerCount")
                or profile.get("connectionsCount")
                or "—"
            )
            name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or "—"
            display_rows.append(
                {
                    "Name": name,
                    "Headline": profile.get("headline", "—"),
                    "Followers": followers,
                    "Industry": profile.get("industryName", "—"),
                    "Company": profile.get("companyName", "—"),
                    "Country": profile.get("countryCode", "—"),
                }
            )

        st.dataframe(display_rows, use_container_width=True)

        st.subheader("Raw JSON")
        st.json(st.session_state.profile_samples)

        if st.session_state.profile_saved_path:
            st.info(f"💾 Data saved to: `{st.session_state.profile_saved_path}`")
else:
    status_area.info("Select/paste profile URLs in the sidebar and click 'Run Profile Scraper'.")
