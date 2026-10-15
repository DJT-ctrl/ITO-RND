"""Unit tests for company LinkedIn search, scraping, and corpus collection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from processors.company_collector import (
    _clean_linkedin_company_url,
    is_linkedin_url,
    parse_bulk_company_input,
    resolve_company_urls,
    run_company_corpus_flow,
)


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(
        apify_api_token="test_token",
        apify_actor_id="harvestapi/linkedin-post-search",
        apify_profile_actor_id="harvestapi/linkedin-profile-scraper",
        linkedin_cookies=[],
        gemini_api_key="test_gemini_key",
        raw_data_dir="data/raw",
        default_search_limit=10,
        database_url="",
    )


def test_parse_bulk_company_input():
    raw = """
    # Comment
    Stripe
    OpenAI, Anthropic
    https://www.linkedin.com/company/microsoft
    
    stripe
    """
    parsed = parse_bulk_company_input(raw)
    assert "Stripe" in parsed or "stripe" in parsed
    assert "OpenAI" in parsed
    assert "Anthropic" in parsed
    assert "https://www.linkedin.com/company/microsoft" in parsed
    # Duplicates removed (case insensitive)
    assert len(parsed) == 4


def test_clean_linkedin_company_url():
    url1, slug1 = _clean_linkedin_company_url("https://www.linkedin.com/company/stripe/")
    assert url1 == "https://www.linkedin.com/company/stripe"
    assert slug1 == "stripe"

    url2, slug2 = _clean_linkedin_company_url("linkedin.com/company/weights-and-biases?trk=biz")
    assert url2 == "https://www.linkedin.com/company/weights-and-biases"
    assert slug2 == "weights-and-biases"


def test_is_linkedin_url():
    assert is_linkedin_url("https://www.linkedin.com/company/stripe")
    assert is_linkedin_url("linkedin.com/company/openai")
    assert not is_linkedin_url("Stripe Inc")
    assert not is_linkedin_url("Weights & Biases")


def test_resolve_company_urls_direct(mock_settings):
    inputs = ["https://www.linkedin.com/company/stripe"]
    results = resolve_company_urls(inputs, settings=mock_settings)
    assert len(results) == 1
    assert results[0].status == "provided_url"
    assert results[0].slug == "stripe"
    assert results[0].linkedin_url == "https://www.linkedin.com/company/stripe"


@patch("processors.company_collector.genai.Client")
def test_resolve_company_urls_gemini(mock_client_cls, mock_settings):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_resp = MagicMock()
    mock_resp.text = """
    {
      "companies": [
        {
          "input": "Weights & Biases",
          "company_name": "Weights & Biases",
          "linkedin_url": "https://www.linkedin.com/company/wandb",
          "slug": "wandb",
          "confidence": "high"
        }
      ]
    }
    """
    mock_client.models.generate_content.return_value = mock_resp

    inputs = ["Weights & Biases"]
    results = resolve_company_urls(inputs, settings=mock_settings)
    assert len(results) == 1
    assert results[0].status == "resolved"
    assert results[0].slug == "wandb"
    assert results[0].linkedin_url == "https://www.linkedin.com/company/wandb"


@patch("processors.company_collector.resolve_company_urls")
@patch("processors.company_collector.scrape_company_posts")
@patch("processors.company_collector.ingest_company_posts_to_corpus")
def test_run_company_corpus_flow_success(mock_ingest, mock_scrape, mock_resolve, mock_settings, tmp_path):
    from processors.company_collector import CompanyResolvedItem, CompanyScrapeResult

    mock_resolve.return_value = [
        CompanyResolvedItem(
            input_text="Stripe",
            company_name="Stripe",
            linkedin_url="https://www.linkedin.com/company/stripe",
            slug="stripe",
        )
    ]
    raw_path = tmp_path / "linkedin_20260828T120000Z.json"
    raw_path.write_text("[]")

    mock_scrape.return_value = CompanyScrapeResult(
        raw_posts=[{"id": "urn:li:activity:1", "content": "Test company post content exceeding ten words here"}],
        raw_file_path=raw_path,
        total_cost_usd=0.01,
    )
    mock_ingest.return_value = (1, tmp_path / "analysed.jsonl", tmp_path / "embed.npy")

    res = run_company_corpus_flow(["Stripe"], max_posts_per_company=10, settings=mock_settings)
    assert res.status == "success"
    assert res.total_posts_scraped == 1
    assert res.total_posts_ingested == 1


@patch("processors.company_collector.urllib.request.urlopen")
def test_verify_linkedin_company_url_success(mock_urlopen):
    from processors.company_collector import verify_linkedin_company_url

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    exists, desc = verify_linkedin_company_url("https://www.linkedin.com/company/stripe")
    assert exists is True
    assert "Live" in desc


@patch("processors.company_collector.urllib.request.urlopen")
def test_verify_linkedin_company_url_404(mock_urlopen):
    import urllib.error
    from processors.company_collector import verify_linkedin_company_url

    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="https://www.linkedin.com/company/fake",
        code=404,
        msg="Not Found",
        hdrs={},
        fp=None,
    )

    exists, desc = verify_linkedin_company_url("https://www.linkedin.com/company/fake")
    assert exists is False
    assert "404" in desc


@patch("processors.company_collector.LinkedInPostUrlScraper")
def test_scrape_company_posts_filename(mock_scraper_cls, mock_settings, tmp_path):
    import dataclasses
    from processors.company_collector import scrape_company_posts
    from scrapers.result import ScrapeResult

    settings = dataclasses.replace(mock_settings, raw_data_dir=str(tmp_path))
    mock_instance = MagicMock()
    mock_instance.fetch_posts_by_urls.return_value = ScrapeResult(
        items=[
            {
                "id": "urn:li:activity:101",
                "content": "Company post text",
                "author": {"linkedinUrl": "https://www.linkedin.com/company/stripe"},
            }
        ],
    )
    mock_scraper_cls.return_value = mock_instance

    res = scrape_company_posts(
        ["https://www.linkedin.com/company/stripe"],
        max_posts_per_company=10,
        settings=settings,
    )
    assert res.raw_file_path is not None
    assert res.raw_file_path.name.startswith("linkedin_company_")
    assert res.raw_file_path.name.endswith(".json")
    assert res.raw_file_path.exists()


