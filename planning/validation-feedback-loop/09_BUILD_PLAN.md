# 09 — Build Plan

**Status:** All build phases A–D complete  
**Date:** 2026-07-12  
**Source:** Planning docs 01–08 + peer review

Living tracker for implementing the validation feedback loop.

---

## How many phases?

| # | Phase | Status |
|---|-------|--------|
| 0 | Foundation (validation grading exists) | Done |
| **A** | Passive calibration | **Done** |
| **B** | Structured feedback records | **Done** |
| **C** | Deterministic cluster routing | **Done** |
| **D** | Feedback injection + A/B flag | **Done** |

**5 phases total** (0 + A–D). Feedback loop core build is complete.

Gemini context caching remains a later optimisation when injection volume justifies it (not required for Phase D DoD).

---

## Doc map → phases

| Phase | Docs | Outcome | Status |
|-------|------|---------|--------|
| **0 — Foundation** | 01, 02, 08 | Validation grades predictions; code practices | Done |
| **A — Passive calibration** | 03 Phase A, 05 §4, 07 §1–3 | Global `mean_delta` + `N_min` gate; no LLM | Done |
| **B — Structured feedback** | 03 Phase B, 04 Option B | `prediction_feedback` + template job | Done |
| **C — Cluster routing** | 03 Phase C, 05 §2 | Deterministic routing + `prediction_clusters` | Done |
| **D — Injection** | 03 Phase D, 05 caching | Predict-time feedback + A/B flag | Done |

```
Validated rows → mean_delta → calibrate percentile (A)
       → template feedback records (B)
       → cluster routing (C)
       → inject at predict time (D)
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

## Locked decisions (implementation)

| Decision | Choice |
|----------|--------|
| Package | `feedback/` from day one |
| Calibration formula | `calibrated = clamp(raw + mean_delta, 0, 100)` |
| Delta | `prediction_delta = actual − predicted` |
| Routing | Metadata buckets first (no LLM) |
| Injection | Cluster feedback block; numbers stay deterministic |
| A/B | `VALIDATION_FEEDBACK_INJECTION_ENABLED` |

See [08 — Build Practices](08_BUILD_PRACTICES.md) for module layout and DoD.
