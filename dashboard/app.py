"""Throwaway visual test harness for the sample-collection module.

This is NOT the product UI - it exists purely so we can see what a scraper
module returns and confirm it saved correctly, one module at a time. When
Step 2 (make sense of samples) is built, it gets its own section/page here
rather than changing this one.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))

from config.settings import load_settings  # noqa: E402
from scrapers.linkedin_scraper import LinkedInScraper  # noqa: E402
from storage.sample_store import SampleStore  # noqa: E402

# Company LinkedIn pages put follower count (e.g. "3,121 followers") in the
# author.info field instead of a headline.  Compiled once at module level.
_FOLLOWER_RE = re.compile(r"^[\d,]+\s+followers?$", re.IGNORECASE)

st.set_page_config(page_title="Sample Scraper Test Harness", layout="wide")
st.title("Step 1: Get Samples — Scraper Test Harness")
st.caption("Throwaway visual tool for testing scraper modules. Not the product UI.")

settings = load_settings()

# Initialize session state for samples
if "samples" not in st.session_state:
    st.session_state.samples = []
if "saved_path" not in st.session_state:
    st.session_state.saved_path = None

with st.sidebar:
    st.header("Load Previous Scan")
    
    # List all saved scans
    data_dir = Path(settings.raw_data_dir)
    saved_scans = sorted(data_dir.glob("*.json"), reverse=True) if data_dir.exists() else []
    
    if saved_scans:
        scan_options = ["-- Select a saved scan --"] + [f.name for f in saved_scans]
        selected_scan = st.selectbox(
            "Saved scans",
            scan_options,
            help="Load a previously saved scan to avoid re-scraping",
        )
        
        if selected_scan != "-- Select a saved scan --":
            if st.button("Load Selected Scan", use_container_width=True):
                scan_path = data_dir / selected_scan
                with open(scan_path, "r") as f:
                    st.session_state.samples = json.load(f)
                    st.session_state.saved_path = str(scan_path)
                st.success(f"Loaded {len(st.session_state.samples)} posts from {selected_scan}")
    else:
        st.info("No saved scans found. Run a scrape first.")
    
    st.markdown("---")
    st.header("Run New Scrape")
    platform = st.selectbox(
        "Platform",
        ["linkedin"],
        help="More platforms plug in later via the BaseScraper interface.",
    )
    search_term = st.text_input(
        "Search query",
        value="ai marketing",
        help="LinkedIn search query (supports Boolean operators)",
    )
    limit = st.number_input(
        "Max posts", min_value=1, max_value=500, value=settings.default_search_limit
    )
    sort_by = st.selectbox(
        "Sort by", ["relevance", "date"], help="Sort by relevance or date (newest first)"
    )
    posted_limit = st.selectbox(
        "Time filter",
        ["all", "1h", "24h", "week", "month", "3months", "6months", "year"],
        help="Fetch posts no older than this time period",
    )
    run_clicked = st.button("Run Scraper", type="primary")

status_area = st.empty()
results_area = st.container()

if run_clicked:
    if not settings.apify_api_token or not settings.apify_actor_id:
        status_area.error("Missing APIFY_API_TOKEN or APIFY_ACTOR_ID. Check your .env file.")
    else:
        try:
            status_area.info(f"Starting {platform} scrape for '{search_term}' (limit={limit})...")
            scraper = LinkedInScraper(settings)
            params = {
                "searchQueries": [search_term],
                "maxPosts": int(limit),
                "sortBy": sort_by,
            }
            if posted_limit != "all":
                params["postedLimit"] = posted_limit
            samples = scraper.fetch_samples(params)

            status_area.info(f"Fetched {len(samples)} samples. Saving to disk...")
            store = SampleStore(settings.raw_data_dir)
            saved_path = store.save(platform, samples)
            
            # Store in session state
            st.session_state.samples = samples
            st.session_state.saved_path = saved_path

            status_area.success(f"Done. Saved {len(samples)} samples to `{saved_path}`.")
        except Exception as exc:  # surfaced in the UI on purpose for a test harness
            status_area.error(f"Scrape failed: {exc}")

# Display results if we have samples
if st.session_state.samples:
    with results_area:
        st.subheader("Results")
        
        # Sorting controls
        st.markdown("**Sort by engagement:**")
        col1, col2, col3, col4 = st.columns([1, 1, 1, 3])
        
        with col1:
            if st.button("Most Likes", use_container_width=True):
                st.session_state.samples = sorted(
                    st.session_state.samples,
                    key=lambda x: x.get("engagement", {}).get("likes", 0),
                    reverse=True
                )
        
        with col2:
            if st.button("Most Comments", use_container_width=True):
                st.session_state.samples = sorted(
                    st.session_state.samples,
                    key=lambda x: x.get("engagement", {}).get("comments", 0),
                    reverse=True
                )
        
        with col3:
            if st.button("Most Shares", use_container_width=True):
                st.session_state.samples = sorted(
                    st.session_state.samples,
                    key=lambda x: x.get("engagement", {}).get("shares", 0),
                    reverse=True
                )
        
        st.markdown("---")
        
        # Display table with flattened engagement metrics
        if st.session_state.samples:
            now = datetime.now(timezone.utc)

            display_samples = []
            for sample in st.session_state.samples:
                eng = sample.get("engagement", {})
                likes = eng.get("likes", 0) or 0
                comments = eng.get("comments", 0) or 0
                shares = eng.get("shares", 0) or 0
                total = likes + comments + shares

                # Reaction types breakdown  e.g. "LIKE:12 PRAISE:1"
                reactions_raw = eng.get("reactions", [])
                reaction_str = "  ".join(
                    f"{r.get('type','?')}:{r.get('count',0)}"
                    for r in reactions_raw
                ) if reactions_raw else "—"

                # Post age
                ts = sample.get("postedAt", {}).get("timestamp")
                if ts:
                    posted_dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                    age_hours = (now - posted_dt).total_seconds() / 3600
                    post_age = f"{int(age_hours)}h" if age_hours < 48 else f"{int(age_hours/24)}d"
                else:
                    post_age = "—"

                # Media
                images = sample.get("postImages", [])
                media_count = len(images)

                # Post text length
                content = sample.get("content", "") or ""
                post_length = len(content)

                # Author
                author = sample.get("author", {})
                author_name = author.get("name", "—")
                author_info = author.get("info") or ""

                # Company pages put their follower count in the `info` field
                # (e.g. "3,121 followers") instead of a headline. Detect that
                # so the two cases don't end up merged in the same column.
                if _FOLLOWER_RE.match(author_info.strip()):
                    author_headline = "—"
                    author_page_followers = author_info.strip()
                else:
                    author_headline = author_info or "—"
                    author_page_followers = "—"

                display_samples.append({
                    "Author": author_name,
                    "Headline": author_headline,
                    "Page Followers": author_page_followers,
                    "Post (preview)": content[:120] + "…" if len(content) > 120 else content,
                    "Post Length": post_length,
                    "Post Age": post_age,
                    "Has Media": "✅" if media_count > 0 else "❌",
                    "Media Count": media_count,
                    "👍 Likes": likes,
                    "💬 Comments": comments,
                    "🔄 Shares": shares,
                    "⚡ Total Engagement": total,
                    "💬/👍 Comment Ratio": round(comments / likes, 2) if likes else "—",
                    "🔄/👍 Share Ratio": round(shares / likes, 2) if likes else "—",
                    "Reaction Breakdown": reaction_str,
                    "LinkedIn URL": sample.get("linkedinUrl", ""),
                })
            
            st.dataframe(display_samples, use_container_width=True)
        else:
            st.warning("No samples returned.")

        # Raw JSON viewer
        st.subheader("Raw JSON")
        st.json(st.session_state.samples)
        
        if st.session_state.saved_path:
            st.info(f"💾 Data saved to: `{st.session_state.saved_path}`")
else:
    status_area.info("Set your params in the sidebar and click 'Run Scraper'.")
