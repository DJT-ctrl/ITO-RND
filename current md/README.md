# Current MD — Feedback Loop (active work)

**Updated:** 2026-07-15 (post-F engineering package)  
**Purpose:** Single place for the docs we are actively using right now (Phase F re-runs, ops, roadmap).

Historical design notes (01–08) stay in [`planning/validation-feedback-loop/`](../planning/validation-feedback-loop/).

---

## Start here

| Priority | Doc | What it is |
|----------|-----|------------|
| 1 | [11_GO_NO_GO.md](11_GO_NO_GO.md) | Latest ship decision (calibration / injection ON or OFF) |
| 2 | [10_PRODUCTION_RUNBOOK.md](10_PRODUCTION_RUNBOOK.md) | Safe flags, how to run evals / staging ops |
| 3 | [09_BUILD_PLAN.md](09_BUILD_PLAN.md) | Phase checklist (A–J + I/G+) living tracker |
| 4 | [FEEDBACK_LOOP_FUTURE_AFTER_H.md](FEEDBACK_LOOP_FUTURE_AFTER_H.md) | What’s next (F ops, caching, H+, K) |
| 5 | [FEEDBACK_LOOP_GAPS_A_H.md](FEEDBACK_LOOP_GAPS_A_H.md) | What’s still open vs deferred from A–H |
| 6 | [FEEDBACK_LOOP_PART2_PLAN.md](FEEDBACK_LOOP_PART2_PLAN.md) | Original Part 2 spec (reference) |
| 7 | [12_AGE_AWARE_VALIDATION.md](12_AGE_AWARE_VALIDATION.md) | Age/mode metadata + optional AI learning filter |

---

## Current status (short)

- Phases A–J **engineering done**; post-F package also landed:
  - I.1 async `feedback_jobs` queue + worker
  - I.2 cluster roll-ups + injection formats (`rollup_top2` / `rollup_contrastive`)
  - G+ auto-approve (default OFF)
- Live: feedback ON, calibration OFF, injection OFF, injectability `hard_lock`
- Shadow mode ON; Phase F still **NO-GO** (cal lift 2.97% < 5%)
- Deferred: Gemini context caching (I.3), H+ k-means, Phase K
- **Age-aware validation (new):** grades store `validation_age_hours` / `validation_mode`; filter default **OFF**. See [12_AGE_AWARE_VALIDATION.md](12_AGE_AWARE_VALIDATION.md).
- Operate: drain queue after validates; keep collecting with shadow; re-run F when N grows

---

## Archive / background

| Location | Contents |
|----------|----------|
| [`planning/validation-feedback-loop/`](../planning/validation-feedback-loop/) | 01–08 design docs + index |
| Stub files at old paths | Point here so old links still work |
