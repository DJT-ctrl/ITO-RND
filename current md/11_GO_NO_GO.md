# 11 — Go / No-Go Decision (Phase F)

**Date:** 2026-07-15 (morning re-run; N=702)  
**Status:** Decision recorded — learning mechanisms remain **OFF** in production  
**Prerequisite:** Phase J injectability + shadow telemetry; active docs in [`current md/`](README.md)

---

## Latest re-run (2026-07-15 morning)

| Field | Value |
|-------|-------|
| Validated N | 702 |
| Holdout | 30 |
| Training | 672 |
| Global mean Δ (training) | 5.0162 |
| Calibration ready | Yes |
| Rows with `shadow_percentile` (holdout) | **16 / 30** |
| Report 1 | `data/telemetry/eval_feedback_2026-07-15_102637Z.json` |
| Report 2 | `data/telemetry/eval_feedback_2026-07-15_102638Z.json` |

Both runs identical (stable-hash holdout).

### Arm MAE (holdout)

| Arm | MAE | % within 10 pts |
|-----|-----|-----------------|
| raw_no_feedback | 22.6127 | 26.67 |
| raw_with_feedback | 22.6129 | 26.67 |
| calibrated_no_feedback | 21.9413 | 30.0 |
| calibrated_with_feedback | 21.9415 | 30.0 |

Raw → calibrated MAE improvement: **2.97%**  
Gate required: **≥5%** → **not met** (regressed from 4.90% on N=553).

Note: `global_mean_delta` ≈ 5.0 is training bias, **not** the MAE lift %. Do not confuse the two.

### Shadow vs live (`shadow_live`)

| Metric | Value |
|--------|-------|
| Sample count (holdout with shadow) | 16 |
| Live MAE | 24.1306 |
| Shadow MAE | 24.131 |
| MAE delta (live − shadow) | **−0.0004** |

Shadow does **not** beat live (essentially tied / slightly worse). Soft-blend / injection stay OFF.

---

## Prior re-runs

| When | N | Cal lift | Shadow in holdout | Decision |
|------|---|----------|-------------------|----------|
| **2026-07-15 morning** | **702** | **2.97%** | **16/30** | **NO-GO** |
| 2026-07-14 evening | 553 | 4.90% | 16/30 | NO-GO |
| 2026-07-14 afternoon | 365 | 4.48% | 4/30 | NO-GO |
| 2026-07-13 | 241 | 1.48% | n/a | NO-GO |

Evening 2026-07-14 reports: `eval_feedback_2026-07-14_200511Z.json`, `…_200512Z.json`.  
Afternoon: `…_181833Z.json`, `…_182012Z.json`.

---

## Decisions (locked)

| Mechanism | Decision | Rationale |
|-----------|----------|-----------|
| Template feedback records | **ON** | Signal collection |
| Global calibration | **NO-GO / OFF** | 2.97% < 5% gate (two stable runs) |
| Cluster calibration | **NO-GO / OFF** | Global gate not cleared |
| Prompt injection | **NO-GO / OFF** | Shadow MAE ≉ better than live; no lift |
| Injectability `soft_blend` | **NO-GO / OFF** | Keep `hard_lock` |
| Shadow mode | **ON OK (staging)** | Keep collecting |

Calibration vs soft_blend/injection remain **independent**: clearing the 5% cal gate alone would allow calibration ON without waiting for shadow lift. Soft_blend/injection still need clear shadow MAE improvement.

### Prod / dashboard baseline

```
VALIDATION_FEEDBACK_ENABLED=true
VALIDATION_CALIBRATION_ENABLED=false
VALIDATION_FEEDBACK_INJECTION_ENABLED=false
VALIDATION_INJECTABILITY_MODE=hard_lock
VALIDATION_SHADOW_MODE_ENABLED=true
```

Affirmed via override audit `phase_j_outcome_unlock_2026-07-15`.

---

## Revisit when

1. Calibration lift ≥5% on holdout≥30, **twice**.
2. Shadow MAE clearly beats live on a large holdout shadow sample.
3. Re-run: `python -m feedback.jobs.run_feedback_evaluation --holdout-size 30`

See [10_PRODUCTION_RUNBOOK.md](10_PRODUCTION_RUNBOOK.md).  
Roadmap: [FEEDBACK_LOOP_FUTURE_AFTER_H.md](FEEDBACK_LOOP_FUTURE_AFTER_H.md).
