# 03 — Feedback System

**Status:** Idea / planning  
**Owner:** Daniel  
**Priority:** Next big build after validation pipeline stabilises

---

## The missing piece

The validation pipeline answers: *"Was the prediction accurate?"*

The feedback system answers: *"What should the AI do differently next time?"*

Without this, we have a one-shot predictor with a report card — not a learning system.

---

## Goal

After a prediction is validated, go back to the AI with structured feedback:

- What it got **right** (direction, magnitude, reasoning that held up)
- Where it **missed** (over/under-estimated, wrong neighbor weighting, ignored signals)
- **Gaps to fill** — patterns from similar validated misses that should inform the next prediction

---

## Proposed feedback shape

Structured output (likely JSON schema) attached to each validated prediction:

```json
{
  "prediction_id": "uuid",
  "delta_summary": {
    "predicted_percentile": 72.0,
    "actual_percentile": 58.0,
    "prediction_delta": -14.0,
    "direction": "overestimated"
  },
  "what_worked": [
    "Neighbor set was topically relevant",
    "Baseline engagement growth rate was in expected range"
  ],
  "what_missed": [
    "Predicted viral tail; post plateaued after 6h",
    "Follower count band not accounted for in weighting"
  ],
  "lessons_for_similar_posts": [
    "Short-form listicles in this cluster tend to underperform neighbor average by ~10 pts"
  ],
  "cluster_id": "optional — assigned by deterministic routing"
}
```

Exact schema TBD. Key constraint: **compact, factual, derived from stored deltas** — not free-form LLM rambling.

---

## How feedback gets consumed

At prediction time, before or during Predictor Agent execution:

1. **Route** the incoming post to a cluster via deterministic routing — embedding → nearest centroid, no LLM (see [05 — Technical Approach](05_TECHNICAL_APPROACH.md)).
2. **Retrieve** top-N validated feedback entries from that cluster (similar embeddings or same `cluster_id`).
3. **Inject** a short feedback block into the predictor context — what worked and what failed for comparable posts.
4. **Bias** deterministic scoring (neighbor-weighted percentile in `processors/benchmark.py`) using cluster-specific calibration offsets if available.

---

## Concerns to design around

### Hallucination

Feedback summaries must be grounded in stored numbers (`prediction_delta`, actual vs predicted counts). The feedback generator should cite fields from the validated row, not invent narratives.

Mitigations:
- Template-first summaries for simple cases (delta < 5 pts → "accurate")
- LLM only for `what_missed` / `lessons` fields, with strict JSON schema + validation
- Human review queue for high-magnitude misses (optional, later)

### Context size

As validated rows grow, we cannot dump all history into every prompt.

Mitigations:
- Cluster-first routing — only retrieve feedback from the relevant cluster
- Rank within cluster by embedding similarity to current post
- Cap retrieved feedback to top 3–5 entries
- Periodic summarisation: roll up cluster-level calibration stats (mean delta, std dev) into a single paragraph per cluster — these summaries are good candidates for [context caching](05_TECHNICAL_APPROACH.md#context-caching) at scale

---

## Suggested build phases

### Phase A — Passive calibration (no new agent)

- Aggregate `prediction_delta` by `prediction_method`, follower band, content length
- Apply simple correction offsets to deterministic neighbor scoring
- Zero extra LLM calls; proves the loop with data alone

### Phase B — Structured feedback records

- New `prediction_feedback` table (see [04 — Data Model](04_DATA_MODEL.md))
- Batch job: for each newly validated row, generate structured feedback JSON
- Store alongside prediction; no injection yet

### Phase C — Deterministic cluster routing

- Embed post → nearest cluster centroid (pgvector), with metadata-bucket fallback
- No LLM for routing — same post always maps to the same cluster
- Clusters grow organically; start with coarse buckets (format, length, topic embedding k-means)

### Phase D — Feedback injection at predict time

- Predictor reads cluster feedback + calibration offsets
- A/B compare accuracy with vs without feedback on held-out validated set

---

## Integration point in codebase

Best hook: after `mark_validated()` in `validation_pipeline/worker.py`, enqueue feedback generation for that `prediction_id`.

Consumer: `validation_pipeline/predict.py` / `agents/predictor.py` at predict time.
