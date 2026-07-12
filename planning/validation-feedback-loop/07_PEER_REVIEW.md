# 07 — Peer Review

**Status:** Review notes for team alignment  
**Date:** 2026-07-12  
**Scope:** Docs 01–06 + current `validation_pipeline/` code

---

## Verdict

The plan is directionally strong and ready to socialise. Separation of **measurement** (validation) vs **learning** (feedback), the phase ladder (A → D), and the explicit “no fine-tuning / no LLM router / no tabular transformers” decisions are the right constraints for this problem.

Main risk is not architecture — it is **shipping calibration too early on thin data**, and **mixing feedback concerns into the already-busy validation worker** without clear module boundaries. Address those in Phase A scope and in [08 — Build Practices](08_BUILD_PRACTICES.md).

---

## What works well

| Area | Why it holds up |
|------|-----------------|
| Two-layer framing | Grades first, learning second — avoids building prompt injection before deltas are trustworthy |
| Phase A (passive calibration) | Proves the loop with zero LLM cost; good kill-switch if MAE does not move |
| Option B feedback table | Versioning + regeneration without mutating the prediction row is correct |
| Deterministic cluster routing | Reproducible assignment beats an LLM router on cost, latency, and debuggability |
| Structured feedback JSON | Matches existing Pydantic patterns (`validation_pipeline/schemas.py`) |
| Context caching deferred to Phase D | Correct: cache serves cost, not learning |
| Hook after `mark_validated()` | Natural enqueue point once validation is stable |

---

## Gaps to close before / during build

### 1. Minimum sample size for calibration

Global `mean_delta` on a handful of validated rows can *worsen* predictions.

**Add to Phase A:**
- Gate: apply offset only when `N_validated >= N_min` (suggest start at **30** global, **50** per cluster later)
- Report `mean_delta` with std / CI in telemetry; do not silently apply when variance is huge
- Feature flag: `VALIDATION_CALIBRATION_ENABLED` (or settings equivalent) so raw vs calibrated can be compared

### 2. Cold start / fallback policy

Document explicit behaviour when feedback/calibration is unavailable:

| State | Behaviour |
|-------|-----------|
| No validated rows | Predictor unchanged (today’s path) |
| Below `N_min` | Log stats only; do not apply offset |
| Cluster too small | Fall back to global calibration, then to no offset |
| Feedback retrieval empty | Predict without feedback block |

This should live in code and in the Accuracy History UI so “no learning yet” is visible.

### 3. Sign convention for deltas (lock it)

Docs already say `prediction_delta = actual − predicted`. Calibration pseudocode must stay consistent:

- Overestimate (predicted 72, actual 58) → delta **-14**
- Calibration: `calibrated = raw_neighbor_percentile + mean_delta`  
  (adding a negative mean delta pulls overestimates down)

Update the Phase A formula in doc 05 if anyone copies `raw - mean_delta` without checking the sign. **One convention, one formula, one unit test.**

### 4. Corpus percentile drift

`actual_engagement_percentile` is mapped against the live corpus. If the corpus grows or shifts, the same absolute engagement gets a different percentile later — feedback “lessons” can rot.

**Add:**
- Persist `corpus_benchmark_version` or snapshot id used at scoring time on the prediction / snapshot row
- Prefer delta in **absolute engagement** for some diagnostics; keep percentile for product-facing accuracy
- When regenerating feedback, re-score only intentionally (version bump), do not silently rewrite history

### 5. Embeddings for validated RAG

Phase B/C assume similarity retrieval over validated posts. Confirm storage:

- Either store embedding on `predictions` (or a side table) at predict time
- Or re-embed content at feedback/retrieval time (costly, drift risk)

**Recommendation:** persist embedding (or reference to existing corpus vector) when the prediction is created. Feedback RAG should not re-embed ad hoc without a version pin.

### 6. Evaluation leakage

A/B “with vs without feedback” is listed in open questions — it needs a hard rule:

- Feedback retrieval must **exclude** the current post and, for eval runs, exclude the held-out validation set
- Re-use the evaluation-cycle harness with an explicit `feedback_enabled` flag and separate telemetry keys

Without this, Phase D will look better than it is.

### 7. Failure paths and idempotency

Validation already has `failed` / `validating` statuses. Feedback must respect them:

- Generate feedback **only** for `status = 'validated'`
- Feedback job must be **idempotent** (same `prediction_id` + `feedback_version` → upsert or no-op)
- Do not block the rescrape worker on LLM feedback — enqueue async (separate job), matching the open question leaning toward async

### 8. Worker / store hygiene (pre-feedback)

`validation_pipeline/worker.py` opens a new DB connection per prediction step. That is fine at low volume and a smell before scale. Refactor connection/session handling **before** bolting on feedback enqueue — see build practices.

Also: rescrape match failures are already noisy; keep feedback generation out of that exception path.

### 9. Observability for the learning loop

Doc 01 correctly flags cost/latency. Extend the same framework to:

| Event | Track |
|-------|-------|
| Calibration applied | raw vs calibrated percentile, `N`, `mean_delta` |
| Feedback generated | method (`template` / `llm`), latency, token cost |
| Feedback injected | cluster_id, count of entries, cache hit/miss (Phase D) |
| A/B arm | `control` vs `treatment` |

Without these, Accuracy History cannot attribute MAE changes to feedback vs corpus drift.

### 10. Dashboard surface (decide early)

Suggest for v1: extend **Accuracy History** with calibration/raw comparison and a thin “recent feedback” panel — do not invent a fifth validation page until Phase B produces reviewable records. Human review queue can wait.

---

## Suggested additions to the plan (accepted into this folder)

| Addition | Where it lands |
|----------|----------------|
| Cold-start / `N_min` gates | This review + Phase A in doc 03 (conceptually) |
| Delta sign + calibration formula lock | This review; fix formula when implementing |
| Corpus benchmark versioning | Data model follow-up when scoring hardens |
| Persist prediction embeddings | Data model / Phase B prerequisite |
| Eval leakage rules | Open questions → resolved before Phase D |
| Build/refactor practices | [08 — Build Practices](08_BUILD_PRACTICES.md) |
| Reading order + doc map | [README](README.md) |

---

## Recommendations on open questions (reviewer stance)

| Question | Recommendation |
|----------|----------------|
| Feedback table vs JSONB column | **Option B** — separate table |
| `prediction_deltas` view | Nice-to-have; ship later if analytics needs a named surface |
| Backfill validated into corpus | **Defer** until 48h window is trusted; use validated store for RAG first |
| Template vs LLM feedback | **Hybrid** as proposed; Phase A/B templates only |
| Human review queue | Skip for v1; add when LLM lessons ship |
| Initial clusters | Start with **metadata buckets**; add embedding centroids when N supports it |
| Min cluster size | Fallback chain: cluster → global → none |
| 48h window | **Proceed with 48h**; do not block feedback on T7 A4 |
| Sync vs async feedback | **Async job** after validate |
| A/B framework | Re-use eval harness + `feedback_enabled` |
| First PR scope | Agree with doc 06 minimal slice **plus** `N_min` gate + telemetry for raw vs calibrated |

---

## Risks ranked

1. **Thin-data calibration** — highest product risk  
2. **Corpus percentile drift** — silent history corruption  
3. **Eval leakage** — false confidence in Phase D  
4. **Monolithic worker growth** — maintainability risk (mitigate via 08)  
5. **LLM feedback hallucination** — mitigated if Phase B stays template-first  

---

## Ready-to-build checklist

- [ ] Team confirms Option B + Phase A first PR scope (doc 06 + `N_min`)
- [ ] Lock delta sign / calibration formula in tests
- [ ] Decide embedding persistence for validated rows
- [ ] Add settings flags for calibration (and later feedback injection)
- [ ] Read [08 — Build Practices](08_BUILD_PRACTICES.md) before opening the first implementation PR
- [ ] Keep validation pipeline green (`pytest` for worker/scoring/rescrape) before feedback enqueue

---

## Bottom line

Ship **measurement → passive calibration → structured feedback → deterministic routing → injection**, in that order. Do not skip the sample-size gate. Treat feedback as a **new package concern** next to validation, not as more logic piled into `worker.py`.
