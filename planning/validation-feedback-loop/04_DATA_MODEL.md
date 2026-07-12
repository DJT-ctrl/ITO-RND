# 04 — Data Model

**Status:** Proposed  
**Source:** Team discussion — keep base data and predictions together for future historical pulls

---

## Design intent

When we pull historical post data in the future, we should get **both** the raw engagement facts **and** the prediction snapshot that was made at the time. The delta between them is first-class data, not a throwaway calculation.

---

## What exists today

### `predictions` table

Single table holding the full lifecycle: prediction snapshot, T0 baseline, actuals after rescrape, and deltas.

```
predictions
├── identity: prediction_id, linkedin_post_id, linkedin_url, content, posted_at
├── predicted:  predicted_engagement_percentile, predicted_*_engagement, prediction_method
├── baseline:   baseline_*_engagement (T0 at collect)
├── actual:     actual_*_engagement, actual_engagement_percentile (post-rescrape)
├── deltas:     prediction_delta, accuracy_score, *_delta
└── scheduling: status, validation_due_at, validated_at
```

### `prediction_engagement_snapshots`

Timestamped rescrape results per validation event. Supports future multi-window rescrapes (48h, 7d, 30d).

---

## Proposed additions

### Option A — Extend `predictions` (minimal)

Add columns for feedback once generated:

| Column | Type | Purpose |
|--------|------|---------|
| `feedback_json` | JSONB | Structured feedback record (see doc 03) |
| `feedback_generated_at` | TIMESTAMPTZ | When feedback was produced |
| `cluster_id` | TEXT | Cluster assignment for routing |

**Pros:** Simple; one row = full story.  
**Cons:** Feedback schema evolution requires migrations; no feedback version history.

### Option B — Separate `prediction_feedback` table (recommended)

```sql
CREATE TABLE prediction_feedback (
    feedback_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prediction_id       UUID NOT NULL REFERENCES predictions(prediction_id),
    cluster_id          TEXT,
    feedback_json       JSONB NOT NULL,
    feedback_version    TEXT NOT NULL DEFAULT 'v1',
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    generation_method   TEXT  -- 'template', 'llm', 'human'
);

CREATE INDEX prediction_feedback_prediction_idx ON prediction_feedback (prediction_id);
CREATE INDEX prediction_feedback_cluster_idx ON prediction_feedback (cluster_id);
```

**Pros:** Versioned feedback; can regenerate without touching prediction row; supports human overrides.  
**Cons:** Extra join at read time.

### Option C — `prediction_deltas` view or materialised view

If the team wants a dedicated "delta table" name without duplicating storage:

```sql
CREATE VIEW prediction_deltas AS
SELECT
    prediction_id,
    linkedin_post_id,
    posted_at,
    predicted_engagement_percentile,
    actual_engagement_percentile,
    prediction_delta,
    accuracy_score,
    prediction_method,
    neighbor_count,
    validated_at
FROM predictions
WHERE status = 'validated';
```

This is a read surface, not new storage. Useful for analytics and feedback batch jobs.

---

## Cluster registry (future)

```sql
CREATE TABLE prediction_clusters (
    cluster_id          TEXT PRIMARY KEY,
    label               TEXT,
    description         TEXT,
    centroid_embedding  vector(3072),  -- optional, for routing
    sample_count        INTEGER DEFAULT 0,
    mean_delta          DOUBLE PRECISION,
    std_delta           DOUBLE PRECISION,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Updated periodically from validated predictions assigned to each cluster. `mean_delta` / `std_delta` power simple calibration offsets in Phase A of the feedback system.

---

## Historical data with predictions attached

Future corpus imports and exports should include:

| Field | Source |
|-------|--------|
| Post content + engagement | `posts` or scrape artifact |
| Prediction at time of draft | `predictions.predicted_*` |
| Actual outcome | `predictions.actual_*` |
| Delta | `predictions.prediction_delta` |
| Feedback lessons | `prediction_feedback.feedback_json` |

This makes backtesting and retraining decisions (if ever needed) possible from a single export.

---

## Migration path

1. **Now** — `predictions` + deltas already exist; no schema change needed for validation.
2. **Phase B** — Add `prediction_feedback` table + `cluster_id` on feedback rows.
3. **Phase C** — Add `prediction_clusters` when routing agent is live.
4. **Later** — Optional `post_engagement_history` (T7 A4) for multi-window actuals.
