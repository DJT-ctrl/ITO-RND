"""Unit tests for processors/profile_enricher.py (T6 Point 1: author
follower enrichment, standalone from the main NormalizedPost pipeline).
"""

from processors.profile_enricher import (
    classify_author,
    clean_profile_url,
    collect_personal_profile_urls,
    enrich_posts_with_follower_data,
    extract_company_follower_count,
)


def _post(
    post_id: str = "1",
    author_type: str = "profile",
    public_identifier: str = "helena-vilches",
    universal_name: str = None,
    info: str = "Recruitment @ Revolut | Strategy & Operations",
    linkedin_url: str = "https://www.linkedin.com/in/helena-vilches?miniProfileUrn=urn%3Ali",
    author_name: str = "Helena Vilches",
) -> dict:
    return {
        "id": post_id,
        "linkedinUrl": f"https://www.linkedin.com/posts/{post_id}",
        "author": {
            "type": author_type,
            "publicIdentifier": public_identifier,
            "universalName": universal_name,
            "info": info,
            "linkedinUrl": linkedin_url,
            "name": author_name,
        },
    }


# ── classify_author ──────────────────────────────────────────────────────────

def test_classify_author_personal_from_type():
    assert classify_author(_post(author_type="profile")) == "personal"


def test_classify_author_company_from_type():
    post = _post(
        author_type="company",
        public_identifier=None,
        universal_name="fintechnewsph",
        info="2,402 followers",
    )
    assert classify_author(post) == "company"


def test_classify_author_falls_back_to_info_regex_when_type_missing():
    post = _post(author_type=None, info="5,474,846 followers")
    del post["author"]["type"]
    assert classify_author(post) == "company"


def test_classify_author_falls_back_to_personal_when_type_missing_and_info_is_headline():
    post = _post(author_type=None, info="Founder at Acme")
    del post["author"]["type"]
    assert classify_author(post) == "personal"


def test_classify_author_missing_author_defaults_to_personal():
    assert classify_author({"id": "1"}) == "personal"


# ── extract_company_follower_count ───────────────────────────────────────────

def test_extract_company_follower_count_real_example_small():
    post = _post(author_type="company", info="2,402 followers")
    assert extract_company_follower_count(post) == 2402


def test_extract_company_follower_count_real_example_large():
    post = _post(author_type="company", info="5,474,846 followers")
    assert extract_company_follower_count(post) == 5474846


def test_extract_company_follower_count_singular_follower():
    post = _post(author_type="company", info="1 follower")
    assert extract_company_follower_count(post) == 1


def test_extract_company_follower_count_none_for_personal_author():
    post = _post(author_type="profile", info="Recruitment @ Revolut")
    assert extract_company_follower_count(post) is None


# ── clean_profile_url ────────────────────────────────────────────────────────

def test_clean_profile_url_strips_query_params():
    url = "https://www.linkedin.com/in/helena-vilches?miniProfileUrn=urn%3Ali%3Afsd_profile"
    assert clean_profile_url(url) == "https://www.linkedin.com/in/helena-vilches"


def test_clean_profile_url_leaves_clean_url_unchanged():
    url = "https://www.linkedin.com/in/towhid-rahman"
    assert clean_profile_url(url) == url


def test_clean_profile_url_empty_string():
    assert clean_profile_url("") == "://"


# ── collect_personal_profile_urls ────────────────────────────────────────────

def test_collect_personal_profile_urls_excludes_business_authors():
    posts = [
        _post(post_id="1", author_type="profile", linkedin_url="https://www.linkedin.com/in/alice"),
        _post(post_id="2", author_type="company", linkedin_url="https://www.linkedin.com/company/acme/posts"),
    ]
    assert collect_personal_profile_urls(posts) == ["https://www.linkedin.com/in/alice"]


def test_collect_personal_profile_urls_dedups_and_cleans():
    posts = [
        _post(
            post_id="1",
            linkedin_url="https://www.linkedin.com/in/alice?miniProfileUrn=urn%3Ali%3A1",
        ),
        _post(
            post_id="2",
            linkedin_url="https://www.linkedin.com/in/alice?miniProfileUrn=urn%3Ali%3A2",
        ),
    ]
    assert collect_personal_profile_urls(posts) == ["https://www.linkedin.com/in/alice"]


def test_collect_personal_profile_urls_empty_input():
    assert collect_personal_profile_urls([]) == []


# ── enrich_posts_with_follower_data ───────────────────────────────────────────

def test_enrich_business_post_uses_free_parse_no_profile_records_needed():
    posts = [
        _post(
            post_id="1",
            author_type="company",
            public_identifier=None,
            universal_name="fintechnewsph",
            info="2,402 followers",
        )
    ]
    enriched = enrich_posts_with_follower_data(posts, [])
    assert enriched[0]["is_business"] is True
    assert enriched[0]["follower_count"] == 2402
    # Personal-only fields stay None for business authors — not scraped.
    assert enriched[0]["headline"] is None
    assert enriched[0]["connections_count"] is None


def test_enrich_personal_post_matches_profile_record_by_public_identifier():
    posts = [_post(post_id="1", author_type="profile", public_identifier="helena-vilches")]
    profile_records = [
        {
            "publicIdentifier": "helena-vilches",
            "linkedinUrl": "https://www.linkedin.com/in/helena-vilches",
            "followerCount": 500,
            "connectionsCount": 300,
            "headline": "Recruitment @ Revolut",
            "openToWork": False,
            "hiring": True,
            "premium": True,
            "influencer": False,
            "verified": True,
            "location": {"linkedinText": "Dublin, Ireland"},
        }
    ]
    enriched = enrich_posts_with_follower_data(posts, profile_records)
    record = enriched[0]
    assert record["is_business"] is False
    assert record["follower_count"] == 500
    assert record["connections_count"] == 300
    assert record["headline"] == "Recruitment @ Revolut"
    assert record["location_text"] == "Dublin, Ireland"
    assert record["hiring"] is True
    assert record["verified"] is True


def test_enrich_personal_post_unmatched_gets_none_follower_count():
    posts = [_post(post_id="1", author_type="profile", public_identifier="unknown-person")]
    enriched = enrich_posts_with_follower_data(posts, [])
    assert enriched[0]["is_business"] is False
    assert enriched[0]["follower_count"] is None


def test_enrich_does_not_mutate_input():
    posts = [_post(post_id="1")]
    original_keys = set(posts[0].keys())
    enrich_posts_with_follower_data(posts, [])
    assert set(posts[0].keys()) == original_keys


def test_enrich_does_not_false_positive_match_when_both_urls_are_missing():
    """Regression test: two different personal authors who both lack
    author.linkedinUrl must NOT be matched to the same profile record just
    because clean_profile_url("") collides to the same "://" sentinel for
    both. Only user1 has a matching profile record (by publicIdentifier);
    user2 must stay unmatched."""
    posts = [
        _post(post_id="1", author_type="profile", public_identifier="user1", linkedin_url=""),
        _post(post_id="2", author_type="profile", public_identifier="user2", linkedin_url=""),
    ]
    profile_records = [{"publicIdentifier": "user1", "followerCount": 1000, "linkedinUrl": ""}]

    enriched = enrich_posts_with_follower_data(posts, profile_records)
    by_id = {p["id"]: p for p in enriched}

    assert by_id["1"]["follower_count"] == 1000
    assert by_id["2"]["follower_count"] is None
