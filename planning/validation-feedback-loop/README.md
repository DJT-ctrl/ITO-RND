# Validation Feedback Loop — Planning

**Date:** 2026-07-12  
**Status:** Planning — team review before build  
**Owner:** Daniel  
**Context:** Extends the validation pipeline from measurement (predict → wait → compare) into a closed-loop learning system that improves future predictions.

---

## What this is

Two related but distinct layers:

1. **Validation pipeline** — Re-scrape engagement ~48 hours after publish, compare actuals to `predicted_engagement_percentile`, persist deltas. This is the *grading mechanism* during testing.
2. **Feedback system** — Use those grades to tell the AI what it got right, where it missed, and inject that knowledge into future predictions. This is the *learning mechanism*.

The validation pipeline is partially built (`validation_pipeline/`). The feedback system is the next big job.

---

## Documents

| Doc | Contents |
|-----|----------|
| [01 — Completed Work (Phase X)](01_COMPLETED_WORK.md) | Recent infrastructure Daniel shipped |
| [02 — Validation Pipeline](02_VALIDATION_PIPELINE.md) | 48h re-scrape, delta scoring, lifecycle |
| [03 — Feedback System](03_FEEDBACK_SYSTEM.md) | Closed-loop design: what goes back to the AI |
| [04 — Data Model](04_DATA_MODEL.md) | Predictions delta table, historical data with predictions attached |
| [05 — Technical Approach](05_TECHNICAL_APPROACH.md) | Why not fine-tuning; clustering + RAG strategy |
| [06 — Open Questions](06_OPEN_QUESTIONS.md) | Decisions still to make with the team |

---

## Relationship to existing docs

- **T6 Engineering Gaps #1** — identified the feedback-loop gap; validation pipeline addresses the measurement half.
- **T7 A4 (Engagement-Decay Capture)** — related but separate; multi-window rescrapes inform *when* to grade, not *how* to learn.
- **Codebase today** — `validation_pipeline/` (collect → predict → worker rescrape → scoring), `predictions` table, `prediction_engagement_snapshots`, Accuracy History dashboard.

---

## Guiding principles (from team discussion)

- **Avoid fine-tuning** for engagement prediction — platform algorithms shift too often; retraining would be slow, expensive, and fragile.
- **Keep base data and predictions together** — historical pulls should include the prediction snapshot, not just raw post data.
- **Cluster as we grow** — don't dump unbounded context into prompts; route inputs to the right cluster first (deterministic routing, not an LLM agent), then rank within it.
- **Context caching at scale** — cache stable cluster/global summaries to cut Gemini cost; learning still comes from the database.
- **No structured data transformers** — retrieval + calibration fits this problem better than tabular ML models.
- **Plan before building** — this is a large step; share with the team and align on data model + approach first.
