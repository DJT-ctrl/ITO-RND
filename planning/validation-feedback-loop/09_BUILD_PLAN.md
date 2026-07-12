# 09 — Build Plan

**Status:** Phase C complete — next is Phase D  
**Date:** 2026-07-12  
**Source:** Planning docs 01–08 + peer review

Living tracker for implementing the validation feedback loop. Do not skip phases.

---

## How many phases?

| # | Phase | Status |
|---|-------|--------|
| 0 | Foundation (validation grading exists) | Done |
| **A** | Passive calibration | **Done** |
| **B** | Structured feedback records | **Done** |
| **C** | Deterministic cluster routing | **Done** |
| **D** | Feedback injection + context cache | Not started ← next |

**5 phases total** (0 + A–D). Finished through **C**; next is **D**.

---

## Doc map → phases

| Phase | Docs | Outcome | Status |
|-------|------|---------|--------|
| **0 — Foundation** | 01, 02, 08 | Validation grades predictions; code practices | Done |
| **A — Passive calibration** | 03 Phase A, 05 §4, 07 §1–3 | Global `mean_delta` + `N_min` gate; no LLM | Done |
| **B — Structured feedback** | 03 Phase B, 04 Option B | `prediction_feedback` + template job | Done |
| **C — Cluster routing** | 03 Phase C, 05 §2 | Deterministic routing + `prediction_clusters` | Done |
| **D — Injection + cache** | 03 Phase D, 05 caching | Predict-time feedback + A/B; cache later | Not started |

```
Validated rows → mean_delta → calibrate percentile (A)
       → template feedback records (B)
       → cluster routing (C)
       → inject at predict time (D)
```

---

## Phase A checklist

- [x] `feedback/` package with pure calibration math
- [x] `fetch_calibration_stats` + `VALIDATION_CALIBRATION_*` settings
- [x] Wire into `validation_pipeline/predict.py` (fail open)
- [x] Unit tests for sign convention, `N_min`, clamp
- [x] `pytest` green for calibration + existing validation tests

---

## Phase B checklist

- [x] `prediction_feedback` table + unique `(prediction_id, feedback_version)`
- [x] Template generator (`feedback/generate.py`) — no LLM
- [x] Store upsert + missing-feedback query
- [x] Batch job `python -m feedback.jobs.run_feedback_batch`
- [x] Thin hook after `mark_validated` in worker (fail open)
- [x] Setting `VALIDATION_FEEDBACK_ENABLED`
- [x] Tests: `tests/test_feedback_generate.py` + worker asserts enqueue

---

## Phase C checklist

- [x] Deterministic `assign_cluster_id` (length × format × follower band)
- [x] `prediction_clusters` table
- [x] `refresh_cluster_stats` from validated feedback
- [x] Assign `cluster_id` on template feedback generation
- [x] `resolve_calibration_stats` fallback: cluster → global → none
- [x] Predict path uses cluster-aware calibration + telemetry fields
- [x] Setting `VALIDATION_CLUSTER_N_MIN` (default 50)
- [x] Tests: `tests/test_feedback_routing.py`

**Code landed:**
- `feedback/routing.py`
- `storage/schema.sql` → `prediction_clusters`
- `resolve_calibration_stats` / `refresh_cluster_stats` in `feedback/store.py`

**Out of scope for C:** embedding centroids / k-means, LLM cluster labels, predict-time feedback text injection (Phase D).

---

## Locked decisions (implementation)

| Decision | Choice |
|----------|--------|
| Package | `feedback/` from day one |
| Hook | After `compute_neighbor_prediction` in `predict_for_post` |
| Formula | `calibrated = clamp(raw + mean_delta, 0, 100)` |
| Delta | `prediction_delta = actual − predicted` |
| Defaults | calibration enabled; `N_min = 30`; cluster `N_min = 50` |
| On error / cold start | Use raw percentile (fail open) |
| Feedback table | Separate `prediction_feedback` (Option B) |
| Feedback v1 | Template-only; fail-open after validate |
| Routing | Metadata buckets first (no LLM); embedding centroids later |

---

## Later phases (summary)

**D:** Retrieve + inject feedback block at predict time; A/B flag; context caching when cost justifies it.

See [08 — Build Practices](08_BUILD_PRACTICES.md) for module layout and DoD.
