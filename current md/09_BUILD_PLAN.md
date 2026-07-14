# 09 — Build Plan

**Status:** A–J engineering done; Phase F evening re-run 2026-07-14 still **NO-GO** (4.90% < 5%)  
**Date:** 2026-07-14  
**Source:** Planning docs 01–08 + peer review + `FEEDBACK_LOOP_PART2_PLAN.md`  
**Active docs folder:** this directory (`current md/`)

Living tracker for implementing the validation feedback loop.

---

## How many phases?

| # | Phase | Status |
|---|-------|--------|
| 0 | Foundation (validation grading exists) | Done |
| **A** | Passive calibration | **Done** (prod OFF) |
| **B** | Structured feedback records | **Done** |
| **C** | Deterministic cluster routing | **Done** |
| **D** | Feedback injection + A/B flag | **Done** (prod OFF) |
| **E** | Production hardening & observability | **Done** |
| **F** | Prove lift (offline go/no-go) | **Re-run NO-GO** (4.90% < 5%) |
| **G** | LLM hybrid feedback v2 + human review | **Done (staging)** |
| **H** | Embedding persistence + centroids + ranked retrieve | **Done (staging)** |
| I | Scale (async, caching) | Deferred (after GO / volume pain) |
| **J** | Injectability unlock (soften overwrite + shadow) | **Done** (live=`hard_lock`; shadow ON OK) |

Latest F re-run: N=553, holdout=30, cal lift **4.90%**, shadow holdout **16/30** with
MAE delta **0**. See [11_GO_NO_GO.md](11_GO_NO_GO.md).

**Next:** keep shadow ON; re-run F when cal might clear 5% or shadow shows lift.
Do **not** start Advanced injection / Phase I / G+ for prod learning flips yet.

---

## Doc map → phases

| Phase | Docs | Outcome | Status |
|-------|------|---------|--------|
| **0 — Foundation** | 01, 02, 08 | Validation grades predictions; code practices | Done |
| **A — Passive calibration** | 03 Phase A, 05 §4, 07 §1–3 | Global `mean_delta` + `N_min` gate; no LLM | Done |
| **B — Structured feedback** | 03 Phase B, 04 Option B | `prediction_feedback` + template job | Done |
| **C — Cluster routing** | 03 Phase C, 05 §2 | Deterministic routing + `prediction_clusters` | Done |
| **D — Injection** | 03 Phase D, 05 caching | Predict-time feedback + A/B flag | Done |
| **E — Observability** | Part 2 §E, 10 runbook | Telemetry + 4-arm harness + Accuracy History | Done |
| **F — Prove lift** | Part 2 §F, [11](11_GO_NO_GO.md) | Offline eval; prod defaults from evidence | Done (NO-GO) |
| **G — Hybrid LLM** | Part 2 §G | v2 hybrid + review queue (staging; injection OFF) | Done |
| **H — Embeddings** | Part 2 §H | Persist vectors, centroids, ranked retrieve | Done |

```
Validated rows → mean_delta → calibrate percentile (A)
       → template feedback records (B)
       → cluster routing (C)
       → inject at predict time (D)
       → measure + gates (E/F) → learning ON only if pass
```

---

## Phase D checklist

- [x] `feedback/retrieve.py` — cluster-scoped top-N feedback (excludes self)
- [x] Format compact prompt block (lessons / misses grounded in deltas)
- [x] `EvaluationDeps.feedback_context` + predictor prompt section
- [x] Wire into `validation_pipeline/predict.py` (fail open)
- [x] A/B settings: `VALIDATION_FEEDBACK_INJECTION_ENABLED`, `VALIDATION_FEEDBACK_INJECTION_LIMIT`
- [x] Telemetry fields on neighbor dict: `feedback_injected`, `feedback_count`
- [x] Tests: `tests/test_feedback_retrieve.py`
- [x] Streamlit **Feedback Loop** page + Accuracy History calibration/coverage
- [x] Manual actions: generate missing feedback, refresh clusters, regenerate one
- [ ] Gemini context caching — deferred until stable prefix cost justifies it

**Code landed:**
- `feedback/retrieve.py`, `feedback/ui.py`
- `dashboard/pages/validation/10_Feedback_Loop.py`
- `agents/schemas.py` / `agents/predictor.py` injection
- Settings for injection enable + limit

---

## Phase E checklist

- [x] Predict telemetry (`PredictionTelemetry` + `build_prediction_telemetry`)
- [x] Feedback generate latency/cost on template rows
- [x] 4-arm leakage-safe offline replay + CLI
- [x] Accuracy History raw vs calibrated + MAE by method
- [x] Per-cluster MAE + learning-active banner
- [x] Override audit JSONL
- [x] Ops runbook ([10](10_PRODUCTION_RUNBOOK.md))
- [x] Feedback Loop offline-eval panel

---

## Phase F checklist

- [x] Holdout=30 eval on ≥31 validated rows (ran on N=241; two identical reports)
- [x] Go/no-go doc ([11](11_GO_NO_GO.md)) — **NO-GO** for calibration and injection
- [x] Prod/dashboard baseline locked: feedback ON, calibration OFF, injection OFF
- [x] Shadow mode — landed in Phase J; staging ON; F re-run 2026-07-14 still NO-GO (see [11](11_GO_NO_GO.md))

---

## Phase G checklist

- [x] `feedback_review_status` + approved-only retrieve
- [x] `generate_hybrid_feedback` behind `VALIDATION_FEEDBACK_LLM_ENABLED` + daily cap
- [x] Lesson text sanitized via `wrap_untrusted_text`
- [x] Feedback Loop human review queue (approve/reject pending v2)
- [x] Prod injection remains OFF (Phase F)
- [x] Staging ops: ≥10 approved v2 (grounded review)

---

## Phase H checklist

- [x] Persist `predictions.embedding` + `embedding_model_version` at predict time
- [x] `prediction_clusters.centroid_embedding` + `run_cluster_centroids` job
- [x] Routing: centroid → metadata fallback (`feedback/routing.py`)
- [x] Ranked retrieve by cosine when query embedding present; prefer v2
- [x] Staging ops: bounded embedding backfill + centroids + routing MAE report

---

## Phase J checklist

- [x] `resolve_final_prediction` — `hard_lock` | `soft_blend` | `shadow_only`
- [x] Settings: `VALIDATION_SHADOW_MODE_ENABLED`, `VALIDATION_INJECTABILITY_MODE`, `VALIDATION_SOFT_BLEND_WEIGHT`
- [x] Dashboard toggles + runtime overrides
- [x] Telemetry: `llm_percentile`, `shadow_percentile`, injectability fields
- [x] Eval: `shadow_live` comparison + injection arms use shadow when present
- [x] Phase F re-run 2026-07-14 afternoon (N=365, 4.48%) and evening (N=553, **4.90%**) — still NO-GO
- [ ] Next F re-run when cal may clear 5% or shadow MAE beats live

---

## Locked decisions (implementation)

| Decision | Choice |
|----------|--------|
| Package | `feedback/` from day one |
| Calibration formula | `calibrated = clamp(raw + mean_delta, 0, 100)` |
| Delta | `prediction_delta = actual − predicted` |
| Routing | Metadata buckets first (no LLM) |
| Injection | Cluster feedback block; live numbers default hard_lock |
| Injectability (Phase J) | soft_blend / shadow_only behind flags; default hard_lock |
| A/B | `VALIDATION_FEEDBACK_INJECTION_ENABLED` |
| Prod learning defaults (2026-07-13) | Calibration OFF; injection OFF until gate passes |

See [08 — Build Practices](08_BUILD_PRACTICES.md) for module layout and DoD.
