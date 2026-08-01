"""Phase 11 multi-horizon orchestration: Lane A (same-age) + Lane B (24/48/72)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from config.settings import Settings, load_settings
from phase_10.budget import allow_paid_step, record_agentic_spend
from storage.vector_store import create_schema, get_connection
from validation_pipeline.age_buckets import (
    LANE_FIXED_HORIZON,
    LANE_SAME_AGE,
    parse_fixed_horizons,
    same_age_horizon_hours,
)
from validation_pipeline.age_aware import classify_validation_mode
from validation_pipeline.predict import predict_for_post, save_prediction
from validation_pipeline.schemas import (
    CollectedPost,
    CollectPredictResult,
    EngagementActuals,
    PredictionRecord,
    strip_engagement_for_backtest,
)
from validation_pipeline.scoring import (
    compute_validation_scores,
    corpus_size_warning,
    fetch_bucketed_corpus_engagement_totals,
)
from validation_pipeline.store import (
    insert_snapshot,
    mark_failed,
    mark_validated,
)

logger = logging.getLogger(__name__)

_INTER_POST_DELAY_S = 1.0

# Prefer creating the canonical mid horizon first when budget is tight.
_FIXED_CREATE_ORDER = (48, 24, 72)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _age_hours(posted_at: datetime, scraped_at: datetime) -> float:
    return max(0.0, (scraped_at - posted_at).total_seconds() / 3600.0)


def _truth_engagement(post: CollectedPost) -> EngagementActuals:
    return EngagementActuals(
        likes=int(post.likes or 0),
        comments=int(post.comments or 0),
        shares=int(post.shares or 0),
        total_engagement=int(
            post.total_engagement
            or (int(post.likes or 0) + int(post.comments or 0) + int(post.shares or 0))
        ),
    )


def _budget_allows_predict(settings: Settings) -> bool:
    decision = allow_paid_step("multi_horizon_predict", settings=settings)
    return bool(decision.allowed)


def _record_predict_spend(settings: Settings, *, cost_usd: float = 0.002) -> None:
    try:
        record_agentic_spend(
            job_id="multi_horizon_predict",
            provider="gemini",
            cost_usd=cost_usd,
            settings=settings,
        )
    except Exception:
        logger.debug("Failed to record multi_horizon_predict spend", exc_info=True)


def grade_same_age_prediction(
    prediction: PredictionRecord,
    actuals: EngagementActuals,
    settings: Settings,
    *,
    age_hours: float,
) -> PredictionRecord:
    """Grade Lane A immediately from pre-strip engagement (no Apify).

    The row was already inserted as ``scheduled`` by the caller before this
    runs. ``fetch_due_predictions`` never selects ``prediction_lane =
    'same_age'`` rows (see ``store.py``), so if grading raises here without
    the row being marked ``failed``, it would be stuck at ``scheduled``
    forever — no worker tick would ever pick it up. The except block below
    closes that gap.
    """
    conn = get_connection(settings)
    try:
        create_schema(conn)
        corpus_totals, age_bucket, percentile_source = (
            fetch_bucketed_corpus_engagement_totals(
                conn,
                horizon_hours=float(prediction.prediction_horizon_hours or age_hours),
                min_n=settings.validation_age_bucket_min_n,
            )
        )
        warning = corpus_size_warning(corpus_totals)
        if warning:
            logger.info("Lane A grade corpus warning: %s", warning)
        scores = compute_validation_scores(
            actuals,
            prediction,
            corpus_totals,
            age_bucket=age_bucket,
            percentile_source=percentile_source,
            horizon_hours=float(prediction.prediction_horizon_hours or age_hours),
        )
        validated_at = _utcnow()
        horizon = float(prediction.prediction_horizon_hours or age_hours)
        # classify_validation_mode's "live_48h" label is a generic "graded
        # within tolerance of its stated horizon" flag inherited from the
        # pre-Phase-11 48h-only world — it does not mean the horizon was
        # literally 48h. Lane A's horizon is derived from its own current
        # age, so this call reliably lands in that in-window band.
        _classified_age, mode = classify_validation_mode(
            posted_at=prediction.posted_at,
            validated_at=validated_at,
            horizon_hours=horizon,
            is_backtest=False,
            tolerance_hours=settings.validation_age_window_tolerance_hours,
            mature_min_hours=float(settings.validation_backtest_mature_min_hours),
        )
        mark_validated(
            conn,
            prediction.prediction_id,
            actuals,
            scores,
            validation_age_hours=round(age_hours, 2),
            validation_mode=mode,
            validated_at=validated_at,
        )
        insert_snapshot(conn, prediction.prediction_id, actuals)
    except Exception as exc:
        try:
            fail_conn = get_connection(settings)
            try:
                mark_failed(fail_conn, prediction.prediction_id, str(exc))
            finally:
                fail_conn.close()
        except Exception:
            logger.exception(
                "Also failed to mark Lane A prediction %s as failed",
                prediction.prediction_id,
            )
        raise
    finally:
        conn.close()

    return prediction.model_copy(
        update={
            "status": "validated",
            "validated_at": validated_at,
            "validation_age_hours": round(age_hours, 2),
            "validation_mode": mode,
            "actual_likes": actuals.likes,
            "actual_comments": actuals.comments,
            "actual_shares": actuals.shares,
            "actual_total_engagement": actuals.total_engagement,
            "actual_engagement_percentile": scores.actual_engagement_percentile,
            "prediction_delta": scores.prediction_delta,
            "accuracy_score": scores.accuracy_score,
        }
    )


def planned_horizons_for_post(
    post: CollectedPost,
    settings: Settings,
    *,
    scraped_at: datetime | None = None,
) -> list[tuple[str, int]]:
    """Return ordered (lane, horizon_hours) jobs for one post.

    Fixed horizons that have already elapsed by predict time are skipped:
    if the post is already older than a horizon, ``due_at`` for that Lane B
    job would collapse to "now" (see ``predict_multi_horizon_for_post``),
    so the very next worker tick would re-scrape and label *today's* (often
    mature) engagement as if it were the 24h/48h/72h number — reintroducing
    the exact age/horizon skew Phase 11 exists to remove, plus wasting an
    Apify + Gemini call. This matters most for bulk/backtest imports of
    already-scraped historical posts, where ``posted_at`` can be days or
    months in the past. Lane A already grades the post at its real current
    age, so it is the correct stand-in for any horizon that has passed.
    """
    now = scraped_at or post.scraped_at or _utcnow()
    age_h = _age_hours(post.posted_at, now)
    jobs: list[tuple[str, int]] = [(LANE_SAME_AGE, same_age_horizon_hours(age_h))]
    if not getattr(settings, "validation_fixed_horizon_enabled", True):
        return jobs
    fixed = parse_fixed_horizons(settings.validation_fixed_horizons_hours)
    ordered = [h for h in _FIXED_CREATE_ORDER if h in fixed]
    for h in fixed:
        if h not in ordered:
            ordered.append(h)
    for h in ordered:
        if age_h >= h:
            continue
        jobs.append((LANE_FIXED_HORIZON, int(h)))
    return jobs


async def predict_multi_horizon_for_post(
    post: CollectedPost,
    settings: Settings,
    *,
    existing_keys: set[tuple[str, float]] | None = None,
    same_age_posts: set[str] | None = None,
    predict_budget_remaining: list[int] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[list[PredictionRecord], list[str], int]:
    """Create missing Lane A + Lane B predictions for one post.

    Returns (saved_rows, errors, budget_skipped_count).
    """
    scraped_at = post.scraped_at or _utcnow()
    age_h = _age_hours(post.posted_at, scraped_at)
    truth = _truth_engagement(post)
    blind = strip_engagement_for_backtest([post])[0]
    blind = blind.model_copy(update={"scraped_at": scraped_at})

    keys = existing_keys
    same_age_done = set(same_age_posts or ())
    if keys is None or same_age_posts is None:
        conn = get_connection(settings)
        try:
            create_schema(conn)
            from validation_pipeline.store import existing_prediction_lanes_and_keys

            loaded_keys, loaded_same = existing_prediction_lanes_and_keys(
                conn, [post.linkedin_post_id]
            )
            keys = keys if keys is not None else loaded_keys
            if same_age_posts is None:
                same_age_done = loaded_same
        finally:
            conn.close()

    saved: list[PredictionRecord] = []
    errors: list[str] = []
    budget_skipped = 0

    for lane, horizon in planned_horizons_for_post(
        post, settings, scraped_at=scraped_at
    ):
        key = (post.linkedin_post_id, float(horizon))
        if lane == LANE_SAME_AGE and post.linkedin_post_id in same_age_done:
            continue
        if key in keys:
            continue

        if predict_budget_remaining is not None and predict_budget_remaining[0] <= 0:
            budget_skipped += 1
            continue
        if not _budget_allows_predict(settings):
            budget_skipped += 1
            continue

        if on_progress:
            on_progress(
                f"{post.linkedin_post_id}: predict {lane} @{horizon}h"
            )

        try:
            prediction = await predict_for_post(
                blind,
                settings,
                target_horizon_hours=float(horizon),
                prediction_lane=lane,
                age_hours_at_predict=age_h,
            )
            if lane == LANE_SAME_AGE:
                due_at = scraped_at
            else:
                due_at = post.posted_at + timedelta(hours=horizon)
                if due_at < scraped_at:
                    due_at = scraped_at
            # Always store pre-strip baselines for auditability.
            truth_for_baseline = post.model_copy(
                update={
                    "likes": truth.likes,
                    "comments": truth.comments,
                    "shares": truth.shares,
                    "total_engagement": truth.total_engagement,
                    "scraped_at": scraped_at,
                }
            )
            record = save_prediction(
                truth_for_baseline,
                prediction,
                settings,
                validation_due_at=due_at,
                is_backtest=False,
                validation_window_hours=float(horizon),
                prediction_lane=lane,
                scraped_at_predict=scraped_at,
            )

            if lane == LANE_SAME_AGE:
                record = grade_same_age_prediction(
                    record,
                    truth,
                    settings,
                    age_hours=age_h,
                )
                same_age_done.add(post.linkedin_post_id)

            saved.append(record)
            keys.add(key)
            _record_predict_spend(settings)
            if predict_budget_remaining is not None:
                predict_budget_remaining[0] -= 1
        except Exception as exc:
            errors.append(f"{post.linkedin_post_id}@{horizon}h: {exc}")
            logger.exception(
                "Multi-horizon predict failed for %s @%sh",
                post.linkedin_post_id,
                horizon,
            )

    return saved, errors, budget_skipped

async def run_multi_horizon_on_posts(
    posts: list[CollectedPost],
    *,
    settings: Settings | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> CollectPredictResult:
    """Auto Lane A + Lane B for each post under per-run + Gemini budget caps."""
    settings = settings or load_settings()
    result = CollectPredictResult()
    result.scraped = len(posts)

    if not settings.validation_multi_horizon_enabled:
        # Legacy single-horizon path: one predict at validation_window_hours.
        from validation_pipeline.pipeline import _predict_posts

        return await _predict_posts(posts, settings, on_progress=on_progress)

    conn = get_connection(settings)
    try:
        create_schema(conn)
        from validation_pipeline.store import existing_prediction_lanes_and_keys

        keys, same_age_posts = existing_prediction_lanes_and_keys(
            conn, [p.linkedin_post_id for p in posts]
        )
    finally:
        conn.close()

    budget = [int(settings.validation_multi_horizon_max_predicts_per_run)]

    for i, post in enumerate(posts, start=1):
        if on_progress:
            on_progress(f"Multi-horizon {i}/{len(posts)}: {post.linkedin_post_id}")
        # Stamp scraped_at if missing.
        if post.scraped_at is None:
            post = post.model_copy(update={"scraped_at": _utcnow()})

        # Skip entirely only when all planned horizons already exist.
        # Lane A is satisfied by *any* same_age row (hour may drift with age).
        planned = planned_horizons_for_post(post, settings)
        missing: list[tuple[str, int]] = []
        for lane, h in planned:
            if lane == LANE_SAME_AGE:
                if post.linkedin_post_id not in same_age_posts:
                    missing.append((lane, h))
                continue
            if (post.linkedin_post_id, float(h)) not in keys:
                missing.append((lane, h))
        if not missing:
            result.skipped += 1
            if on_progress:
                on_progress(
                    f"Multi-horizon {i}/{len(posts)} done: {post.linkedin_post_id} (skipped)"
                )
            continue

        saved, errors, budget_skipped = await predict_multi_horizon_for_post(
            post,
            settings,
            existing_keys=keys,
            same_age_posts=same_age_posts,
            predict_budget_remaining=budget,
            on_progress=on_progress,
        )
        result.predicted += len(saved)
        result.predictions.extend(saved)
        result.errors.extend(errors)
        result.budget_skipped += budget_skipped
        for row in saved:
            if row.prediction_horizon_hours is not None:
                keys.add((row.linkedin_post_id, float(row.prediction_horizon_hours)))
            if row.prediction_lane == LANE_SAME_AGE:
                same_age_posts.add(row.linkedin_post_id)

        if on_progress:
            on_progress(
                f"Multi-horizon {i}/{len(posts)} done: {post.linkedin_post_id}"
            )

        if i < len(posts):
            await asyncio.sleep(_INTER_POST_DELAY_S)

    return result

def run_multi_horizon_on_posts_sync(
    posts: list[CollectedPost],
    *,
    settings: Settings | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> CollectPredictResult:
    return asyncio.run(
        run_multi_horizon_on_posts(
            posts, settings=settings, on_progress=on_progress
        )
    )
