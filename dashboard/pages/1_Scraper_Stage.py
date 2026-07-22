"""Corpus step 1 — collect LinkedIn samples and author profiles."""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from config.paths import resolve_data_path  # noqa: E402
from config.settings import load_settings  # noqa: E402
from dashboard.chrome import page_header, pipeline_flow_strip, section_header  # noqa: E402
from dashboard.pipeline_readiness import compute_corpus_readiness  # noqa: E402
from processors.profile_sources import find_paired_profile_file  # noqa: E402
from processors.run_sample_collection import run_sample_collection  # noqa: E402
from telemetry.apify_ui import render_apify_cost_history, render_apify_session_cost  # noqa: E402

_FOLLOWER_RE = re.compile(r"^[\d,]+\s+followers?$", re.IGNORECASE)

settings = load_settings()
_corpus_ready = compute_corpus_readiness("collect", settings=settings)

page_header(
    "Collect samples",
    "Pull LinkedIn posts (and matching author profiles) so the rest of the "
    "corpus pipeline has raw data to work with. Uses Apify — expect cost.",
    step_hint="Corpus step 1 of 5 · Next: Analyse posts",
)
pipeline_flow_strip("corpus", "collect", readiness=_corpus_ready)
_analyse = _corpus_ready.steps.get("analyse")
if _analyse and _analyse.state == "ready":
    st.caption(f"→ {_analyse.hint}")
elif _analyse and _analyse.state == "done":
    st.caption(f"✓ {_analyse.hint} · ready for Patterns / Embed")

section_header(
    "What this page does",
    """
**Input:** search keywords / filters (or load a previous JSON collection).

**Output:** saved `linkedin_*.json` files under the raw data folder, ready for
**Analyse posts**.

Use the sidebar to reload an earlier collection without re-scraping.
""",
)

if "samples" not in st.session_state:
    st.session_state.samples = []
if "enriched_samples" not in st.session_state:
    st.session_state.enriched_samples = []
if "saved_path" not in st.session_state:
    st.session_state.saved_path = None
if "profile_saved_path" not in st.session_state:
    st.session_state.profile_saved_path = None
if "enriched_saved_path" not in st.session_state:
    st.session_state.enriched_saved_path = None
if "last_apify_runs" not in st.session_state:
    st.session_state.last_apify_runs = []

with st.sidebar:
    st.header("Load Previous Collection")

    data_dir = resolve_data_path(settings.raw_data_dir)
    saved_scans = (
        sorted(
            (f for f in data_dir.glob("linkedin_*.json") if "profiles" not in f.name),
            reverse=True,
        )
        if data_dir.exists()
        else []
    )

    if saved_scans:
        scan_options = ["-- Select a saved collection --"] + [f.name for f in saved_scans]
        selected_scan = st.selectbox(
            "Saved collections",
            scan_options,
            help="Load a previously saved post scan (paired profile data auto-detected).",
        )

        if selected_scan != "-- Select a saved collection --":
            if st.button("Load Selected Collection", use_container_width=True):
                scan_path = data_dir / selected_scan
                with open(scan_path, "r") as f:
                    st.session_state.samples = json.load(f)
                    st.session_state.saved_path = str(scan_path)

                paired = find_paired_profile_file(scan_path, settings.raw_data_dir)
                st.session_state.profile_saved_path = str(paired) if paired else None
                st.session_state.enriched_samples = []
                st.session_state.enriched_saved_path = None

                if paired:
                    st.success(
                        f"Loaded {len(st.session_state.samples)} posts + paired profiles "
                        f"from `{paired.name}`."
                    )
                else:
                    st.warning(
                        f"Loaded {len(st.session_state.samples)} posts — no paired profile data."
                    )
    else:
        st.info("No saved collections found. Run a collection first.")

    st.markdown("---")
    st.header("Run New Collection")
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
    run_clicked = st.button("Run Collection", type="primary")

status_area = st.empty()
results_area = st.container()

if run_clicked:
    if not settings.apify_api_token or not settings.apify_actor_id:
        status_area.error("Missing APIFY_API_TOKEN or APIFY_ACTOR_ID. Check your .env file.")
    elif not settings.apify_profile_actor_id:
        status_area.error("Missing APIFY_PROFILE_ACTOR_ID. Check your .env file.")
    else:
        try:
            status_area.info(
                f"Phase 1/2: Starting {platform} post search for '{search_term}' "
                f"(limit={limit})..."
            )
            params = {
                "searchQueries": [search_term],
                "maxPosts": int(limit),
                "sortBy": sort_by,
            }
            if posted_limit != "all":
                params["postedLimit"] = posted_limit

            result = run_sample_collection(
                params,
                settings=settings,
                on_progress=lambda msg: status_area.info(msg),
            )

            st.session_state.samples = result.posts
            st.session_state.enriched_samples = result.enriched_posts
            st.session_state.saved_path = str(result.post_path)
            st.session_state.profile_saved_path = (
                str(result.profile_path) if result.profile_path else None
            )
            st.session_state.enriched_saved_path = (
                str(result.enriched_path) if result.enriched_path else None
            )
            st.session_state.last_apify_runs = result.apify_runs

            total_cost = sum(r.cost_usd for r in result.apify_runs)
            summary = (
                f"Done. Saved {len(result.posts)} post(s) to "
                f"`{result.post_path}`."
            )
            if result.profile_path:
                summary += f" Profiles: `{result.profile_path}`."
            if result.enriched_path:
                summary += f" Enriched CSV: `{result.enriched_path}`."
            if result.apify_runs:
                summary += f" Apify cost: ${total_cost:.4f}."
            status_area.success(summary)
        except Exception as exc:  # surfaced in the UI on purpose for a test harness
            status_area.error(f"Collection failed: {exc}")

display_posts = st.session_state.enriched_samples or st.session_state.samples

if st.session_state.last_apify_runs:
    render_apify_session_cost(st.session_state.last_apify_runs)
    st.divider()

render_apify_cost_history(settings)

st.divider()

if display_posts:
    with results_area:
        st.subheader("Results")

        st.markdown("**Sort by engagement:**")
        col1, col2, col3, col4 = st.columns([1, 1, 1, 3])

        sort_key = (
            st.session_state.enriched_samples
            if st.session_state.enriched_samples
            else st.session_state.samples
        )

        with col1:
            if st.button("Most Likes", use_container_width=True):
                sorted_posts = sorted(
                    sort_key,
                    key=lambda x: x.get("engagement", {}).get("likes", 0),
                    reverse=True,
                )
                if st.session_state.enriched_samples:
                    st.session_state.enriched_samples = sorted_posts
                else:
                    st.session_state.samples = sorted_posts

        with col2:
            if st.button("Most Comments", use_container_width=True):
                sorted_posts = sorted(
                    sort_key,
                    key=lambda x: x.get("engagement", {}).get("comments", 0),
                    reverse=True,
                )
                if st.session_state.enriched_samples:
                    st.session_state.enriched_samples = sorted_posts
                else:
                    st.session_state.samples = sorted_posts

        with col3:
            if st.button("Most Shares", use_container_width=True):
                sorted_posts = sorted(
                    sort_key,
                    key=lambda x: x.get("engagement", {}).get("shares", 0),
                    reverse=True,
                )
                if st.session_state.enriched_samples:
                    st.session_state.enriched_samples = sorted_posts
                else:
                    st.session_state.samples = sorted_posts

        st.markdown("---")

        now = datetime.now(timezone.utc)
        display_samples = []
        for sample in display_posts:
            eng = sample.get("engagement", {})
            likes = eng.get("likes", 0) or 0
            comments = eng.get("comments", 0) or 0
            shares = eng.get("shares", 0) or 0
            total = likes + comments + shares

            reactions_raw = eng.get("reactions", [])
            reaction_str = (
                "  ".join(
                    f"{r.get('type', '?')}:{r.get('count', 0)}"
                    for r in reactions_raw
                )
                if reactions_raw
                else "—"
            )

            ts = sample.get("postedAt", {}).get("timestamp")
            if ts:
                posted_dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                age_hours = (now - posted_dt).total_seconds() / 3600
                post_age = f"{int(age_hours)}h" if age_hours < 48 else f"{int(age_hours / 24)}d"
            else:
                post_age = "—"

            images = sample.get("postImages", [])
            media_count = len(images)
            content = sample.get("content", "") or ""
            post_length = len(content)

            author = sample.get("author", {})
            author_name = author.get("name", "—")
            author_info = author.get("info") or ""

            if _FOLLOWER_RE.match(author_info.strip()):
                author_headline = "—"
                author_page_followers = author_info.strip()
            else:
                author_headline = author_info or "—"
                author_page_followers = "—"

            row = {
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
            }

            if "is_business" in sample:
                row["Business?"] = sample.get("is_business")
                row["Followers"] = sample.get("follower_count", "—")

            display_samples.append(row)

        st.dataframe(display_samples, use_container_width=True)

        st.subheader("Raw JSON")
        st.json(display_posts)

        if st.session_state.saved_path:
            st.info(f"Posts saved to: `{st.session_state.saved_path}`")
        if st.session_state.profile_saved_path:
            st.info(f"Profiles saved to: `{st.session_state.profile_saved_path}`")
        elif st.session_state.saved_path:
            st.caption("No paired profile scrape for this collection.")
        if st.session_state.enriched_saved_path:
            st.info(f"Enriched CSV saved to: `{st.session_state.enriched_saved_path}`")
else:
    status_area.info("Set your params in the sidebar and click 'Run Collection'.")
