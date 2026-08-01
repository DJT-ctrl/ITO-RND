"""Suggest corpus search keywords from a LinkedIn profile or post URL.

Scrapes via Apify (profile or post-URL actor), then asks Gemini for exactly
10 LinkedIn search terms that would find similar people / content for the
corpus. Does not write seeds or trigger collection — callers copy the terms.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from google import genai
from google.genai import types as genai_types

from agents.prompt_safety import (
    PROMPT_DATA_PREAMBLE,
    escape_tag_breakout,
    sanitize_known_injection_patterns,
)
from config.paths import resolve_data_path, resolve_telemetry_data_dir, utc_artifact_stamp
from config.settings import GEMINI_MODEL, Settings, load_settings
from processors.gemini_retry import call_with_gemini_retry
from scrapers.linkedin_post_url_scraper import LinkedInPostUrlScraper
from scrapers.linkedin_profile_scraper import LinkedInProfileScraper
from scrapers.result import ScrapeResult
from telemetry.apify_schemas import ApifyRunRecord
from telemetry.pricing import cost_from_tokens

logger = logging.getLogger(__name__)

UrlKind = Literal["profile", "post", "company", "unknown"]

KEYWORD_COUNT = 10
_COMPANY_POST_LIMIT = 8
_LOG_NAME = "keyword_suggestions.jsonl"
_ARTIFACT_DIR = "data/processed"

_PROMPT = """You suggest LinkedIn search keywords for building a content corpus.

Given scraped LinkedIn data (personal profile, company page, or post), return
exactly {count} search keywords that would find similar professionals and posts
on LinkedIn.

Rules:
- Keywords must suit THIS source's niche, industry, and topics.
- For a company page: focus on industry, products/services, and themes in their
  recent posts — not the company brand name itself as a search term.
- Prefer 1–4 word phrases that work as LinkedIn searchQueries.
- Mix role/title terms, industry terms, and topical phrases.
- No hashtags, no URLs, no person names. Avoid company brand names unless they
  are a known product category (e.g. "Salesforce admin").
- Avoid generic filler ("leadership", "innovation", "motivation") unless
  the source is clearly about that.
- Return JSON only: {{"keywords": ["...", ...]}} with exactly {count} strings.

{preamble}
<source_kind>{source_kind}</source_kind>
<source_url>{source_url}</source_url>
<scraped_context>
{context}
</scraped_context>
"""


@dataclass
class KeywordSuggestionResult:
    url: str
    url_kind: UrlKind
    keywords: list[str]
    context_summary: dict[str, Any]
    scrape_item_count: int
    apify_run_ids: list[str] = field(default_factory=list)
    apify_runs: list[ApifyRunRecord] = field(default_factory=list)
    gemini_model: str = ""
    gemini_input_tokens: int = 0
    gemini_output_tokens: int = 0
    gemini_cost_usd: float = 0.0
    artifact_path: Optional[str] = None
    log_path: Optional[str] = None
    error: Optional[str] = None
    recorded_at: str = ""

    def keywords_text(self) -> str:
        """One keyword per line — easy to paste into Collect samples / seeds."""
        return "\n".join(self.keywords)


def classify_linkedin_url(url: str) -> UrlKind:
    """Best-effort classify a LinkedIn URL as profile, company, or post."""
    raw = (url or "").strip()
    if not raw:
        return "unknown"
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    except ValueError:
        return "unknown"
    host = (parsed.netloc or "").lower()
    if "linkedin.com" not in host:
        return "unknown"
    path = (parsed.path or "").lower().rstrip("/")
    if "/company/" in path:
        return "company"
    if "/in/" in path or path.startswith("/pub/"):
        return "profile"
    if any(
        marker in path
        for marker in ("/posts/", "/feed/update/", "/pulse/", "/activity/")
    ):
        return "post"
    return "unknown"


def _safe_text(value: Any, *, limit: int = 1200) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _location_text(location: Any) -> str:
    if isinstance(location, dict):
        return _safe_text(
            location.get("linkedinText")
            or (location.get("parsed") or {}).get("text")
            or ""
        )
    return _safe_text(location)


def summarize_profile(item: dict[str, Any]) -> dict[str, Any]:
    """Compact profile fields for the Gemini prompt (not the full Apify dump)."""
    skills_raw = item.get("skills") or []
    skill_names: list[str] = []
    if isinstance(skills_raw, list):
        for skill in skills_raw[:15]:
            if isinstance(skill, dict) and skill.get("name"):
                skill_names.append(_safe_text(skill["name"], limit=80))
            elif isinstance(skill, str):
                skill_names.append(_safe_text(skill, limit=80))

    experience_bits: list[str] = []
    for exp in (item.get("experience") or [])[:5]:
        if not isinstance(exp, dict):
            continue
        bit = " | ".join(
            part
            for part in (
                _safe_text(exp.get("position"), limit=120),
                _safe_text(exp.get("companyName"), limit=120),
                _safe_text(exp.get("description"), limit=240),
            )
            if part
        )
        if bit:
            experience_bits.append(bit)

    name = " ".join(
        part
        for part in (_safe_text(item.get("firstName"), limit=80), _safe_text(item.get("lastName"), limit=80))
        if part
    ) or _safe_text(item.get("name"), limit=160)

    return {
        "kind": "profile",
        "name": name,
        "headline": _safe_text(item.get("headline"), limit=400),
        "about": _safe_text(item.get("about"), limit=1500),
        "location": _location_text(item.get("location")),
        "follower_count": item.get("followerCount"),
        "skills": skill_names,
        "recent_experience": experience_bits,
        "linkedin_url": _safe_text(item.get("linkedinUrl"), limit=300),
    }


def summarize_post(item: dict[str, Any]) -> dict[str, Any]:
    author = item.get("author") or {}
    return {
        "kind": "post",
        "content": _safe_text(item.get("content"), limit=2500),
        "author_name": _safe_text(author.get("name"), limit=160),
        "author_info": _safe_text(author.get("info") or author.get("headline"), limit=400),
        "author_url": _safe_text(author.get("linkedinUrl"), limit=300),
        "post_url": _safe_text(item.get("linkedinUrl"), limit=300),
    }


def summarize_company(items: list[dict[str, Any]], *, company_url: str = "") -> dict[str, Any]:
    """Summarise a company page from recent posts scraped via the post-URL actor."""
    if not items:
        return {"kind": "company", "empty": True, "company_url": company_url}

    authors = [item.get("author") or {} for item in items]
    company_name = ""
    company_info = ""
    follower_hint = ""
    for author in authors:
        name = _safe_text(author.get("name") or author.get("universalName"), limit=160)
        info = _safe_text(author.get("info") or author.get("headline"), limit=400)
        if name and not company_name:
            company_name = name
        if info and not company_info:
            company_info = info
        if "follower" in info.lower() and not follower_hint:
            follower_hint = info

    recent_posts: list[str] = []
    for item in items[:_COMPANY_POST_LIMIT]:
        content = _safe_text(item.get("content"), limit=600)
        if content:
            recent_posts.append(content)

    return {
        "kind": "company",
        "company_name": company_name,
        "company_info": company_info or follower_hint,
        "company_url": company_url
        or _safe_text((authors[0] if authors else {}).get("linkedinUrl"), limit=300),
        "post_count": len(items),
        "recent_posts": recent_posts,
    }


def _normalize_keywords(raw: Any, *, count: int = KEYWORD_COUNT) -> list[str]:
    if isinstance(raw, dict):
        raw = raw.get("keywords") or raw.get("search_terms") or raw.get("terms")
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        term = re.sub(r"\s+", " ", item).strip().lstrip("#")
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= count:
            break
    return out


def _extract_response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return text.strip()
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                return part_text.strip()
    return ""


def _usage_tokens(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0, 0
    inp = int(
        getattr(usage, "prompt_token_count", None)
        or getattr(usage, "input_tokens", None)
        or 0
    )
    out = int(
        getattr(usage, "candidates_token_count", None)
        or getattr(usage, "output_tokens", None)
        or 0
    )
    return inp, out


def suggest_keywords_from_context(
    context: dict[str, Any],
    *,
    settings: Settings,
    source_url: str,
    source_kind: UrlKind,
    count: int = KEYWORD_COUNT,
) -> tuple[list[str], str, int, int, float]:
    """Call Gemini; returns keywords, model, input tokens, output tokens, cost."""
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set (check your .env file).")

    model = GEMINI_MODEL
    context_json = json.dumps(context, ensure_ascii=False, indent=2)
    safe_context = sanitize_known_injection_patterns(escape_tag_breakout(context_json))
    prompt = _PROMPT.format(
        count=count,
        preamble=PROMPT_DATA_PREAMBLE,
        source_kind=source_kind,
        source_url=sanitize_known_injection_patterns(escape_tag_breakout(source_url)),
        context=safe_context,
    )

    client = genai.Client(api_key=settings.gemini_api_key)
    logger.info(
        "keyword_suggestions gemini request model=%s source_kind=%s url=%s",
        model,
        source_kind,
        source_url,
    )

    def _request() -> Any:
        return client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )

    response = call_with_gemini_retry(_request, label="Gemini keyword suggestions")
    text = _extract_response_text(response)
    inp, out = _usage_tokens(response)
    cost = cost_from_tokens(model, input_tokens=inp, output_tokens=out)
    logger.info(
        "keyword_suggestions gemini response tokens_in=%s tokens_out=%s cost_usd=%.6f raw=%s",
        inp,
        out,
        cost,
        text[:500],
    )

    try:
        parsed = json.loads(text) if text else {}
    except json.JSONDecodeError:
        logger.warning("keyword_suggestions: Gemini returned non-JSON: %s", text[:300])
        parsed = {}

    keywords = _normalize_keywords(parsed, count=count)
    if len(keywords) < count:
        logger.warning(
            "keyword_suggestions: got %s keywords, expected %s",
            len(keywords),
            count,
        )
    return keywords, model, inp, out, cost


def _scrape_url(
    url: str,
    url_kind: UrlKind,
    settings: Settings,
) -> tuple[list[dict[str, Any]], list[ApifyRunRecord]]:
    """Return scraped items and Apify run records (already persisted by scrapers)."""
    runs: list[ApifyRunRecord] = []
    if url_kind == "profile":
        scraper = LinkedInProfileScraper(settings)
        logger.info("keyword_suggestions scraping profile url=%s", url)
        result: ScrapeResult = scraper.fetch_samples(
            {"profileUrls": [url]},
            context="keyword_suggestions:profile",
        )
        if result.run_record is not None:
            runs.append(result.run_record)
        return list(result.items), runs

    if url_kind == "post":
        scraper = LinkedInPostUrlScraper(settings)
        logger.info("keyword_suggestions scraping post url=%s", url)
        result = scraper.fetch_posts_by_urls(
            [url],
            max_posts=1,
            context="keyword_suggestions:post",
        )
        if result.run_record is not None:
            runs.append(result.run_record)
        return list(result.items), runs

    if url_kind == "company":
        # harvestapi/linkedin-profile-posts accepts company URLs in targetUrls
        # and returns recent company posts — enough signal for keyword suggestions.
        scraper = LinkedInPostUrlScraper(settings)
        logger.info(
            "keyword_suggestions scraping company url=%s max_posts=%s",
            url,
            _COMPANY_POST_LIMIT,
        )
        result = scraper.fetch_posts_by_urls(
            [url],
            max_posts=_COMPANY_POST_LIMIT,
            context="keyword_suggestions:company",
        )
        if result.run_record is not None:
            runs.append(result.run_record)
        return list(result.items), runs

    raise ValueError(f"Unsupported LinkedIn URL kind: {url_kind}")


def _build_context(
    items: list[dict[str, Any]],
    url_kind: UrlKind,
    *,
    source_url: str = "",
) -> dict[str, Any]:
    if not items:
        return {"kind": url_kind, "empty": True}
    primary = items[0]
    if url_kind == "profile":
        return summarize_profile(primary)
    if url_kind == "post":
        return summarize_post(primary)
    if url_kind == "company":
        return summarize_company(items, company_url=source_url)
    # Fallback: try both shapes.
    if primary.get("headline") is not None or primary.get("about") is not None:
        return summarize_profile(primary)
    return summarize_post(primary)


def _save_artifact(
    settings: Settings,
    *,
    url: str,
    url_kind: UrlKind,
    items: list[dict[str, Any]],
    context: dict[str, Any],
    keywords: list[str],
    meta: dict[str, Any],
) -> Path:
    out_dir = resolve_data_path(_ARTIFACT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"keyword_suggestions_{utc_artifact_stamp()}.json"
    payload = {
        "url": url,
        "url_kind": url_kind,
        "keywords": keywords,
        "context_summary": context,
        "scrape_items": items,
        "meta": meta,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("keyword_suggestions artifact saved path=%s", path)
    return path


def _append_log(settings: Settings, record: dict[str, Any]) -> Path:
    path = resolve_telemetry_data_dir(settings) / _LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("keyword_suggestions log appended path=%s", path)
    return path


def run_keyword_suggestions(
    url: str,
    *,
    settings: Optional[Settings] = None,
    count: int = KEYWORD_COUNT,
    persist: bool = True,
) -> KeywordSuggestionResult:
    """Scrape a LinkedIn profile/post URL and return 10 corpus search keywords."""
    settings = settings or load_settings()
    cleaned = (url or "").strip()
    recorded_at = datetime.now(timezone.utc).isoformat()
    url_kind = classify_linkedin_url(cleaned)

    result = KeywordSuggestionResult(
        url=cleaned,
        url_kind=url_kind,
        keywords=[],
        context_summary={},
        scrape_item_count=0,
        recorded_at=recorded_at,
    )

    if url_kind == "unknown":
        result.error = (
            "URL must be a LinkedIn personal profile (/in/...), company page "
            "(/company/...), or post (/posts/, /feed/update/, /activity/) URL."
        )
        logger.warning("keyword_suggestions rejected url=%s reason=%s", cleaned, result.error)
        if persist:
            result.log_path = str(
                _append_log(
                    settings,
                    {
                        "event": "rejected",
                        "url": cleaned,
                        "url_kind": url_kind,
                        "error": result.error,
                        "recorded_at": recorded_at,
                    },
                )
            )
        return result

    try:
        items, runs = _scrape_url(cleaned, url_kind, settings)
    except Exception as exc:
        logger.exception("keyword_suggestions scrape failed url=%s", cleaned)
        result.error = f"Scrape failed: {exc}"
        if persist:
            result.log_path = str(
                _append_log(
                    settings,
                    {
                        "event": "scrape_error",
                        "url": cleaned,
                        "url_kind": url_kind,
                        "error": result.error,
                        "recorded_at": recorded_at,
                    },
                )
            )
        return result

    run_ids = [r.run_id for r in runs if r.run_id]
    result.scrape_item_count = len(items)
    result.apify_run_ids = run_ids
    result.apify_runs = runs
    if not items:
        result.error = "Scrape returned no items for that URL."
        logger.warning("keyword_suggestions empty scrape url=%s", cleaned)
        if persist:
            result.log_path = str(
                _append_log(
                    settings,
                    {
                        "event": "empty_scrape",
                        "url": cleaned,
                        "url_kind": url_kind,
                        "apify_run_ids": run_ids,
                        "error": result.error,
                        "recorded_at": recorded_at,
                    },
                )
            )
        return result

    context = _build_context(items, url_kind, source_url=cleaned)
    result.context_summary = context
    logger.info(
        "keyword_suggestions context ready kind=%s keys=%s",
        context.get("kind"),
        list(context.keys()),
    )

    try:
        keywords, model, inp, out, cost = suggest_keywords_from_context(
            context,
            settings=settings,
            source_url=cleaned,
            source_kind=url_kind,
            count=count,
        )
    except Exception as exc:
        logger.exception("keyword_suggestions gemini failed url=%s", cleaned)
        result.error = f"Gemini failed: {exc}"
        if persist:
            artifact = _save_artifact(
                settings,
                url=cleaned,
                url_kind=url_kind,
                items=items,
                context=context,
                keywords=[],
                meta={"error": result.error, "apify_run_ids": run_ids},
            )
            result.artifact_path = str(artifact)
            result.log_path = str(
                _append_log(
                    settings,
                    {
                        "event": "gemini_error",
                        "url": cleaned,
                        "url_kind": url_kind,
                        "apify_run_ids": run_ids,
                        "context_summary": context,
                        "error": result.error,
                        "artifact_path": result.artifact_path,
                        "recorded_at": recorded_at,
                    },
                )
            )
        return result

    result.keywords = keywords
    result.gemini_model = model
    result.gemini_input_tokens = inp
    result.gemini_output_tokens = out
    result.gemini_cost_usd = cost

    if persist:
        artifact = _save_artifact(
            settings,
            url=cleaned,
            url_kind=url_kind,
            items=items,
            context=context,
            keywords=keywords,
            meta={
                "apify_run_ids": run_ids,
                "gemini_model": model,
                "gemini_input_tokens": inp,
                "gemini_output_tokens": out,
                "gemini_cost_usd": cost,
            },
        )
        result.artifact_path = str(artifact)
        result.log_path = str(
            _append_log(
                settings,
                {
                    "event": "ok",
                    "url": cleaned,
                    "url_kind": url_kind,
                    "keywords": keywords,
                    "context_summary": context,
                    "scrape_item_count": len(items),
                    "apify_run_ids": run_ids,
                    "gemini_model": model,
                    "gemini_input_tokens": inp,
                    "gemini_output_tokens": out,
                    "gemini_cost_usd": cost,
                    "artifact_path": result.artifact_path,
                    "recorded_at": recorded_at,
                },
            )
        )

    logger.info(
        "keyword_suggestions done url=%s keywords=%s",
        cleaned,
        keywords,
    )
    return result
