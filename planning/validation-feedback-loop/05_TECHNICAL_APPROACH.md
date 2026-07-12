# 05 — Technical Approach

**Status:** Agreed direction — details TBD  
**Decision:** No fine-tuning for engagement prediction

---

## Fine-tuning: explicitly ruled out

| Concern | Why it matters here |
|---------|---------------------|
| Platform-specific | LinkedIn's algorithm changes frequently; a fine-tuned model encodes a snapshot that goes stale |
| Slow + expensive | Needs clean labelled data, compute, evaluation cycles — months, not days |
| Wrong problem shape | Fine-tuning suits narrow domains with stable rules (e.g. cross-border corporate law). Engagement prediction is a moving target tied to platform dynamics |

Fine-tuning is practical when solving a **specific problem in a very specific domain**. Engagement percentile on a social platform does not meet that bar.

**Verdict:** Use retrieval, clustering, and prompt-level calibration — not Vertex/Azure fine-tuning.

---

## Recommended stack

### 1. RAG over validated predictions (near-term)

- Embed validated posts (already have 3072-dim embeddings in corpus pipeline)
- At predict time, retrieve neighbors from **validated** rows with known deltas, not just high-performing corpus posts
- Weight neighbor influence by inverse delta magnitude (trust accurate historical predictions more)

Builds on existing pgvector + neighbor retrieval in `processors/benchmark.py`.

### 2. Deterministic cluster routing (medium-term — required at scale)

As validated data grows into thousands of rows, a single global neighbor pool becomes noisy. **Routing is required** — but it should be a fast, deterministic function, not an LLM agent.

**Architecture:**

```
Incoming post
      │
      ▼
┌─────────────────────┐
│ Deterministic       │  ← embedding → nearest cluster centroid
│ cluster routing     │     or metadata bucket (length, format, follower band)
│ (no LLM)            │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Cluster-scoped      │  ← retrieve feedback + neighbors within cluster
│ RAG + ranking       │
└────────┬────────────┘
         │
         ▼
   Predictor Agent (with cluster context + calibration offset)
```

- **Why not an LLM routing agent:** adds latency, cost, and another hallucination surface. Routing must be reproducible — the same post should always land in the same cluster.
- **How routing works:** embed the post → find nearest cluster centroid (pgvector), with metadata buckets as a fallback when a cluster has too few validated rows.
- Per-cluster ranking: sort retrieved feedback by relevance and recency
- Per-cluster calibration: `mean_delta` from `prediction_clusters` applied as offset
- An LLM may later **label/describe** clusters for the dashboard — but it does not assign them.

### 3. JSON schema feedback (not free-form prompts)

Daniel's instinct is correct: feedback should be **structured**, not a growing prose dump.

- Define a Pydantic model mirroring `PredictorOutput` gaps (what was wrong about the reasoning, not just the number)
- Generate via LLM with `response_format` / structured output
- Validate before storage; reject rows that don't parse

### 4. Deterministic calibration layer (cheap win)

Before any new agent work:

```python
# Pseudocode — cluster or global
calibrated_percentile = raw_neighbor_percentile - mean_delta_for_cluster
```

Uses data already in `predictions` where `status = 'validated'`. No new infrastructure.

---

## Vertex / Azure training?

**Not recommended** for this use case.

| Alternative | Role |
|-------------|------|
| Existing Gemini via PydanticAI | Feedback generation, predictor reasoning |
| pgvector retrieval | Find similar validated posts + their deltas |
| Deterministic cluster routing | Assign `cluster_id` at scale (no LLM) |
| Deterministic scoring | `processors/benchmark.py` — keep the number grounded |
| Cluster tables | Scale context without unbounded prompt growth |

If we later need a dedicated embedding model fine-tuned on LinkedIn post pairs, that's a separate, much smaller scope than fine-tuning the predictor LLM.

---

## Context management strategy

| Problem | Solution |
|---------|----------|
| Context grows unbounded | Deterministic cluster routing limits retrieval scope |
| Irrelevant feedback | Rank by embedding similarity within cluster |
| Stale lessons | Prefer recent validations; decay weight by age |
| Redundant entries | Summarise cluster stats periodically; retrieve summaries not raw rows |

---

## Context caching

**Useful for cost and speed — not for learning.**

Context caching (e.g. Gemini cached content) stores a large, stable prompt prefix so repeat calls don't re-send the same tokens. It does **not** teach the model new facts from yesterday's validations.

| Cache | Good for | Not a substitute for |
|-------|----------|----------------------|
| Cluster summaries (`mean_delta`, lesson roll-ups per cluster) | Stable reference blocks injected into every prediction in that cluster | Fresh per-post validated deltas |
| Global corpus stats | Distribution context that changes slowly | Live validation results |
| Cluster descriptions | Human-readable labels once clusters are named | Routing decisions |

**When it pays off:** once cluster summaries and global stats are large enough to be expensive to re-send on every predict call. Refresh the cache when cluster stats are recomputed (e.g. nightly batch), not on every new validation.

**Verdict:** add context caching in Phase D (feedback injection at scale) to reduce Gemini cost on the stable prefix. Learning still comes from the database; caching just makes serving cheaper.

---

## Structured data transformers — ruled out

**Not useful for this problem.**

Tabular/transformer models (e.g. models trained on spreadsheet-like data) are built for structured columns with fixed schemas. Our learning signal lives in **text + embeddings + prediction deltas** — retrieval, clustering, and simple calibration stats are a better fit.

**Verdict:** do not pursue structured data transformers. Revisit only if retrieval + calibration plateaus on accuracy.

---

## Success metrics

| Metric | Source |
|--------|--------|
| MAE of `prediction_delta` | `store.fetch_accuracy_aggregates()` — already exists |
| % within 10 percentile points | Same |
| Delta trend over time | Accuracy History — should improve after feedback phases land |
| Per-cluster MAE | New — split aggregates by `cluster_id` |

---

## What to build first

1. Deterministic calibration offsets (Phase A in doc 03) — proves value with zero new LLM calls
2. `prediction_feedback` table + batch generator (Phase B)
3. Deterministic cluster routing once N validated rows per bucket is meaningful (~50+ per cluster)
4. Context caching on stable cluster/global prefixes once injection volume justifies it (Phase D)
