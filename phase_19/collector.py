"""Execute approved Phase 19 collection jobs under fixed budget caps."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from config.settings import Settings, load_settings
from phase_10.budget import record_agentic_spend
from phase_10.cost_ledger_store import agentic_context
from phase_19 import evidence_store
from phase_19.budget_guard import JOB_ID, evaluate_collection_gate
from phase_19.curator import CuratedCandidate, curate_candidates
from phase_19.gaps import assess_gaps
from processors.finalize_records import load_finalized_jsonl
from processors.run_db_ingest import run_db_ingest
from processors.run_embeddings import run_embeddings
from processors.run_pipeline import run_pipeline
from processors.run_sample_collection import run_sample_collection
from scrapers.linkedin_post_url_scraper import LinkedInPostUrlScraper
from storage.vector_store import create_schema, get_connection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectionRunResult:
    action: str  # ran | skipped | failed
    detail: str
    job_id: str | None = None
    receipt_id: str | None = None


def _estimate_cost_usd(candidates: int) -> float:
    """Conservative Apify estimate used only for job planning display."""
    return round(max(0.05, candidates * 0.02), 4)


def _ingest_accepted(
    posts: list[dict[str, Any]],
    *,
    subscriber_id: str,
    scope: str,
    primary_niche: str,
    settings: Settings,
) -> int:
    """Analyse, embed, and ingest accepted posts; stamp private user_id when needed."""
    if not posts:
        return 0
    _, jsonl_path = run_pipeline(
        with_gemini=settings.agentic_scrape_with_gemini,
        settings=settings,
        with_profile_enrichment=False,
        raw_posts=posts,
        source_scans=[],
    )
    records = load_finalized_jsonl(jsonl_path)
    for record in records:
        record["niche"] = primary_niche or record.get("niche")
        if scope == "subscriber_private":
            record["user_id"] = subscriber_id
    npy_path = run_embeddings(processed_file=str(jsonl_path), settings=settings)
    return run_db_ingest(
        processed_file=str(jsonl_path),
        embeddings_file=str(npy_path),
        settings=settings,
        skip_backup=True,
    )


def _persist_curated(
    conn,
    curated: list[CuratedCandidate],
    *,
    brief: dict[str, Any],
    job_id: str,
    provider_run_id: str | None,
    scope_for_source: dict[str, str],
) -> tuple[int, int]:
    accepted = rejected = 0
    for item in curated:
        scope = scope_for_source.get(item.source_type, "shared_niche")
        if item.decision == "accepted":
            accepted += 1
        else:
            rejected += 1
        evidence_store.save_evidence_item(
            conn,
            post_id=item.post_id,
            source_url=item.source_url,
            source_type=item.source_type,
            content_preview=item.content_preview,
            primary_niche=brief.get("primary_niche") or "",
            sub_niche=brief.get("sub_niche") or "",
            target_audience=brief.get("target_audience") or "",
            author_key=item.author_key,
            quality_score=item.quality_score,
            decision=item.decision,
            rejection_reason=item.rejection_reason,
            provider_run_id=provider_run_id,
            collection_job_id=job_id,
            subscriber_id=brief["subscriber_id"],
            scope=scope,
        )
    return accepted, rejected


def _collect_profile_posts(
    urls: list[str],
    *,
    max_posts: int,
    settings: Settings,
) -> tuple[list[dict[str, Any]], float, str | None]:
    if not urls or max_posts <= 0:
        return [], 0.0, None
    scraper = LinkedInPostUrlScraper(settings)
    result = scraper.fetch_posts_by_urls(
        urls,
        max_posts=max_posts,
        context=agentic_context(JOB_ID),
    )
    cost = float(result.run_record.cost_usd or 0.0) if result.run_record else 0.0
    run_id = result.run_record.run_id if result.run_record else None
    return list(result.items or []), cost, run_id


def _collect_query_posts(
    queries: list[str],
    *,
    max_posts: int,
    settings: Settings,
) -> tuple[list[dict[str, Any]], float, str | None]:
    if not queries or max_posts <= 0:
        return [], 0.0, None
    collection = run_sample_collection(
        {
            "searchQueries": queries,
            "maxPosts": int(max_posts),
            "sortBy": "date",
        },
        settings=settings,
        context=agentic_context(JOB_ID),
    )
    posts = list(collection.enriched_posts or collection.posts or [])
    cost = sum(float(r.cost_usd or 0.0) for r in collection.apify_runs)
    run_id = collection.apify_runs[0].run_id if collection.apify_runs else None
    return posts, cost, run_id


def run_subscriber_collection(
    conn,
    brief: dict[str, Any],
    plan: dict[str, Any],
    *,
    job_kind: str,
    gap_reason: str = "",
    recommended_seeds: list[str] | None = None,
    settings: Settings | None = None,
    profile_collector: Callable[..., tuple[list[dict[str, Any]], float, str | None]] | None = None,
    query_collector: Callable[..., tuple[list[dict[str, Any]], float, str | None]] | None = None,
    ingest_fn: Callable[..., int] | None = None,
) -> CollectionRunResult:
    """Run one baseline or daily refresh under remaining budget/candidate caps."""
    settings = settings or load_settings()
    gate = evaluate_collection_gate(conn, brief=brief, plan=plan, settings=settings)
    if not gate.allowed:
        return CollectionRunResult(action="skipped", detail=f"skipped: {gate.reason}")

    remaining_budget = gate.remaining_budget_usd
    remaining_candidates = gate.remaining_candidates
    estimated = _estimate_cost_usd(min(remaining_candidates, 40))

    job = evidence_store.create_collection_job(
        conn,
        subscriber_id=brief["subscriber_id"],
        brief_id=brief["id"],
        plan_id=plan["id"],
        job_kind=job_kind,
        gap_reason=gap_reason,
        estimated_cost_usd=min(estimated, remaining_budget),
        recommended_seeds=recommended_seeds,
    )
    evidence_store.mark_job_running(conn, job["id"])

    profile_fn = profile_collector or _collect_profile_posts
    query_fn = query_collector or _collect_query_posts
    ingest = ingest_fn or (
        lambda posts, **kwargs: _ingest_accepted(posts, settings=settings, **kwargs)
    )

    known = evidence_store.known_post_ids_for_subscriber(conn, brief["subscriber_id"])
    total_cost = 0.0
    all_curated: list[CuratedCandidate] = []
    accepted_posts_private: list[dict[str, Any]] = []
    accepted_posts_shared: list[dict[str, Any]] = []
    provider_run_ids: list[str] = []

    try:
        # Priority 1: subscriber public profile
        profile_budget = min(20, remaining_candidates)
        if profile_budget > 0 and remaining_budget > 0:
            posts, cost, run_id = profile_fn(
                [brief["public_profile_url"]],
                max_posts=profile_budget,
                settings=settings,
            )
            if run_id:
                provider_run_ids.append(run_id)
            total_cost += cost
            remaining_budget = max(0.0, remaining_budget - cost)
            curated = curate_candidates(
                posts,
                source_type="subscriber_public_profile",
                known_post_ids=known,
                max_accept=profile_budget,
            )
            for item in curated:
                if item.decision == "accepted" and item.post_id:
                    known.add(item.post_id)
                    accepted_posts_private.append(item.raw)
            all_curated.extend(curated)
            remaining_candidates = max(0, remaining_candidates - len(posts))

        # Priority 2: approved seed accounts only (never auto-recommended seeds)
        seeds = [u for u in (brief.get("seed_accounts") or []) if u]
        seed_budget = min(30, remaining_candidates)
        if seeds and seed_budget > 0 and remaining_budget > 0:
            posts, cost, run_id = profile_fn(
                seeds,
                max_posts=max(1, seed_budget // max(1, len(seeds))),
                settings=settings,
            )
            if run_id:
                provider_run_ids.append(run_id)
            total_cost += cost
            remaining_budget = max(0.0, remaining_budget - cost)
            curated = curate_candidates(
                posts,
                source_type="approved_seed_accounts",
                known_post_ids=known,
                max_accept=seed_budget,
            )
            for item in curated:
                if item.decision == "accepted" and item.post_id:
                    known.add(item.post_id)
                    accepted_posts_shared.append(item.raw)
            all_curated.extend(curated)
            remaining_candidates = max(0, remaining_candidates - len(posts))

        # Priority 3: niche keyword queries
        queries = [q for q in (plan.get("proposed_queries") or []) if q]
        query_budget = min(40, remaining_candidates)
        if queries and query_budget > 0 and remaining_budget > 0:
            posts, cost, run_id = query_fn(
                queries[:4],
                max_posts=query_budget,
                settings=settings,
            )
            if run_id:
                provider_run_ids.append(run_id)
            total_cost += cost
            curated = curate_candidates(
                posts,
                source_type="niche_keyword_queries",
                known_post_ids=known,
                max_accept=query_budget,
            )
            for item in curated:
                if item.decision == "accepted" and item.post_id:
                    known.add(item.post_id)
                    accepted_posts_shared.append(item.raw)
            all_curated.extend(curated)

        scope_map = {
            "subscriber_public_profile": "subscriber_private",
            "approved_seed_accounts": "shared_niche",
            "niche_keyword_queries": "shared_niche",
        }
        accepted_n, rejected_n = _persist_curated(
            conn,
            all_curated,
            brief=brief,
            job_id=job["id"],
            provider_run_id=provider_run_ids[0] if provider_run_ids else None,
            scope_for_source=scope_map,
        )

        niche = brief.get("primary_niche") or ""
        if accepted_posts_private:
            ingest(
                accepted_posts_private,
                subscriber_id=brief["subscriber_id"],
                scope="subscriber_private",
                primary_niche=niche,
            )
        if accepted_posts_shared:
            ingest(
                accepted_posts_shared,
                subscriber_id=brief["subscriber_id"],
                scope="shared_niche",
                primary_niche=niche,
            )

        if total_cost > 0:
            record_agentic_spend(
                job_id=JOB_ID,
                provider="apify",
                cost_usd=total_cost,
                settings=settings,
            )
        evidence_store.record_budget_usage(
            conn,
            subscriber_id=brief["subscriber_id"],
            plan_id=plan["id"],
            cost_usd=total_cost,
            candidates=len(all_curated),
        )

        evidence_store.finish_collection_job(
            conn,
            job["id"],
            status="completed",
            actual_cost_usd=total_cost,
            candidate_count=len(all_curated),
            accepted_count=accepted_n,
            rejected_count=rejected_n,
            recommended_seeds=recommended_seeds,
        )
        receipt = evidence_store.save_receipt(
            conn,
            subscriber_id=brief["subscriber_id"],
            collection_job_id=job["id"],
            collected_count=accepted_n,
            rejected_count=rejected_n,
            actual_cost_usd=total_cost,
            coverage_gaps=[gap_reason] if gap_reason else [],
            summary=(
                f"{job_kind}: accepted={accepted_n} rejected={rejected_n} "
                f"usd={total_cost:.4f}"
            ),
        )
        return CollectionRunResult(
            action="ran",
            detail=receipt["summary"],
            job_id=job["id"],
            receipt_id=receipt["id"],
        )
    except Exception as exc:
        logger.exception("Subscriber evidence collection failed for %s", brief["subscriber_id"])
        evidence_store.finish_collection_job(
            conn,
            job["id"],
            status="failed",
            actual_cost_usd=total_cost,
            candidate_count=len(all_curated),
            error_detail=str(exc),
            recommended_seeds=recommended_seeds,
        )
        return CollectionRunResult(
            action="failed",
            detail=f"failed: {exc}",
            job_id=job["id"],
        )


def process_subscriber(
    conn,
    brief: dict[str, Any],
    plan: dict[str, Any],
    *,
    settings: Settings | None = None,
    **collector_kwargs: Any,
) -> CollectionRunResult:
    """Choose baseline vs daily refresh for one approved subscriber."""
    settings = settings or load_settings()
    if not evidence_store.baseline_completed(conn, plan["id"]):
        return run_subscriber_collection(
            conn,
            brief,
            plan,
            job_kind="baseline",
            gap_reason="baseline_capture",
            settings=settings,
            **collector_kwargs,
        )

    stats = evidence_store.coverage_stats(conn, brief["subscriber_id"])
    assessment = assess_gaps(stats, brief=brief)
    if not assessment.needs_collection:
        job = evidence_store.create_collection_job(
            conn,
            subscriber_id=brief["subscriber_id"],
            brief_id=brief["id"],
            plan_id=plan["id"],
            job_kind="daily_refresh",
            gap_reason="no_gap",
            recommended_seeds=list(assessment.recommended_seeds),
        )
        evidence_store.finish_collection_job(
            conn,
            job["id"],
            status="skipped",
            recommended_seeds=list(assessment.recommended_seeds),
        )
        return CollectionRunResult(
            action="skipped",
            detail="skipped: no coverage gap",
            job_id=job["id"],
        )

    return run_subscriber_collection(
        conn,
        brief,
        plan,
        job_kind="daily_refresh",
        gap_reason="; ".join(assessment.reasons),
        recommended_seeds=list(assessment.recommended_seeds),
        settings=settings,
        **collector_kwargs,
    )


def run_subscriber_evidence_refresh(settings: Settings | None = None) -> str:
    """Agentic tick entry: process all approved, non-paused briefs once."""
    settings = settings or load_settings()
    if not settings.database_url:
        return "skipped: DATABASE_URL is not set"
    conn = get_connection(settings)
    try:
        create_schema(conn)
        pairs = evidence_store.list_approved_briefs(conn)
        if not pairs:
            return "skipped: no approved briefs"
        details: list[str] = []
        ran = skipped = failed = 0
        for brief, plan in pairs:
            result = process_subscriber(conn, brief, plan, settings=settings)
            details.append(f"{brief['subscriber_id']}:{result.action}")
            if result.action == "ran":
                ran += 1
            elif result.action == "failed":
                failed += 1
            else:
                skipped += 1
        return f"ran={ran} skipped={skipped} failed={failed} ({', '.join(details)})"
    finally:
        conn.close()
