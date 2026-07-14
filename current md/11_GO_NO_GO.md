# 11 — Go / No-Go Decision (Phase F)

**Date:** 2026-07-14 (evening re-run; N=553)  
**Status:** Decision recorded — learning mechanisms remain **OFF** in production  
**Prerequisite:** Phase J injectability + shadow telemetry; active docs in [`current md/`](README.md)

---

## Latest re-run (2026-07-14 evening)

| Field | Value |
|-------|-------|
| Validated N | 553 |
| Holdout | 30 |
| Training | 523 |
| Global mean Δ (training) | (see report) |
| Calibration ready | Yes |
| Rows with `shadow_percentile` (approx) | ~270 |
| Shadow rows in this holdout | **16 / 30** |
| Report 1 | `data/telemetry/eval_feedback_2026-07-14_200511Z.json` |
| Report 2 | `data/telemetry/eval_feedback_2026-07-14_200512Z.json` |

Both runs identical (stable-hash holdout).

### Arm MAE (holdout)

| Arm | MAE | % within 10 pts |
|-----|-----|-----------------|
| raw_no_feedback | 24.2437 | (see report) |
| raw_with_feedback | 24.2437 | |
| calibrated_no_feedback | 23.0559 | |
| calibrated_with_feedback | 23.0559 | |

Raw → calibrated MAE improvement: **4.90%**  
Gate required: **≥5%** → **not met** (very close; improved from 4.48% / 1.48%).

### Shadow vs live (`shadow_live`)

| Metric | Value |
|--------|-------|
| Sample count (holdout with shadow) | 16 |
| Live MAE | 27.1887 |
| Shadow MAE | 27.1887 |
| MAE delta (live − shadow) | **0.0** |

Shadow does **not** beat live. Soft-blend / injection stay OFF.

---

## Prior re-runs (same day)

| When | N | Cal lift | Shadow in holdout | Decision |
|------|---|----------|-------------------|----------|
| Afternoon | 365 | 4.48% | 4/30 | NO-GO |
| Evening | 553 | **4.90%** | 16/30 | NO-GO |
| 2026-07-13 | 241 | 1.48% | n/a | NO-GO |

Afternoon reports: `eval_feedback_2026-07-14_181833Z.json`, `…_182012Z.json`.

---

## Decisions (locked)

| Mechanism | Decision | Rationale |
|-----------|----------|-----------|
| Template feedback records | **ON** | Signal collection |
| Global calibration | **NO-GO / OFF** | 4.90% < 5% gate |
| Cluster calibration | **NO-GO / OFF** | Global gate not cleared |
| Prompt injection | **NO-GO / OFF** | Shadow MAE == live; no lift |
| Injectability `soft_blend` | **NO-GO / OFF** | Keep `hard_lock` |
| Shadow mode | **ON OK (staging)** | Keep collecting |

### Prod / dashboard baseline

```
VALIDATION_FEEDBACK_ENABLED=true
VALIDATION_CALIBRATION_ENABLED=false
VALIDATION_FEEDBACK_INJECTION_ENABLED=false
VALIDATION_INJECTABILITY_MODE=hard_lock
VALIDATION_SHADOW_MODE_ENABLED=true
```

---

## Revisit when

1. Calibration lift ≥5% on holdout≥30, **twice**.
2. Shadow MAE clearly beats live on a large holdout shadow sample.
3. Re-run: `python -m feedback.jobs.run_feedback_evaluation --holdout-size 30`

See [10_PRODUCTION_RUNBOOK.md](10_PRODUCTION_RUNBOOK.md).  
Roadmap: [FEEDBACK_LOOP_FUTURE_AFTER_H.md](FEEDBACK_LOOP_FUTURE_AFTER_H.md).
