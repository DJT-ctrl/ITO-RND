"""Unit tests for processors.keyword_suggestions (no live Apify/Gemini)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from processors.keyword_suggestions import (
    KEYWORD_COUNT,
    _normalize_keywords,
    classify_linkedin_url,
    run_keyword_suggestions,
    summarize_post,
    summarize_profile,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.linkedin.com/in/jane-doe", "profile"),
        ("https://linkedin.com/in/jane-doe/?locale=en", "profile"),
        ("https://www.linkedin.com/posts/jane_activity-123", "post"),
        ("https://www.linkedin.com/feed/update/urn:li:activity:123", "post"),
        ("https://www.linkedin.com/company/barclays-bank/", "company"),
        ("https://www.linkedin.com/company/acme", "company"),
        ("https://example.com/in/fake", "unknown"),
        ("", "unknown"),
    ],
)
def test_classify_linkedin_url(url: str, expected: str) -> None:
    assert classify_linkedin_url(url) == expected


def test_normalize_keywords_dedupes_and_caps() -> None:
    raw = {
        "keywords": [
            "AI SaaS",
            "#ai saas",
            "enterprise IT",
            "  ",
            "cybersecurity",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
        ]
    }
    out = _normalize_keywords(raw, count=KEYWORD_COUNT)
    assert len(out) == KEYWORD_COUNT
    assert out[0] == "AI SaaS"
    assert "ai saas" not in {k.lower() for k in out[1:]}  # duplicate dropped


def test_summarize_profile_keeps_useful_fields() -> None:
    summary = summarize_profile(
        {
            "firstName": "Ada",
            "lastName": "Lovelace",
            "headline": "Math + computing",
            "about": "Notes on the analytical engine " * 200,
            "skills": [{"name": "Mathematics"}, {"name": "Programming"}],
            "experience": [
                {
                    "position": "Analyst",
                    "companyName": "Babbage Lab",
                    "description": "Wrote algorithms",
                }
            ],
            "location": {"linkedinText": "London"},
            "followerCount": 42,
            "linkedinUrl": "https://www.linkedin.com/in/ada",
        }
    )
    assert summary["name"] == "Ada Lovelace"
    assert summary["headline"] == "Math + computing"
    assert summary["skills"] == ["Mathematics", "Programming"]
    assert "Analyst" in summary["recent_experience"][0]
    assert len(summary["about"]) <= 1501


def test_summarize_post() -> None:
    summary = summarize_post(
        {
            "content": "How BBA grads skip the MBA",
            "linkedinUrl": "https://www.linkedin.com/posts/x",
            "author": {
                "name": "Vinod",
                "info": "Sr. SEO Manager",
                "linkedinUrl": "https://www.linkedin.com/in/vinod",
            },
        }
    )
    assert summary["kind"] == "post"
    assert "MBA" in summary["content"]
    assert summary["author_info"] == "Sr. SEO Manager"


def test_summarize_company() -> None:
    from processors.keyword_suggestions import summarize_company

    summary = summarize_company(
        [
            {
                "content": "We're hiring data engineers for retail banking.",
                "author": {
                    "name": "Barclays",
                    "info": "12,345,678 followers",
                    "linkedinUrl": "https://www.linkedin.com/company/barclays-bank",
                    "type": "company",
                },
            },
            {
                "content": "Open banking APIs and fintech partnerships.",
                "author": {"name": "Barclays", "info": "12,345,678 followers"},
            },
        ],
        company_url="https://www.linkedin.com/company/barclays-bank/",
    )
    assert summary["kind"] == "company"
    assert summary["company_name"] == "Barclays"
    assert summary["post_count"] == 2
    assert len(summary["recent_posts"]) == 2
    assert "fintech" in summary["recent_posts"][1]


def test_run_rejects_unknown_url(tmp_path: Path) -> None:
    settings = MagicMock()
    settings.gemini_api_key = "x"
    settings.apify_api_token = "y"
    settings.telemetry_data_dir = str(tmp_path / "telemetry")

    result = run_keyword_suggestions(
        "https://example.com/nope",
        settings=settings,
        persist=True,
    )
    assert result.error
    assert result.keywords == []
    assert result.log_path
    lines = Path(result.log_path).read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[-1])["event"] == "rejected"


def test_run_happy_path_profile(tmp_path: Path) -> None:
    settings = MagicMock()
    settings.gemini_api_key = "fake-key"
    settings.apify_api_token = "fake-token"
    settings.apify_profile_actor_id = "actor/profile"
    settings.telemetry_data_dir = str(tmp_path / "telemetry")

    scrape_items = [
        {
            "firstName": "Ada",
            "lastName": "Lovelace",
            "headline": "AI product founder",
            "about": "Building SaaS for enterprise IT",
            "skills": [{"name": "SaaS"}, {"name": "AI"}],
            "experience": [],
            "linkedinUrl": "https://www.linkedin.com/in/ada",
        }
    ]
    keywords = [f"term {i}" for i in range(KEYWORD_COUNT)]

    fake_result = MagicMock()
    fake_result.items = scrape_items
    fake_result.run_record = MagicMock()
    fake_result.run_record.run_id = "run-1"

    with (
        patch(
            "processors.keyword_suggestions.LinkedInProfileScraper"
        ) as mock_scraper_cls,
        patch(
            "processors.keyword_suggestions.suggest_keywords_from_context",
            return_value=(keywords, "gemini-2.5-flash-lite", 10, 20, 0.001),
        ) as mock_gemini,
        patch(
            "processors.keyword_suggestions.resolve_data_path",
            return_value=tmp_path / "processed",
        ),
    ):
        mock_scraper_cls.return_value.fetch_samples.return_value = fake_result
        result = run_keyword_suggestions(
            "https://www.linkedin.com/in/ada",
            settings=settings,
            persist=True,
        )

    assert result.error is None
    assert result.keywords == keywords
    assert result.keywords_text() == "\n".join(keywords)
    assert result.apify_run_ids == ["run-1"]
    assert len(result.apify_runs) == 1
    assert result.artifact_path
    assert Path(result.artifact_path).exists()
    mock_gemini.assert_called_once()
    assert mock_scraper_cls.return_value.fetch_samples.called
