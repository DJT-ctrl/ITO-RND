# 02 — Validation Pipeline

**Status:** Partially implemented  
**Owner:** Daniel

Independent pipeline that grades predictions against reality after a fixed post-publish window.

---

## Purpose

1. Collect a live post (or import from corpus).
2. Run the Predictor Agent → store `predicted_engagement_percentile`.
3. Wait until engagement has had time to accrue (default **48 hours** after `posted_at`).
4. Re-scrape actual engagement metrics from LinkedIn.
5. Map actual total engagement to a corpus percentile.
6. Calculate and persist the **delta** (`actual − predicted`).
7. Surface accuracy history for the team during testing.

This is the core validation tool: *we predicted X, reality was Y, here's the gap.*

---

## Flow

```
Collect / Corpus Import
        │
        ▼
   predict_for_post()  ──►  predictions row (status: scheduled)
        │                      validation_due_at = posted_at + 48h
        │                      baseline_* captured at T0
        ▼
   [wait until validation_due_at]
        │
        ▼
   worker: rescrape URLs  ──►  actual likes/comments/shares
        │
        ▼
   compute_validation_scores()
        │   actual_engagement_percentile (corpus-mapped)
        │   prediction_delta = actual − predicted
        │   accuracy_score = max(0, 100 − |delta|)
        ▼
   mark_validated() + snapshot  ──►  prediction_engagement_snapshots
        │
        ▼
   Accuracy History dashboard
```

---

## What exists in code today

| Component | Location |
|-----------|----------|
| Collect + predict orchestration | `validation_pipeline/pipeline.py`, `collect.py`, `predict.py` |
| 48h scheduling | `validation_due_at` on insert; `VALIDATION_DEV_WINDOW_MINUTES` for dev |
| Rescrape by URL | `validation_pipeline/rescrape.py` |
| Delta scoring | `validation_pipeline/scoring.py` |
| Scheduled worker | `validation_pipeline/worker.py`, `jobs/run_validation_worker.py` |
| Persistence | `validation_pipeline/store.py`, `storage/schema.sql` (`predictions`, `prediction_engagement_snapshots`) |
| Dashboard | `dashboard/pages/validation/7_Validation_Collect.py`, `8_Validation_Queue.py`, `9_Accuracy_History.py` |

---

## Key fields on `predictions`

| Field group | Examples |
|-------------|----------|
| Predicted | `predicted_engagement_percentile`, `predicted_total_engagement`, `prediction_method`, `neighbor_count` |
| T0 baseline | `baseline_likes`, `baseline_total_engagement` (engagement at collect time) |
| Actual (post-rescrape) | `actual_total_engagement`, `actual_engagement_percentile` |
| Deltas | `prediction_delta`, `likes_delta`, `comments_delta`, `shares_delta`, `total_engagement_delta`, `accuracy_score` |

---

## What validation does *not* do yet

- Feed deltas back into the Predictor Agent
- Cluster predictions by topic or author segment
- Re-weight neighbor scoring based on historical accuracy
- Backfill validated posts into the corpus with ground-truth percentiles

That is the job of the [feedback system](03_FEEDBACK_SYSTEM.md).

---

## Open design note: validation window

48 hours is the current default. T7 module A4 (Engagement-Decay Capture) would inform whether 48h is the right grading window per topic or post type. Until decay curves are measured, 48h is a pragmatic fixed window for testing.
