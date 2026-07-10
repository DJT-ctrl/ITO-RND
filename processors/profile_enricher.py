"""Classifies post authors as personal vs. business and enriches posts with
follower counts, without wasting paid profile-scraper credits.

Why this exists (T6 Point 1 — reach-bias normalization)
---------------------------------------------------------
The Predictor Agent compares a draft against historical posts using ABSOLUTE
engagement figures. A creator with a huge following gets thousands of views
regardless of content quality, which skews the benchmark. Fixing this
requires each post's author's follower count — but LinkedIn exposes that
very differently for personal profiles vs. company/business pages, and only
one of the two actually needs a paid scrape:

  - Business/company authors: the post-search scraper ALREADY returns the
    follower count for free, as plain text in ``author["info"]``
    (e.g. ``"2,402 followers"``) — confirmed against real scraped data.
    No second scraper call is ever needed for these.
  - Personal-profile authors: ``author["info"]`` is a headline/position
    string instead (e.g. ``"Recruitment @ Revolut | Strategy & Ops"``), not
    a follower count. These DO need a real profile scrape
    (``scrapers/linkedin_profile_scraper.py``, backed by the
    ``harvestapi/linkedin-profile-scraper`` Apify actor) to get their
    follower count.

Classifying every author up front means the paid profile scraper is only
ever called for the authors that actually need it — never wasted on
business pages whose follower count we already have for free.

This module classifies authors and merges follower counts onto raw posts.
Follower-normalized engagement is computed downstream by
``processors/run_pipeline.py`` (``--with-profile-enrichment``) and
``processors/benchmark.py`` (``add_audience_adjusted_benchmark``). Profile
rows are cached in the ``profiles`` table via ``storage/profile_store.py``.
"""

import re
from typing import Any, Literal, Optional
from urllib.parse import urlparse

# Matches the "info" text LinkedIn shows for company/business pages instead
# of a headline, e.g. "2,402 followers", "5,474,846 followers", "2 followers".
_FOLLOWERS_TEXT_RE = re.compile(r"^([\d,]+)\+?\s*followers?$", re.IGNORECASE)

# Curated whitelist of scalar fields to keep from a harvestapi profile
# scrape result. Everything else (experience, education, skills,
# certifications, projects, volunteering, courses, publications, patents,
# honorsAndAwards, languages, moreProfiles, receivedRecommendations,
# featured, query/status/entityId/requestId) is deliberately dropped per
# spec: only follower count + the author's own activity data is wanted,
# not their other posts / LinkedIn's suggested-profiles data.
_PROFILE_FIELD_MAP = {
    "connectionsCount": "connections_count",
    "headline": "headline",
    "openToWork": "open_to_work",
    "hiring": "hiring",
    "premium": "premium",
    "influencer": "influencer",
    "verified": "verified",
}

# location is nested one level (location.linkedinText) in harvestapi's
# output, so it's handled separately from the flat _PROFILE_FIELD_MAP above.
_LOCATION_OUTPUT_KEY = "location_text"


def classify_author(post: dict[str, Any]) -> Literal["personal", "company"]:
    """Return "personal" or "company" for the post's author.

    Primary signal: ``author["type"]`` ("profile" or "company"), which the
    post-search scraper already provides directly — 100% reliable, no
    trial-and-error scraping needed. Falls back to a regex check on
    ``author["info"]`` (does it look like "<N> followers"?) only if `type`
    is missing or an unrecognised value, in case a future scrape/actor
    variant omits it.
    """
    author = post.get("author") or {}
    author_type = author.get("type")
    if author_type == "company":
        return "company"
    if author_type == "profile":
        return "personal"

    info = author.get("info") or ""
    if _FOLLOWERS_TEXT_RE.match(info.strip()):
        return "company"
    return "personal"


def _parse_follower_count(text: str) -> Optional[int]:
    """Parse "2,402 followers" -> 2402. Returns None if it doesn't match."""
    match = _FOLLOWERS_TEXT_RE.match((text or "").strip())
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def extract_company_follower_count(post: dict[str, Any]) -> Optional[int]:
    """Free follower count for a company-authored post, parsed from
    ``author["info"]``. Returns None if the author isn't a company, or the
    text doesn't match the expected "<N> followers" shape.
    """
    if classify_author(post) != "company":
        return None
    author = post.get("author") or {}
    return _parse_follower_count(author.get("info") or "")


def clean_profile_url(url: str) -> str:
    """Strip query string/fragment junk (e.g. "?miniProfileUrn=...") from a
    LinkedIn profile URL so it's a clean input for the profile scraper.
    """
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def collect_personal_profile_urls(posts: list[dict[str, Any]]) -> list[str]:
    """Return a sorted, deduplicated list of cleaned profile URLs for every
    PERSONAL-profile author found in `posts`. Company authors are excluded
    on purpose — they never need the paid profile scraper.
    """
    urls = {
        clean_profile_url(url)
        for post in posts
        if classify_author(post) == "personal"
        for url in [(post.get("author") or {}).get("linkedinUrl") or ""]
        if url
    }
    return sorted(urls)


def _match_profile_record(
    post: dict[str, Any], profile_records: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """Find the harvestapi profile record matching this post's author.

    Matches on publicIdentifier first (most reliable), falling back to a
    cleaned-linkedinUrl match if publicIdentifier is missing on either side.

    Both raw URLs must be non-empty BEFORE cleaning — ``clean_profile_url("")``
    returns the sentinel ``"://"`` for both a missing post author URL and a
    missing profile record URL, which would otherwise false-positive-match
    any post lacking ``author.linkedinUrl`` against any profile record
    lacking ``linkedinUrl`` (confirmed via a real test regression).
    """
    author = post.get("author") or {}
    public_id = author.get("publicIdentifier")
    raw_author_url = author.get("linkedinUrl") or ""
    author_url = clean_profile_url(raw_author_url) if raw_author_url else ""

    for record in profile_records:
        if public_id and record.get("publicIdentifier") == public_id:
            return record
        if not author_url:
            continue
        raw_record_url = record.get("linkedinUrl") or ""
        if raw_record_url and clean_profile_url(raw_record_url) == author_url:
            return record
    return None


def enrich_posts_with_follower_data(
    posts: list[dict[str, Any]], profile_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return a NEW list of posts, each with follower/author-activity data
    merged in. Never mutates `posts` or its dicts.

    Added fields on every record:
        is_business: bool
        follower_count: Optional[int]
        connections_count, headline, location_text, open_to_work, hiring,
        premium, influencer, verified: Optional[...] — only ever populated
            for personal authors matched in `profile_records`; always None
            for company authors (not scraped, by design — free savings).
    """
    enriched = []
    for post in posts:
        is_business = classify_author(post) == "company"
        record = {**post, "is_business": is_business}

        for output_key in _PROFILE_FIELD_MAP.values():
            record[output_key] = None
        record[_LOCATION_OUTPUT_KEY] = None

        if is_business:
            record["follower_count"] = extract_company_follower_count(post)
        else:
            matched = _match_profile_record(post, profile_records)
            record["follower_count"] = matched.get("followerCount") if matched else None
            if matched:
                for source_key, output_key in _PROFILE_FIELD_MAP.items():
                    record[output_key] = matched.get(source_key)
                record[_LOCATION_OUTPUT_KEY] = (matched.get("location") or {}).get("linkedinText")

        enriched.append(record)

    return enriched
