# Current MD — Feedback Loop (active work)

**Updated:** 2026-07-14  
**Purpose:** Single place for the docs we are actively using right now (Phase F re-runs, ops, roadmap).

Historical design notes (01–08) stay in [`planning/validation-feedback-loop/`](../planning/validation-feedback-loop/).

---

## Start here

| Priority | Doc | What it is |
|----------|-----|------------|
| 1 | [11_GO_NO_GO.md](11_GO_NO_GO.md) | Latest ship decision (calibration / injection ON or OFF) |
| 2 | [10_PRODUCTION_RUNBOOK.md](10_PRODUCTION_RUNBOOK.md) | Safe flags, how to run evals / staging ops |
| 3 | [09_BUILD_PLAN.md](09_BUILD_PLAN.md) | Phase checklist (A–J) living tracker |
| 4 | [FEEDBACK_LOOP_FUTURE_AFTER_H.md](FEEDBACK_LOOP_FUTURE_AFTER_H.md) | What’s next after H/J (F re-run, advanced, I, G+) |
| 5 | [FEEDBACK_LOOP_GAPS_A_H.md](FEEDBACK_LOOP_GAPS_A_H.md) | What’s still open vs deferred from A–H |
| 6 | [FEEDBACK_LOOP_PART2_PLAN.md](FEEDBACK_LOOP_PART2_PLAN.md) | Original Part 2 spec (reference) |

---

## Current status (short)

- Phases A–J **engineering done**
- Live: feedback ON, calibration OFF, injection OFF, injectability `hard_lock`
- Shadow mode ON (~270 rows with shadow telemetry)
- Phase F latest (N=553): cal lift **4.90%** → still **NO-GO** (need ≥5%)
- Shadow holdout 16/30: MAE delta **0** → no soft_blend / injection GO

---

## Archive / background

| Location | Contents |
|----------|----------|
| [`planning/validation-feedback-loop/`](../planning/validation-feedback-loop/) | 01–08 design docs + index |
| Stub files at old paths | Point here so old links still work |
