# Feedback Loop — Gaps & Incomplete Work (Phases A–H)

**Date:** 2026-07-14  
**Purpose:** Track what is **not fully done** across Phases 0–H, even when the phase is marked “complete” or “staging.”  
**Companion:** [FEEDBACK_LOOP_FUTURE_AFTER_H.md](FEEDBACK_LOOP_FUTURE_AFTER_H.md) for work after H.

**Current prod baseline** (Phase F): feedback records **ON**; calibration and injection **OFF**.  
See [planning/validation-feedback-loop/11_GO_NO_GO.md](planning/validation-feedback-loop/11_GO_NO_GO.md).

**Triage tags** on open checkboxes:

| Tag | Meaning |
|-----|---------|
| **Fillable now** | Engineering work in this fill pass (Phases 1–3) |
| **Ops-only** | Needs human review / live DB / API spend; checklist only |
| **Out of scope** | Deferred — see [Out of scope appendix](#out-of-scope-appendix-a–h-fill) |

---

## Summary

| Phase | Label | Open items |
|-------|-------|------------|
| 0 | Foundation | None blocking |
| A | Calibration | Prod OFF; gate not met (1.48% lift < 5%) — OOS |
| B | Template feedback | None blocking |
| C | Metadata routing | Routing MAE job landed; run ops when embeddings exist |
| D | Injection | Prod OFF; caching / advanced formats — OOS |
| E | Observability | None blocking |
| F | Prove lift | Shadow + re-open gates — OOS |
| G | Hybrid LLM | Cost plumbing done; ≥10 approved v2 ops-only; injection — OOS |
| H | Embeddings | Jobs + tests landed; full backfill ops-only; k-means/labels — OOS |

---

## Phase 0 — Foundation

**Status:** Done. No open engineering gaps.

Validation pipeline grades predictions (collect → predict → validate → score). See [planning/validation-feedback-loop/02_VALIDATION_PIPELINE.md](planning/validation-feedback-loop/02_VALIDATION_PIPELINE.md).

---

## Phase A — Passive calibration

**Status:** Code done; **prod OFF** (Phase F no-go).

### Done

- `feedback/calibration.py` — `mean_delta`, `N_min` gate, clamp
- Wired in `validation_pipeline/predict.py`
- Telemetry: raw vs calibrated on `PredictionTelemetry`

### Not done / blocked

- [ ] **Out of scope** — **Turn calibration ON in prod** — requires raw→calibrated MAE improvement ≥5% on holdout≥30, stable over 2 runs ([11_GO_NO_GO.md](planning/validation-feedback-loop/11_GO_NO_GO.md))
- [ ] **Out of scope** — **Per-cluster calibration ship criteria** — cluster training N≥50 and better than global; not separately evaluated for prod ON
- [ ] **Ops-only** — Re-run eval after corpus drift or major validation bulk import:  
  `python -m feedback.jobs.run_feedback_evaluation --holdout-size 30`

---

## Phase B — Structured feedback (templates)

**Status:** Done.

### Done

- `prediction_feedback` table + v1 template generator
- Idempotent batch job + post-validate hook
- Feedback coverage on Feedback Loop dashboard

### Not done

- None blocking. v2/hybrid is Phase G (separate version rows).

---

## Phase C — Deterministic cluster routing (metadata)

**Status:** Done for metadata buckets; extended by Phase H.

### Done

- `feedback/routing.py` — `length × format × follower` buckets
- `prediction_clusters` stats refresh from feedback rows
- Offline metadata vs embedding routing MAE report job (`python -m feedback.jobs.run_routing_mae_report`)

### Not done

- [ ] **Ops-only** — Run routing MAE after embedding backfill + centroids; save under `data/telemetry/routing_mae_*.json`

---

## Phase D — Prompt injection + A/B flag

**Status:** Code done; **prod injection OFF**; one optimisation deferred.

### Done

- `feedback/retrieve.py` + predictor prompt section
- `VALIDATION_FEEDBACK_INJECTION_ENABLED` flag
- Fail-open predict path; self-exclusion for eval leakage

### Not done

- [ ] **Out of scope** — **Prod injection ON** — blocked: deterministic overwrite prevents MAE lift; needs Phase J (injectability unlock) before re-evaluating
- [ ] **Out of scope** — **Gemini context caching** — deferred in [09_BUILD_PLAN.md](planning/validation-feedback-loop/09_BUILD_PLAN.md); stable prefix not large enough to justify yet
- [ ] **Out of scope** — **Advanced injection formats** — cluster summary + examples, contrastive pairs (see future doc)

**Why injection is “no-go” today:** After the Predictor runs, `apply_deterministic_prediction` in `agents/predictor.py` forces the neighbor-weighted percentile. Lesson text only affects reasoning, not the graded number — so offline arms D and C had identical MAE.

---

## Phase E — Production hardening & observability

**Status:** Done.

### Done

- Predict + feedback telemetry
- Offline harness + CLI + Feedback Loop eval panel (primary 4 arms + D-v1/D-v2 scaffolds)
- Accuracy History raw/calibrated + per-cluster MAE
- Override audit JSONL + [10_PRODUCTION_RUNBOOK.md](planning/validation-feedback-loop/10_PRODUCTION_RUNBOOK.md)

### Not done

- None blocking.

---

## Phase F — Prove lift (offline go/no-go)

**Status:** Offline decision recorded — **NO-GO** for calibration and injection.

### Done

- Holdout=30 eval on N=241 (two identical reports in `data/telemetry/eval_feedback_*.json`)
- [11_GO_NO_GO.md](planning/validation-feedback-loop/11_GO_NO_GO.md)
- Dashboard overrides locked to safe baseline

### Not done

- [ ] **Out of scope** — **Shadow mode** — run calibration/injection in predict path, log shadow scores, serve live safe path; compare 2 weeks or 50 predicts before flipping flags
- [ ] **Out of scope** — **Re-open go/no-go** after Phase J or when calibration clears ≥5% gate on a fresh eval
- [ ] **Out of scope** — **Cluster calibration** — separate prod decision if global ever passes

---

## Phase G — LLM hybrid feedback v2 + human review

**Status:** **Staging infrastructure done**; prod injection still OFF.

### Done

- `feedback/hybrid.py` — `generate_hybrid_feedback` behind `VALIDATION_FEEDBACK_LLM_ENABLED`
- `feedback_review_status` + approved-only retrieve
- Lesson sanitization (`wrap_untrusted_text`)
- Feedback Loop review queue (approve/reject)
- Daily LLM cap + delta threshold settings
- Hybrid writes store `cost_usd` (via `telemetry.pricing.cost_from_tokens`)
- Dashboard **Cost / 100 hybrid** + **Approved v2** metrics
- Runbook ops checklist for ≥10 approved v2
- Eval scaffold arms `*_with_feedback_v1|v2` + `version_preference` (MAE identical until Phase J)

### Not done (original Part 2 DoD)

- [ ] **Ops-only** — **≥10 human-approved v2 rows** reviewed for factual grounding (see runbook checklist)
- [x] **Fillable now** — **Eval Arm D-v2 vs D-v1** — scaffold landed; numeric MAE locked until Phase J
- [x] **Fillable now** — **Cost per 100 validations** from `input_tokens` / `output_tokens` / `cost_usd` on hybrid rows
- [ ] **Out of scope** — **Auto-approve** — explicitly deferred until staging reject rate is low (see future doc)
- [ ] **Out of scope** — **Prod injection with approved v2** — blocked until Phase J + new F-style gate

### How to use staging now

1. Enable **LLM hybrid (v2)** on Feedback Loop (keep injection OFF).
2. Backfill or validate posts with large |delta|.
3. Approve/reject pending rows in **Human review queue**.

---

## Phase H — Embeddings, centroids, ranked retrieve

**Status:** **Staging infrastructure done**; legacy backfill is ops.

### Done

- `predictions.embedding` + `embedding_model_version` on new predicts
- `prediction_clusters.centroid_embedding` + `python -m feedback.jobs.run_cluster_centroids`
- Routing: nearest centroid → metadata fallback
- Ranked retrieve by cosine when query embedding present; prefer v2 over v1
- Embedding backfill job: `python -m feedback.jobs.run_embedding_backfill --limit 50`
- Routing MAE report job: `python -m feedback.jobs.run_routing_mae_report --holdout-size 30`
- CI: same embedding → same cluster_id; fallback chain centroid → metadata → calibration none

### Not done

- [ ] **Ops-only** — **Backfill embeddings** on existing predictions (run job with `--limit`; full corpus is API spend)
- [x] **Fillable now** — **Reproducibility test** in CI — same embedding → same cluster_id
- [x] **Fillable now** — **Offline metadata vs embedding routing MAE** — job + unit tests; run against DB after backfill
- [x] **Fillable now** — **Fallback chain integration test** — centroid → metadata → global calibration none
- [ ] **Out of scope** — **Optional LLM cluster labels** — dashboard-only names; does not affect routing (low priority)
- [ ] **Out of scope** — **k-means / incremental centroids** — current job uses mean embedding per metadata cluster; true k-means deferred until N per cluster justifies it

### Ops

```bash
# Preview eligible rows (no API)
python -m feedback.jobs.run_embedding_backfill --limit 50 --dry-run

# Embed a bounded batch, then refresh centroids + routing MAE
python -m feedback.jobs.run_embedding_backfill --limit 50
python -m feedback.jobs.run_cluster_centroids
python -m feedback.jobs.run_routing_mae_report --holdout-size 30
```

---

## Cross-cutting gaps (A–H)

| Gap | Affects | Notes |
|-----|---------|-------|
| Deterministic percentile overwrite | D, F, G injection proof | `agents/predictor.py` — Phase J (**Out of scope**) |
| Prod learning flags OFF | A, D | By policy until gates pass (**Out of scope**) |
| Shadow mode | F, J | Safe prod experiment path (**Out of scope**) |
| Gemini context caching | D, I | Cost at scale (**Out of scope**) |
| Corpus / benchmark version on predictions | Peer review P1 | Silent lesson rot on corpus refresh (**Out of scope**) |

---

## Quick reference — where to look

| Topic | File |
|-------|------|
| Build tracker | [planning/validation-feedback-loop/09_BUILD_PLAN.md](planning/validation-feedback-loop/09_BUILD_PLAN.md) |
| Part 2 plan | [FEEDBACK_LOOP_PART2_PLAN.md](FEEDBACK_LOOP_PART2_PLAN.md) |
| Go/no-go | [planning/validation-feedback-loop/11_GO_NO_GO.md](planning/validation-feedback-loop/11_GO_NO_GO.md) |
| Runbook | [planning/validation-feedback-loop/10_PRODUCTION_RUNBOOK.md](planning/validation-feedback-loop/10_PRODUCTION_RUNBOOK.md) |
| Hybrid generator | [feedback/hybrid.py](feedback/hybrid.py) |
| Retrieve / inject | [feedback/retrieve.py](feedback/retrieve.py) |
| Routing | [feedback/routing.py](feedback/routing.py) |
| Centroids job | [feedback/jobs/run_cluster_centroids.py](feedback/jobs/run_cluster_centroids.py) |
| Embedding backfill | `python -m feedback.jobs.run_embedding_backfill --limit 50` |
| Routing MAE report | `python -m feedback.jobs.run_routing_mae_report --holdout-size 30` |
| Offline eval | `python -m feedback.jobs.run_feedback_evaluation --holdout-size 30` |

---

## Out of scope appendix (A–H fill)

Items that require work beyond closing A–H staging gaps. Full placement and ops steps:
[FEEDBACK_LOOP_FUTURE_AFTER_H.md](FEEDBACK_LOOP_FUTURE_AFTER_H.md) (staging ops, phase sections, and
[Gaps appendix index](FEEDBACK_LOOP_FUTURE_AFTER_H.md#gaps-appendix-index-a–h--this-doc)).

| Item | Why out of scope for A–H fill |
|------|-------------------------------|
| Phase J soft overwrite + shadow mode | New predictor post-process + `VALIDATION_SHADOW_MODE_*` |
| Prod calibration / injection ON | Policy gates + needs J for injection proof |
| Re-open go/no-go | Process after J / fresh ≥5% calibration |
| Gemini context caching | Phase I |
| Advanced injection formats | Post-J |
| Auto-approve v2 | Explicitly deferred |
| k-means / incremental centroids | Deferred until N justifies |
| LLM cluster labels | Dashboard-only, low priority |
| Corpus/benchmark version on predictions | Peer-review P1 cross-cut |

**Next implementation chat:** start with **Phase J** (shadow + soft overwrite), then re-run Phase F eval.
