"""Company LinkedIn search, bulk post scraping, and pgvector corpus ingestion.

Enables searching company names, discovering their official LinkedIn company URLs,
verifying their live existence on LinkedIn, manually reviewing/approving them,
scraping their 10 most recent posts via Apify, and directly ingesting them into
the Postgres/pgvector similarity corpus.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from google import genai
from google.genai import types as genai_types

from config.paths import resolve_data_path, utc_artifact_stamp
from config.settings import GEMINI_MODEL, Settings, load_settings
from processors.embedder import embed_batch, save_embeddings
from processors.gemini_retry import call_with_gemini_retry
from processors.run_db_ingest import ingest_embedded_records
from processors.run_embeddings import load_and_join
from processors.run_pipeline import run_pipeline
from scrapers.linkedin_post_url_scraper import LinkedInPostUrlScraper
from scrapers.result import ScrapeResult
from storage.pipeline_registry import (
    register_embeddings_bundle,
    register_scrape_bundle,
)
from storage.sample_store import SampleStore
from telemetry.apify_schemas import ApifyRunRecord
from telemetry.pricing import cost_from_tokens

logger = logging.getLogger(__name__)

_COMPANY_RESOLVE_PROMPT = """You are an expert LinkedIn researcher.
Given a list of company names, return the exact official canonical LinkedIn Company Page URL and slug for each company.

Rules:
- The URL format MUST be: https://www.linkedin.com/company/<slug>
- Use the actual well-known LinkedIn company handle (e.g. "Weights & Biases" -> "https://www.linkedin.com/company/wandb", "OpenAI" -> "https://www.linkedin.com/company/openai", "Stripe" -> "https://www.linkedin.com/company/stripe").
- If unsure of the exact handle, provide your best canonical guess with slug in lowercase alphanumeric and hyphens only.
- Output JSON ONLY in the following exact format:
{{
  "companies": [
    {{
      "input": "string original input",
      "company_name": "cleaned canonical name",
      "linkedin_url": "https://www.linkedin.com/company/slug",
      "slug": "slug",
      "confidence": "high" | "medium" | "low"
    }}
  ]
}}

Companies to resolve:
{company_items}
"""


@dataclass
class CompanyResolvedItem:
    input_text: str
    company_name: str
    linkedin_url: str
    slug: str
    confidence: str = "high"
    status: str = "resolved"  # "resolved" | "provided_url" | "failed"
    notes: str = ""
    exists_on_linkedin: bool = True
    http_status: str = "Verified"
    approved: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "exists_on_linkedin": self.exists_on_linkedin,
            "http_status": self.http_status,
            "input_text": self.input_text,
            "company_name": self.company_name,
            "linkedin_url": self.linkedin_url,
            "slug": self.slug,
            "confidence": self.confidence,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass
class CompanyScrapeResult:
    raw_posts: list[dict[str, Any]]
    raw_file_path: Optional[Path]
    apify_runs: list[ApifyRunRecord] = field(default_factory=list)
    total_cost_usd: float = 0.0
    posts_by_company: dict[str, int] = field(default_factory=dict)
    zero_post_companies: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class CompanyCorpusResult:
    resolved_companies: list[CompanyResolvedItem]
    total_posts_scraped: int = 0
    total_posts_ingested: int = 0
    raw_file_path: Optional[str] = None
    analysed_jsonl: Optional[str] = None
    embeddings_path: Optional[str] = None
    apify_cost_usd: float = 0.0
    gemini_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)
    status: str = "success"


def _clean_linkedin_company_url(raw_url: str) -> tuple[str, str]:
    """Clean a LinkedIn company URL and extract its slug.

    Returns (canonical_url, slug).
    """
    raw = raw_url.strip()
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = "https://" + raw

    parsed = urlparse(raw)
    path = parsed.path.rstrip("/")
    match = re.search(r"/company/([^/?#]+)", path, re.IGNORECASE)
    if match:
        slug = match.group(1).lower()
        return f"https://www.linkedin.com/company/{slug}", slug

    # If it has linkedin.com with another format or just slug
    parts = [p for p in path.split("/") if p]
    if parts:
        slug = parts[-1].lower()
        return f"https://www.linkedin.com/company/{slug}", slug

    return raw, ""


def is_linkedin_url(text: str) -> bool:
    """Check if text is already a LinkedIn URL."""
    lowered = text.strip().lower()
    return "linkedin.com" in lowered or lowered.startswith("http://") or lowered.startswith("https://")


def parse_bulk_company_input(raw_input: str | list[str]) -> list[str]:
    """Parse bulk line-separated or comma-separated company names/URLs."""
    if isinstance(raw_input, str):
        lines = raw_input.splitlines()
    else:
        lines = list(raw_input)

    items: list[str] = []
    seen: set[str] = set()
    for line in lines:
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        # Split by comma if no newlines were present or if comma-separated
        subparts = [p.strip() for p in cleaned.split(",") if p.strip()] if "," in cleaned and not is_linkedin_url(cleaned) else [cleaned]
        for item in subparts:
            key = item.lower()
            if key not in seen:
                seen.add(key)
                items.append(item)
    return items


def verify_linkedin_company_url(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Check if a LinkedIn company URL exists (200 / 999 = Exists, 404 = Not Found)."""
    if not url or not url.strip():
        return False, "Empty URL"
    cleaned = url.strip()
    if not cleaned.startswith("http://") and not cleaned.startswith("https://"):
        cleaned = "https://" + cleaned

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = urllib.request.Request(cleaned, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            if res.status == 200:
                return True, "Live (200 OK)"
            return True, f"Live ({res.status})"
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, "Not Found (404)"
        # LinkedIn returns 999 or 403 or 429 when protecting pages, but the page exists
        return True, f"Active ({exc.code})"
    except urllib.error.URLError as exc:
        return False, f"Connection error ({exc.reason})"
    except Exception as exc:
        return False, f"Check failed ({exc})"


def verify_company_urls_batch(
    urls: list[str], max_workers: int = 10, timeout: float = 5.0
) -> dict[str, tuple[bool, str]]:
    """Verify multiple LinkedIn company URLs in parallel."""
    results: dict[str, tuple[bool, str]] = {}
    if not urls:
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as executor:
        future_to_url = {
            executor.submit(verify_linkedin_company_url, url, timeout): url
            for url in urls
        }
        for future in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[future]
            try:
                exists, detail = future.result()
                results[url] = (exists, detail)
            except Exception as exc:
                results[url] = (False, str(exc))
    return results


def resolve_company_urls(
    company_inputs: list[str],
    settings: Optional[Settings] = None,
    verify_online: bool = True,
) -> list[CompanyResolvedItem]:
    """Resolve a list of company names or URLs to canonical LinkedIn company URLs."""
    settings = settings or load_settings()
    results: list[CompanyResolvedItem] = []
    need_gemini: list[str] = []

    for item in company_inputs:
        cleaned = item.strip()
        if not cleaned:
            continue

        if is_linkedin_url(cleaned):
            canon_url, slug = _clean_linkedin_company_url(cleaned)
            name = slug.replace("-", " ").title() if slug else cleaned
            results.append(
                CompanyResolvedItem(
                    input_text=cleaned,
                    company_name=name,
                    linkedin_url=canon_url,
                    slug=slug,
                    confidence="high",
                    status="provided_url",
                    notes="Direct LinkedIn URL provided",
                )
            )
        else:
            need_gemini.append(cleaned)

    if need_gemini:
        if not settings.gemini_api_key:
            for name in need_gemini:
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
                url = f"https://www.linkedin.com/company/{slug}"
                results.append(
                    CompanyResolvedItem(
                        input_text=name,
                        company_name=name,
                        linkedin_url=url,
                        slug=slug,
                        confidence="medium",
                        status="resolved",
                        notes="Heuristic slug (GEMINI_API_KEY not configured)",
                    )
                )
        else:
            client = genai.Client(api_key=settings.gemini_api_key)
            company_list_text = "\n".join(f"- {name}" for name in need_gemini)
            prompt = _COMPANY_RESOLVE_PROMPT.format(company_items=company_list_text)

            def _call():
                return client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )

            try:
                response = call_with_gemini_retry(_call, label="Company LinkedIn URL resolution")
                text = getattr(response, "text", "") or ""
                parsed = json.loads(text) if text else {}
                companies_data = parsed.get("companies", [])
                resolved_by_input = {c.get("input", "").strip().lower(): c for c in companies_data if isinstance(c, dict)}

                for name in need_gemini:
                    match = resolved_by_input.get(name.lower())
                    if match and match.get("linkedin_url"):
                        url, slug = _clean_linkedin_company_url(match["linkedin_url"])
                        results.append(
                            CompanyResolvedItem(
                                input_text=name,
                                company_name=match.get("company_name") or name,
                                linkedin_url=url,
                                slug=slug or match.get("slug", ""),
                                confidence=match.get("confidence", "high"),
                                status="resolved",
                                notes=f"Resolved via Gemini ({match.get('confidence', 'high')} confidence)",
                            )
                        )
                    else:
                        slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
                        url = f"https://www.linkedin.com/company/{slug}"
                        results.append(
                            CompanyResolvedItem(
                                input_text=name,
                                company_name=name,
                                linkedin_url=url,
                                slug=slug,
                                confidence="medium",
                                status="resolved",
                                notes="Heuristic fallback",
                            )
                        )
            except Exception as exc:
                logger.warning("Gemini company resolution error: %s", exc)
                for name in need_gemini:
                    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
                    url = f"https://www.linkedin.com/company/{slug}"
                    results.append(
                        CompanyResolvedItem(
                            input_text=name,
                            company_name=name,
                            linkedin_url=url,
                            slug=slug,
                            confidence="low",
                            status="resolved",
                            notes=f"Fallback slug: {exc}",
                        )
                    )

    # Perform parallel existence check if requested
    if verify_online and results:
        urls_to_check = [r.linkedin_url for r in results if r.linkedin_url]
        verification_map = verify_company_urls_batch(urls_to_check)
        for r in results:
            if r.linkedin_url in verification_map:
                exists, http_desc = verification_map[r.linkedin_url]
                r.exists_on_linkedin = exists
                r.http_status = http_desc
                r.approved = exists

    return results


def scrape_company_posts(
    company_urls: list[str],
    max_posts_per_company: int = 10,
    settings: Optional[Settings] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> CompanyScrapeResult:
    """Scrape recent posts for a list of company LinkedIn URLs via Apify."""
    settings = settings or load_settings()
    if not settings.apify_api_token:
        raise ValueError("APIFY_API_TOKEN is not set (check your .env file).")

    cleaned_urls = [u.strip() for u in company_urls if u and u.strip()]
    if not cleaned_urls:
        return CompanyScrapeResult(raw_posts=[], raw_file_path=None)

    if on_progress:
        on_progress(
            f"Calling Apify ({settings.apify_post_url_actor_id}) for {len(cleaned_urls)} "
            f"company URL(s), up to {max_posts_per_company} posts each..."
        )

    scraper = LinkedInPostUrlScraper(settings)
    scrape_result = scraper.fetch_posts_by_urls(
        cleaned_urls,
        max_posts=max_posts_per_company,
        context="company_corpus_collector",
        persist_telemetry=True,
    )

    posts = list(scrape_result.items)
    runs = [scrape_result.run_record] if scrape_result.run_record else []
    total_cost = sum(r.cost_usd for r in runs)

    # Compute posts found per company
    posts_by_company: dict[str, int] = {u: 0 for u in cleaned_urls}
    for post in posts:
        author = post.get("author") or {}
        author_url = (author.get("linkedinUrl") or "").lower()
        author_slug = (author.get("publicIdentifier") or author.get("universalName") or "").lower()
        for target_url in cleaned_urls:
            _, target_slug = _clean_linkedin_company_url(target_url)
            target_slug_lower = target_slug.lower()
            if (target_slug_lower and target_slug_lower in author_url) or (author_slug and target_slug_lower == author_slug):
                posts_by_company[target_url] += 1
                break

    zero_post_companies = [u for u, count in posts_by_company.items() if count == 0]
    warnings: list[str] = []
    if zero_post_companies:
        names = [u.rstrip("/").split("/")[-1].replace("-", " ").title() for u in zero_post_companies]
        warnings.append(
            f"{len(zero_post_companies)} company(ies) had no public posts on LinkedIn: {', '.join(names)}"
        )

    if not posts:
        return CompanyScrapeResult(
            raw_posts=[],
            raw_file_path=None,
            apify_runs=runs,
            total_cost_usd=total_cost,
            posts_by_company=posts_by_company,
            zero_post_companies=zero_post_companies,
            warnings=warnings,
            errors=["No posts returned by Apify for the given company URLs."],
        )

    # Save raw posts
    store = SampleStore(settings.raw_data_dir)
    ts = utc_artifact_stamp()
    raw_path = store.save("linkedin_company", posts, timestamp=ts)

    # Register in pipeline manifest
    register_scrape_bundle(
        bundle_id=ts,
        source_scans=[raw_path.name],
        post_count=len(posts),
    )

    if on_progress:
        on_progress(f"Scraped {len(posts)} post(s) from {len(cleaned_urls)} companies. Saved to `{raw_path.name}`.")

    return CompanyScrapeResult(
        raw_posts=posts,
        raw_file_path=raw_path,
        apify_runs=runs,
        total_cost_usd=total_cost,
        posts_by_company=posts_by_company,
        zero_post_companies=zero_post_companies,
        warnings=warnings,
    )


def ingest_company_posts_to_corpus(
    raw_posts: list[dict[str, Any]],
    source_scan_name: str,
    settings: Optional[Settings] = None,
    with_gemini: bool = True,
    on_progress: Optional[Callable[[str], None]] = None,
) -> tuple[int, Path, Path]:
    """Run normalisation, embedding, and vector DB ingestion for scraped company posts.

    Returns:
        (ingested_count, analysed_jsonl_path, embeddings_npy_path)
    """
    settings = settings or load_settings()
    if not raw_posts:
        raise ValueError("No posts provided to ingest into corpus.")

    if on_progress:
        on_progress(f"Normalising {len(raw_posts)} post(s) (Stage 1 {'+ Gemini Stage 2' if with_gemini else ''})...")

    # 1. Run pipeline analysis on these specific raw posts
    csv_path, jsonl_path = run_pipeline(
        raw_posts=raw_posts,
        source_scans=[source_scan_name],
        with_gemini=with_gemini,
        settings=settings,
    )

    if on_progress:
        on_progress(f"Generating Gemini embeddings for {jsonl_path.name}...")

    # 2. Load and join content
    joined_records, _, _ = load_and_join(
        processed_file=str(jsonl_path),
        settings=settings,
    )

    eligible = [
        r for r in joined_records
        if (r.get("content") or "").strip() and r.get("word_count", 0) >= 10
    ]

    if not eligible:
        raise ValueError("No eligible posts with content >= 10 words found to embed.")

    # 3. Generate embeddings
    vectors, skipped = embed_batch(eligible, settings)
    npy_path = save_embeddings(vectors, "linkedin")

    bundle_id = jsonl_path.stem.replace("linkedin_analysed_", "")
    register_embeddings_bundle(
        bundle_id=bundle_id,
        embeddings_npy=str(npy_path),
        embedding_post_ids=[r["post_id"] for r in eligible],
        source_jsonl=jsonl_path.name,
    )

    # 4. Ingest into Postgres
    ingested_count = 0
    if settings.database_url:
        if on_progress:
            on_progress(f"Upserting {len(eligible)} post(s) into Postgres vector database...")
        ingested_count = ingest_embedded_records(
            eligible,
            vectors,
            settings=settings,
            bundle_id=bundle_id,
            skip_backup=True,
        )

    return ingested_count, jsonl_path, npy_path


def run_company_corpus_flow(
    company_inputs: list[str],
    max_posts_per_company: int = 10,
    settings: Optional[Settings] = None,
    with_gemini: bool = True,
    on_progress: Optional[Callable[[str], None]] = None,
) -> CompanyCorpusResult:
    """End-to-end flow: Resolve company URLs -> Scrape posts -> Ingest into vector DB."""
    settings = settings or load_settings()

    # Step 1: Resolve URLs
    if on_progress:
        on_progress(f"Resolving {len(company_inputs)} company name(s) and verifying on LinkedIn...")
    resolved = resolve_company_urls(company_inputs, settings, verify_online=True)

    valid_urls = [r.linkedin_url for r in resolved if r.linkedin_url and r.approved]
    if not valid_urls:
        return CompanyCorpusResult(
            resolved_companies=resolved,
            status="error",
            errors=["No approved LinkedIn company URLs to scrape."],
        )

    # Step 2: Scrape posts
    scrape_res = scrape_company_posts(
        valid_urls,
        max_posts_per_company=max_posts_per_company,
        settings=settings,
        on_progress=on_progress,
    )

    if not scrape_res.raw_posts or not scrape_res.raw_file_path:
        return CompanyCorpusResult(
            resolved_companies=resolved,
            apify_cost_usd=scrape_res.total_cost_usd,
            status="error",
            errors=scrape_res.errors or ["Scrape returned zero posts."],
        )

    # Step 3: Normalise, Embed & Ingest
    try:
        ingested_count, jsonl_path, npy_path = ingest_company_posts_to_corpus(
            raw_posts=scrape_res.raw_posts,
            source_scan_name=scrape_res.raw_file_path.name,
            settings=settings,
            with_gemini=with_gemini,
            on_progress=on_progress,
        )
    except Exception as exc:
        logger.exception("Ingestion failed: %s", exc)
        return CompanyCorpusResult(
            resolved_companies=resolved,
            total_posts_scraped=len(scrape_res.raw_posts),
            raw_file_path=str(scrape_res.raw_file_path),
            apify_cost_usd=scrape_res.total_cost_usd,
            status="partial_error",
            errors=[f"Ingest into corpus failed: {exc}"],
        )

    if on_progress:
        on_progress(
            f"Successfully added {ingested_count} company posts into the corpus!"
        )

    return CompanyCorpusResult(
        resolved_companies=resolved,
        total_posts_scraped=len(scrape_res.raw_posts),
        total_posts_ingested=ingested_count,
        raw_file_path=str(scrape_res.raw_file_path),
        analysed_jsonl=str(jsonl_path),
        embeddings_path=str(npy_path),
        apify_cost_usd=scrape_res.total_cost_usd,
        status="success",
    )
