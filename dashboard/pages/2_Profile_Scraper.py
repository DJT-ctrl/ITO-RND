"""Throwaway visual test harness for the profile-enrichment module.

Loads a previously saved post scan, classifies each author as personal vs.
business (processors/profile_enricher.py), and runs ONLY the personal
authors through the profile scraper — business/company authors' follower
counts come free from data already in the post scan, no paid scrape
needed. This closes the "who is posting and how big is their audience"
gap the post-search scraper leaves open, needed so engagement can later be
normalized by audience size instead of just rewarding whoever already has
the biggest following.

Not the product UI - same spirit as dashboard/app.py's Step 1 harness.
"""

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from processors.profile_enricher import (  # noqa: E402
    collect_personal_profile_urls,
    enrich_posts_with_follower_data,
)
from scrapers.linkedin_profile_scraper import LinkedInProfileScraper  # noqa: E402
from storage.processed_store import ProcessedStore  # noqa: E402
from storage.sample_store import SampleStore  # noqa: E402

st.set_page_config(page_title="Profile Enrichment Test Harness", layout="wide")
st.title("Step 1b: Enrich Authors — Profile Scraper")
st.caption(
    "Throwaway visual tool for testing the profile scraper module. Not the product UI."
)

settings = load_settings()

if "loaded_posts" not in st.session_state:
    st.session_state.loaded_posts = []
if "profile_samples" not in st.session_state:
    st.session_state.profile_samples = []
if "enriched_records" not in st.session_state:
    st.session_state.enriched_records = []
if "profile_saved_path" not in st.session_state:
    st.session_state.profile_saved_path = None
if "enriched_saved_path" not in st.session_state:
    st.session_state.enriched_saved_path = None

with st.sidebar:
    st.header("1. Load a post scan")

    data_dir = Path(settings.raw_data_dir)
    post_scans = sorted(data_dir.glob("linkedin_*.json"), reverse=True) if data_dir.exists() else []
    post_scans = [f for f in post_scans if "profiles" not in f.name]

    personal_urls: list[str] = []
    if post_scans:
        selected_scan = st.selectbox(
            "Saved post scans",
            ["-- Select a saved scan --"] + [f.name for f in post_scans],
            help="Authors are classified personal vs. business from this scan.",
        )
        if selected_scan != "-- Select a saved scan --":
            posts = json.loads((data_dir / selected_scan).read_text())
            st.session_state.loaded_posts = posts
            personal_urls = collect_personal_profile_urls(posts)
            st.info(
                f"{len(posts)} post(s) loaded — "
                f"{len(personal_urls)} unique personal author(s) need a paid scrape, "
                "business authors' followers come free from this scan."
            )
    else:
        st.info("No saved post scans found. Run Step 1 first.")

    st.markdown("---")
    st.header("2. Run profile scrape")
    st.caption("Only personal authors are sent to the paid scraper — business authors are skipped.")
    manual_urls_raw = st.text_area(
        "Or paste extra personal profile URLs (one per line)",
        help="Added on top of any personal authors found in the scan above.",
    )
    manual_urls = {u.strip() for u in manual_urls_raw.splitlines() if u.strip()}
    profile_urls = sorted(set(personal_urls) | manual_urls)

    st.caption(f"**{len(profile_urls)} personal profile(s)** queued for this run.")
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
    else:
        try:
            status_area.info(f"Scraping {len(profile_urls)} personal profile(s)...")
            scraper = LinkedInProfileScraper(settings)
            samples = scraper.fetch_samples({"profileUrls": profile_urls})

            status_area.info(f"Fetched {len(samples)} profiles. Merging + saving...")
            store = SampleStore(settings.raw_data_dir)
            saved_path = store.save("linkedin_profiles", samples)

            st.session_state.profile_samples = samples
            st.session_state.profile_saved_path = saved_path

            if st.session_state.loaded_posts:
                enriched = enrich_posts_with_follower_data(
                    st.session_state.loaded_posts, samples
                )
                st.session_state.enriched_records = enriched
                enriched_path = ProcessedStore().save(
                    "linkedin_enriched",
                    [
                        {
                            "post_id": p.get("id") or "",
                            "author_name": (p.get("author") or {}).get("name") or "",
                            "is_business": p["is_business"],
                            "follower_count": p["follower_count"],
                            "connections_count": p["connections_count"],
                            "headline": p["headline"],
                            "location_text": p["location_text"],
                            "open_to_work": p["open_to_work"],
                            "hiring": p["hiring"],
                            "premium": p["premium"],
                            "influencer": p["influencer"],
                            "verified": p["verified"],
                        }
                        for p in enriched
                    ],
                )
                st.session_state.enriched_saved_path = enriched_path

            status_area.success(f"Done. Saved {len(samples)} profiles to `{saved_path}`.")
        except Exception as exc:  # surfaced in the UI on purpose for a test harness
            status_area.error(f"Profile scrape failed: {exc}")

if st.session_state.profile_samples:
    with results_area:
        st.subheader("Personal Profile Results (paid scrape)")

        display_rows = []
        for profile in st.session_state.profile_samples:
            name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or "—"
            display_rows.append(
                {
                    "Name": name,
                    "Headline": profile.get("headline", "—"),
                    "Followers": profile.get("followerCount", "—"),
                    "Connections": profile.get("connectionsCount", "—"),
                    "Location": (profile.get("location") or {}).get("linkedinText", "—"),
                }
            )

        st.dataframe(display_rows, use_container_width=True)

        st.subheader("Raw JSON")
        st.json(st.session_state.profile_samples)

        if st.session_state.profile_saved_path:
            st.info(f"💾 Personal profile data saved to: `{st.session_state.profile_saved_path}`")

if st.session_state.enriched_records:
    with results_area:
        st.subheader("Enriched Posts (business + personal, merged)")
        st.caption(
            "Business authors' follower counts came free from the post scan — "
            "no extra scraper credits spent on them."
        )
        enriched_rows = [
            {
                "Author": (p.get("author") or {}).get("name", "—"),
                "Business?": p["is_business"],
                "Followers": p["follower_count"],
            }
            for p in st.session_state.enriched_records
        ]
        st.dataframe(enriched_rows, use_container_width=True)

        if st.session_state.enriched_saved_path:
            st.info(f"💾 Enriched CSV saved to: `{st.session_state.enriched_saved_path}`")
elif not run_clicked:
    status_area.info("Select a saved post scan in the sidebar and click 'Run Profile Scraper'.")

