"""Shared corpus refresh spine for T10.4 / T10.5 (+ T10.5.5 proof)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config.settings import Settings, load_settings
from phase_10.budget import allow_paid_step, record_agentic_spend
from phase_10.cost_ledger_store import agentic_context
from phase_10.db import agentic_connection
from phase_10.models import ScrapeProof
from phase_10 import scrape_proof_store
from phase_10.search_plan import (
    active_niches,
    get_search_plan,
    queries_for_general_refresh,
)
from phase_10.topics import queries_for_niche
from processors.finalize_records import load_analysed_jsonl
from processors.run_db_ingest import run_db_ingest
from processors.run_embeddings import run_embeddings
from processors.run_pipeline import run_pipeline
from processors.run_sample_collection import run_sample_collection
from storage.vector_store import create_schema, get_connection

logger = logging.getLogger(__name__)


def _post_id(post: dict[str, Any]) -> str:
    return str(post.get("id") or post.get("post_id") or "").strip()


def _existing_post_ids(settings: Settings, ids: list[str]) -> set[str]:
    if not ids or not settings.database_url:
        return set()
    conn = get_connection(settings)
    try:
        create_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT post_id FROM posts WHERE post_id = ANY(%s)",
                (ids,),
            )
            return {str(r[0]) for r in cur.fetchall()}
    finally:
        conn.close()


def newest_niche_posted_at(settings: Settings, niche: str) -> datetime | None:
    if not settings.database_url:
        return None
    conn = get_connection(settings)
    try:
        create_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(posted_at) FROM posts
                WHERE niche = %s AND posted_at IS NOT NULL
                """,
                (niche,),
            )
            row = cur.fetchone()
        if not row or row[0] is None:
            return None
        value = row[0]
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        return None
    finally:
        conn.close()


def allocate_niche_budgets(
    weights: dict[str, float],
    total: int,
) -> dict[str, int]:
    """Split ``total`` max posts across niches by weight (min 1 if weight > 0)."""
    active = {k: float(v) for k, v in weights.items() if float(v) > 0}
    if not active or total <= 0:
        return {}
    weight_sum = sum(active.values())
    raw = {k: (v / weight_sum) * total for k, v in active.items()}
    budgets = {k: max(1, int(v)) for k, v in raw.items()}
    # Trim overflow from largest buckets.
    while sum(budgets.values()) > total and any(b > 1 for b in budgets.values()):
        biggest = max(budgets, key=lambda k: budgets[k])
        if budgets[biggest] <= 1:
            break
        budgets[biggest] -= 1
    return budgets


def _posted_bounds(posts: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    times: list[str] = []
    for post in posts:
        for key in ("postedAt", "posted_at", "publishedAt"):
            value = post.get(key)
            if value:
                times.append(str(value))
                break
    if not times:
        return None, None
    times.sort()
    return times[0], times[-1]


def _force_niche_on_jsonl(jsonl_path: Path, niche: str) -> list[dict[str, Any]]:
    records = load_analysed_jsonl(jsonl_path)
    for record in records:
        record["niche"] = niche
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return records


def _persist_proof(
    settings: Settings,
    *,
    job_id: str,
    niche: str | None,
    payload: dict[str, Any],
) -> ScrapeProof:
    summary = str(payload.get("summary") or "ok")
    proof = ScrapeProof(
        job_id=job_id,
        niche=niche,
        summary=summary,
        payload=payload,
        ok=bool(payload.get("ok", True)),
    )
    if not settings.database_url:
        return proof
    with agentic_connection(settings) as conn:
        return scrape_proof_store.insert_proof(
            conn,
            job_id=job_id,
            niche=niche,
            payload=payload,
        )


def run_corpus_refresh(
    job_id: str,
    queries: list[str],
    *,
    max_posts: int,
    force_niche: str | None = None,
    settings: Settings | None = None,
    niches_skipped: list[dict[str, str]] | None = None,
) -> ScrapeProof:
    """Collect → scoped analyse → embed → ingest → ledger + proof."""
    settings = settings or load_settings()
    queries = [q.strip() for q in queries if q and str(q).strip()]
    skipped = list(niches_skipped or [])

    decision = allow_paid_step(job_id, "apify", settings=settings)
    if not decision.allowed:
        payload = {
            "ok": False,
            "summary": f"skipped: {decision.reason}",
            "health": decision.reason,
            "queries": queries,
            "niches_skipped": skipped,
            "empty_run": True,
        }
        return _persist_proof(
            settings, job_id=job_id, niche=force_niche, payload=payload
        )

    if not queries or max_posts <= 0:
        payload = {
            "ok": True,
            "summary": "skipped: no queries or zero budget",
            "health": "empty plan",
            "queries": queries,
            "max_posts": max_posts,
            "niches_skipped": skipped,
            "empty_run": True,
            "scraped": 0,
            "new": 0,
            "already": 0,
        }
        return _persist_proof(
            settings, job_id=job_id, niche=force_niche, payload=payload
        )

    search_params = {
        "searchQueries": queries,
        "maxPosts": int(max_posts),
        "sortBy": "date",
    }
    collection = run_sample_collection(
        search_params,
        settings=settings,
        context=agentic_context(job_id),
    )
    posts = list(collection.enriched_posts or collection.posts or [])
    scraped_ids = [_post_id(p) for p in posts if _post_id(p)]
    existing = _existing_post_ids(settings, scraped_ids)
    new_ids = [i for i in scraped_ids if i not in existing]
    already = len(scraped_ids) - len(new_ids)
    apify_cost = sum(float(r.cost_usd or 0.0) for r in collection.apify_runs)
    min_posted, max_posted = _posted_bounds(posts)

    if not posts:
        if apify_cost > 0:
            record_agentic_spend(
                job_id=job_id, provider="apify", cost_usd=apify_cost, settings=settings
            )
        payload = {
            "ok": True,
            "summary": "empty scrape",
            "health": "empty_run",
            "queries": queries,
            "max_posts": max_posts,
            "niches_skipped": skipped,
            "empty_run": True,
            "scraped": 0,
            "new": 0,
            "already": 0,
            "overlap_pct": 0.0,
            "apify_usd": round(apify_cost, 6),
            "usd_per_new": None,
            "posted_at_min": min_posted,
            "posted_at_max": max_posted,
            "force_niche": force_niche,
        }
        return _persist_proof(
            settings, job_id=job_id, niche=force_niche, payload=payload
        )

    source_scans = [collection.post_path.name] if collection.post_path else []
    profile_file = str(collection.profile_path) if collection.profile_path else None
    _, jsonl_path = run_pipeline(
        with_gemini=settings.agentic_scrape_with_gemini,
        settings=settings,
        with_profile_enrichment=bool(profile_file),
        profile_file=profile_file,
        raw_posts=posts,
        source_scans=source_scans,
    )

    records = load_analysed_jsonl(jsonl_path)
    if force_niche:
        records = _force_niche_on_jsonl(jsonl_path, force_niche)

    niche_counts: dict[str, int] = {}
    for record in records:
        niche = str(record.get("niche") or "other")
        niche_counts[niche] = niche_counts.get(niche, 0) + 1

    npy_path = run_embeddings(processed_file=str(jsonl_path), settings=settings)
    ingested = run_db_ingest(
        processed_file=str(jsonl_path),
        embeddings_file=str(npy_path),
        settings=settings,
        skip_backup=True,
    )

    if apify_cost > 0:
        record_agentic_spend(
            job_id=job_id, provider="apify", cost_usd=apify_cost, settings=settings
        )

    scraped_n = len(scraped_ids)
    new_n = len(new_ids)
    overlap = round(100.0 * already / scraped_n, 1) if scraped_n else 0.0
    usd_per_new = round(apify_cost / new_n, 6) if new_n else None
    summary = (
        f"scraped={scraped_n} new={new_n} already={already} "
        f"ingested={ingested} usd={apify_cost:.4f}"
    )
    payload = {
        "ok": True,
        "summary": summary,
        "health": "success",
        "queries": queries,
        "max_posts": max_posts,
        "niches_skipped": skipped,
        "empty_run": False,
        "scraped": scraped_n,
        "new": new_n,
        "already": already,
        "ingested": ingested,
        "overlap_pct": overlap,
        "apify_usd": round(apify_cost, 6),
        "usd_per_new": usd_per_new,
        "niche_counts": niche_counts,
        "force_niche": force_niche,
        "posted_at_min": min_posted,
        "posted_at_max": max_posted,
        "with_gemini": settings.agentic_scrape_with_gemini,
    }
    return _persist_proof(settings, job_id=job_id, niche=force_niche, payload=payload)


def run_general_refresh(settings: Settings | None = None) -> ScrapeProof:
    settings = settings or load_settings()
    queries = queries_for_general_refresh(settings)
    return run_corpus_refresh(
        "general_refresh",
        queries,
        max_posts=settings.agentic_general_max_posts,
        settings=settings,
    )


def run_niche_scrape(settings: Settings | None = None) -> ScrapeProof:
    """Demand-driven niche refresh: per active niche, skip idle/stale."""
    settings = settings or load_settings()
    plan = get_search_plan(settings)
    niches = active_niches(settings=settings)
    skipped: list[dict[str, str]] = []
    if not niches:
        payload = {
            "ok": True,
            "summary": "skipped: no active niches",
            "health": "idle",
            "queries": [],
            "niches_skipped": [{"niche": "*", "reason": "no demand weights"}],
            "empty_run": True,
            "scraped": 0,
            "new": 0,
            "already": 0,
        }
        return _persist_proof(
            settings, job_id="niche_scrape", niche=None, payload=payload
        )

    budgets = allocate_niche_budgets(
        {n: plan.weights_by_niche.get(n, 0.0) for n in niches},
        settings.agentic_niche_max_posts_total,
    )
    now = datetime.now(timezone.utc)
    stale_delta = timedelta(hours=settings.agentic_niche_stale_hours)

    total_scraped = total_new = total_already = 0
    total_cost = 0.0
    niche_results: list[dict[str, Any]] = []
    last_proof: ScrapeProof | None = None

    for niche in niches:
        budget = budgets.get(niche, 0)
        queries = queries_for_niche(niche)
        if budget <= 0 or not queries:
            skipped.append({"niche": niche, "reason": "no queries or zero budget"})
            continue
        newest = newest_niche_posted_at(settings, niche)
        if newest is not None and (now - newest) < stale_delta:
            skipped.append(
                {
                    "niche": niche,
                    "reason": f"fresh (<{settings.agentic_niche_stale_hours}h)",
                }
            )
            continue

        proof = run_corpus_refresh(
            "niche_scrape",
            queries,
            max_posts=budget,
            force_niche=niche,
            settings=settings,
            niches_skipped=[],
        )
        last_proof = proof
        p = proof.payload
        total_scraped += int(p.get("scraped") or 0)
        total_new += int(p.get("new") or 0)
        total_already += int(p.get("already") or 0)
        total_cost += float(p.get("apify_usd") or 0.0)
        niche_results.append(
            {
                "niche": niche,
                "budget": budget,
                "queries": queries,
                "summary": proof.summary,
                "scraped": p.get("scraped"),
                "new": p.get("new"),
            }
        )

    if not niche_results and skipped:
        payload = {
            "ok": True,
            "summary": f"skipped all niches ({len(skipped)})",
            "health": "all_skipped",
            "queries": [],
            "niches_skipped": skipped,
            "niche_results": [],
            "empty_run": True,
            "scraped": 0,
            "new": 0,
            "already": 0,
            "apify_usd": 0.0,
        }
        return _persist_proof(
            settings, job_id="niche_scrape", niche=None, payload=payload
        )

    summary = (
        f"niches={len(niche_results)} scraped={total_scraped} "
        f"new={total_new} already={total_already} usd={total_cost:.4f}"
    )
    # Rollup proof for the overall niche job (per-niche proofs already stored).
    payload = {
        "ok": True,
        "summary": summary,
        "health": "success",
        "niches_skipped": skipped,
        "niche_results": niche_results,
        "scraped": total_scraped,
        "new": total_new,
        "already": total_already,
        "overlap_pct": (
            round(100.0 * total_already / total_scraped, 1) if total_scraped else 0.0
        ),
        "apify_usd": round(total_cost, 6),
        "usd_per_new": (
            round(total_cost / total_new, 6) if total_new else None
        ),
        "plan_weights": dict(plan.weights_by_niche),
        "empty_run": total_scraped == 0,
    }
    return _persist_proof(settings, job_id="niche_scrape", niche=None, payload=payload)
