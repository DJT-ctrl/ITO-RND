# 08 — Build Practices (Sort, Refactor, Code Quality)

**Status:** Implementation guide  
**Audience:** Anyone opening PRs against validation / feedback work  
**Read after:** [07 — Peer Review](07_PEER_REVIEW.md)

This doc exists so the feedback loop is built with the same discipline as the measurement pipeline: small modules, clear boundaries, tests first for deterministic logic, and no drive-by mess.

---

## Goals

1. **Sort** — keep related code in one place; one module = one job  
2. **Refactor** — clean the path *before* bolting on learning (especially worker/store)  
3. **Good practices** — match existing patterns; prefer boring, testable code over clever agents

---

## Target package layout

Keep `validation_pipeline/` as the home for measurement. Add feedback as a sibling concern so the worker does not become a god-module.

```
validation_pipeline/          # grading: collect → predict → wait → rescrape → score
├── collect.py
├── predict.py
├── pipeline.py
├── rescrape.py
├── scoring.py
├── store.py                  # predictions + snapshots only
├── schemas.py                # prediction / validation Pydantic models
├── worker.py                 # orchestrate due validations; enqueue feedback (thin)
├── ui.py
└── jobs/

feedback/                     # learning: generate → store → retrieve → calibrate
├── __init__.py
├── schemas.py                # FeedbackRecord, DeltaSummary, etc.
├── store.py                  # prediction_feedback + cluster reads/writes
├── calibration.py            # mean_delta, N_min gates, apply offset
├── generate.py               # template (Phase B) → LLM later
├── retrieve.py               # cluster-scoped RAG (Phase C/D)
├── routing.py                # deterministic cluster assignment (Phase C)
└── jobs/
    └── run_feedback_batch.py
```

**Rules:**
- `validation_pipeline.worker` may **enqueue** feedback by `prediction_id`; it must not generate LLM text or mutate feedback tables inline
- `feedback.calibration` may be called from `processors/benchmark.py` — keep the math pure and unit-tested
- Dashboard pages stay thin: call store/UI helpers; no SQL in Streamlit pages

If `feedback/` feels premature for the first PR, start with `validation_pipeline/calibration.py` + `validation_pipeline/feedback_store.py`, then extract the package once Phase B lands. Do not leave calibration logic inside `scoring.py` or `worker.py`.

---

## Sort before you add

Before the first feedback PR, do a short hygiene pass on what already exists:

| Smell | Preferred fix |
|-------|----------------|
| New DB connection per status flip in `worker.py` | One connection (or short-lived context) per prediction / batch; shared helper |
| Scoring + corpus fetch mixed with orchestration | Keep `scoring.py` pure; I/O stays in store/worker |
| Dashboard duplicating pipeline logic | Reuse `validation_pipeline.ui` / store helpers |
| Settings scattered as magic numbers | Named settings (`VALIDATION_*`, later `FEEDBACK_*`) in `config/settings.py` |
| Large unstructured dicts crossing boundaries | Pydantic models in `schemas.py` |

**Do not** refactor unrelated scrapers, analysers, or dashboard pages in the same PR as feedback. Scope each PR to one concern (conventional commits: `refactor:`, `feat:`, `test:`).

---

## Implementation order (matches plan phases)

```
1. refactor  — worker/store connection & boundaries (if needed)
2. feat      — Phase A calibration (pure functions + settings gate + telemetry)
3. feat      — prediction_feedback migration + store
4. feat      — template feedback batch job (idempotent)
5. feat      — deterministic routing + retrieve
6. feat      — predict-time injection + A/B flag
7. chore     — context caching only when injection volume justifies it
```

Each step should leave `pytest` green and the validation dashboard usable.

---

## Coding standards for this work

### Prefer pure functions for math

Calibration, delta scoring, and template feedback assembly should be:

```python
def apply_calibration(raw_percentile: float, mean_delta: float, n: int, n_min: int) -> float:
    ...
```

No DB, no network, no Streamlit. Unit-test edge cases: `n < n_min`, clamping to `[0, 100]`, sign of delta.

### Schemas first

- Add/extend Pydantic models before SQL or LLM prompts
- Feedback JSON must validate on write; reject and log on parse failure
- Version field (`feedback_version`) is required from day one

### Idempotency

- Re-running the feedback job for the same validated prediction must not create duplicate “truth”
- Prefer upsert on `(prediction_id, feedback_version)` or delete-and-replace for that version

### Fail closed on learning, fail open on prediction

- If calibration/feedback retrieval fails → **predict without it**, log the error  
- If rescrape/scoring fails → mark `failed` as today; do not invent feedback

### No secrets / no live Apify in unit tests

- Follow existing tests: mock Apify, mock store where needed
- Integration tests that hit DB should be explicit and skippable if no DSN

### Migrations

- Schema changes go through the project’s normal schema path (`storage/schema.sql` + apply path the repo already uses)
- Do not hand-edit prod tables
- New tables: `prediction_feedback`, later `prediction_clusters` — as in [04 — Data Model](04_DATA_MODEL.md)

### Telemetry

Every new path that can change a percentile or spend money must emit enough fields to explain Accuracy History later (raw vs calibrated, method, cluster_id, N, cost/latency).

### Commits & PRs

- Conventional commits (`feat`, `fix`, `refactor`, `test`, `chore`)
- Small PRs: one phase slice per MR where possible
- PR description: what changed, how to test, link to the planning doc section

---

## Refactor checklist (use on each PR)

- [ ] Module has a single responsibility; name matches job  
- [ ] No new circular imports (`feedback` may import validation schemas/store reads; validation must not import LLM feedback generators)  
- [ ] Public functions have type hints; Pydantic at boundaries  
- [ ] Deterministic logic covered by unit tests  
- [ ] Settings/env for behaviour flags — not hardcoded toggles in business logic  
- [ ] Dashboard unchanged unless the PR is explicitly UI  
- [ ] No commented-out code, no speculative abstractions “for later”  
- [ ] Logging explains *why* calibration/feedback was skipped (cold start, low N, error)

---

## Anti-patterns (do not do)

| Anti-pattern | Do instead |
|--------------|------------|
| Dump all validated history into the predictor prompt | Cluster + top-N + summary stats |
| Fine-tune or train a tabular model “quickly” | Stick to retrieval + calibration ([05](05_TECHNICAL_APPROACH.md)) |
| LLM assigns `cluster_id` | Deterministic routing only |
| Generate feedback inside the rescrape `try` block | Enqueue after successful `mark_validated` |
| Apply global offset with N=5 | Gate on `N_min`; log only until then |
| Rewrite historical percentiles when corpus changes | Version the corpus benchmark used at validate time |
| Giant “utils.py” for feedback | Named modules (`calibration`, `generate`, `retrieve`) |

---

## Definition of done (per phase)

### Phase A — Passive calibration
- [ ] Pure calibration helpers + tests (including sign convention)
- [ ] `N_min` gate + settings flag
- [ ] Telemetry: raw vs calibrated
- [ ] No new LLM calls
- [ ] Validation worker behaviour unchanged aside from optional enqueue stub (or none yet)

### Phase B — Structured feedback
- [ ] Migration + store + Pydantic schema
- [ ] Template generator, idempotent batch job
- [ ] Only `validated` rows
- [ ] Tests for schema validation and upsert behaviour

### Phase C/D — Routing + injection
- [ ] Deterministic routing tests (same input → same cluster)
- [ ] Retrieval excludes self / holdout when flagged
- [ ] Predict path degrades gracefully with empty feedback
- [ ] A/B or `feedback_enabled` flag wired through eval harness

---

## Quick reference: where to put new code

| Change | Put it here |
|--------|-------------|
| Rescrape / score / due-queue | `validation_pipeline/` |
| mean_delta / offset math | `feedback/calibration.py` (or temporary `validation_pipeline/calibration.py`) |
| Feedback JSON generate | `feedback/generate.py` |
| Feedback DB | `feedback/store.py` |
| Cluster assign | `feedback/routing.py` |
| Predict-time context block | consumed from `validation_pipeline/predict.py` / predictor agent — built by `feedback/retrieve.py` |
| New Streamlit widgets | `validation_pipeline/ui.py` + existing validation pages |
| New settings | `config/settings.py` |

---

## Related docs

- [02 — Validation Pipeline](02_VALIDATION_PIPELINE.md) — what not to break  
- [03 — Feedback System](03_FEEDBACK_SYSTEM.md) — phase ladder  
- [04 — Data Model](04_DATA_MODEL.md) — tables to add  
- [05 — Technical Approach](05_TECHNICAL_APPROACH.md) — stack constraints  
- [06 — Open Questions](06_OPEN_QUESTIONS.md) — first PR slice  
- [07 — Peer Review](07_PEER_REVIEW.md) — risks and gates  
