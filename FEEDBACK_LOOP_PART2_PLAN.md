# Feedback Loop — Part 2 Plan (Production)

**Status:** Planning — ready for next implementation chat  
**Date:** 2026-07-13  
**Audience:** Kevin + team continuing after Part 1 (Phases A–D)  
**Prerequisite:** Part 1 complete — see `planning/validation-feedback-loop/09_BUILD_PLAN.md`

---

## 1. What Part 1 shipped (baseline)

Part 1 built the **closed-loop skeleton**:

| Piece | What it does today | Limitation |
|-------|-------------------|------------|
| **A — Calibration** | `calibrated = clamp(raw + mean_delta, 0, 100)` with global + cluster `N_min` gates | Can hurt accuracy on thin data; no proof it helps MAE yet |
| **B — Template feedback** | `prediction_feedback` rows (`feedback_version=v1`, `generation_method=template`) | Says *how far* wrong, not deep *why* |
| **C — Metadata clusters** | `length × format × follower_band` routing | Coarse buckets; not topic/embedding similarity |
| **D — Prompt injection** | Top-N recent lessons per cluster into Predictor | Unproven lift; no formal A/B in eval harness |
| **Dashboard** | Feedback Loop tab, toggles, manual backfill | Ops-friendly; overrides in `data/feedback_loop_overrides.json` |

**Critical honesty:** Part 1 is **architecturally complete** but **not production-proven**. Turning all flags ON in production before measurement is the main risk.

---

## 2. What “production” means here

Production does **not** mean “more features.” It means:

1. **Safe defaults** — learning mechanisms fail open; cannot silently degrade predictions.
2. **Measurable** — we can attribute MAE changes to calibration vs injection vs corpus drift.
3. **Reversible** — kill switches + rollback without redeploy (flags already exist; need audit + runbook).
4. **Cost-bounded** — any new LLM path has per-run caps and telemetry.
5. **Data-integrity** — validated history does not rot when corpus or benchmarks shift.

**Production recommendation (day 1):**

| Flag | Suggested prod default | Rationale |
|------|------------------------|-----------|
| Calibration | **ON** only after offline eval shows MAE improvement at current N; else **OFF** (monitor only) | Highest product risk on thin data |
| Feedback records | **ON** | Cheap; builds the dataset for everything else |
| Prompt injection | **OFF** until A/B shows lift | Lesson text is unproven; adds tokens + hallucination surface |

Template feedback storage should stay ON even when injection is OFF — you are collecting training signal for Part 2.

---

## 3. Gap analysis (Part 1 → production)

Items flagged in peer review (`07_PEER_REVIEW.md`) that are **still open**:

| Gap | Risk if ignored | Part 2 priority |
|-----|-----------------|-----------------|
| Raw vs calibrated telemetry in eval harness | Cannot prove calibration works | **P0** |
| Formal A/B (`feedback_enabled` arms) | False confidence in injection | **P0** |
| Eval leakage rules (exclude self + holdout) | Inflated accuracy | **P0** |
| Corpus benchmark versioning on predictions | Silent lesson rot | **P1** |
| Embedding persistence for validated RAG | Re-embed drift; costly retrieval | **P1** |
| Per-cluster MAE dashboard | Cannot see which buckets fail | **P1** |
| Async feedback job (not inline in worker) | Worker latency / failure coupling | **P1** |
| LLM hybrid lessons (`v2`) | Templates too shallow for “why” | **P2** (after proof) |
| Embedding centroids for routing | Metadata buckets too coarse at scale | **P2** |
| Gemini context caching | Cost at scale | **P3** |
| Human review queue for LLM lessons | Bad lessons injected into prompts | **P2** (with LLM) |

---

## 4. Part 2 phases (recommended order)

Do **not** skip Phase E. Phases F–I depend on it.

```
Part 1 (done)     Part 2
─────────────     ─────────────────────────────────────────────
A Calibration  →  E  Observability + eval harness + prod gates
B Templates    →  F  Prove lift (offline + shadow mode)
C Metadata     →  G  LLM hybrid feedback v2 + human review
D Injection    →  H  Smarter routing + ranked retrieval
                  I  Scale (async queue, caching, roll-ups)
```

---

### Phase E — Production hardening & observability (P0)

**Goal:** Every learning decision is logged, attributable, and killable.

**Build:**

1. **Telemetry extension** (`telemetry/` + predict/validate paths)
   - On every predict: `raw_percentile`, `calibrated_percentile`, `calibration_applied`, `mean_delta`, `n_validated`, `calibration_source` (global/cluster/none), `cluster_id`
   - On every predict: `feedback_injected`, `feedback_count`, `feedback_version`, injection token estimate (chars or tokens)
   - On feedback generate: `generation_method`, latency, cost (0 for template)
   - Persist to existing eval JSON / telemetry store (match `data/telemetry/eval_*.json` pattern)

2. **Eval harness arms** (reuse evaluation cycle)
   - `VALIDATION_CALIBRATION_ENABLED` × `VALIDATION_FEEDBACK_INJECTION_ENABLED` → 4 arms
   - Held-out validated set: never inject feedback from holdout rows; exclude current `prediction_id`
   - Report: MAE, % within 10 pts, per-cluster MAE — **raw vs calibrated** side by side

3. **Accuracy History upgrades**
   - Chart: MAE trend split by `prediction_method` (raw / `+calibrated` / `+cluster+calibrated`)
   - Per-cluster MAE table (new store query)
   - “Learning active?” banner: N, gate status, last refresh

4. **Ops runbook** (`deploy/` or `planning/validation-feedback-loop/`)
   - When to turn calibration ON/OFF
   - How to clear `data/feedback_loop_overrides.json`
   - Backfill procedure: `run_feedback_batch` + `refresh_cluster_stats`
   - Incident: “MAE got worse after calibration” → disable flag, file issue with telemetry export

5. **Dashboard override audit** (lightweight)
   - Append-only log when Feedback Loop settings saved (who/when/what) — even a JSONL in `data/telemetry/`

**Definition of done:**

- [ ] Eval run produces comparison report for all 4 arms on ≥30 held-out validated rows
- [ ] Accuracy History shows raw vs calibrated MAE when data exists
- [ ] Runbook reviewed by team
- [ ] No new predict path without telemetry fields (see `08_BUILD_PRACTICES.md` § observability)

**Estimated effort:** 1–2 focused PRs.

---

### Phase F — Prove lift before expanding learning (P0)

**Goal:** Data-driven go/no-go for calibration and injection in production.

**Method:**

1. **Offline replay** — re-score held-out validated predictions:
   - Arm A: raw neighbor percentile only (control)
   - Arm B: + global calibration
   - Arm C: + cluster calibration
   - Arm D: + injection (template lessons)

2. **Success gates** (suggest starting thresholds; tune with team):

   | Mechanism | Ship to prod when… | Kill switch when… |
   |-----------|-------------------|-------------------|
   | Global calibration | MAE improves ≥5% vs raw at N≥30, stable over 2+ eval runs | MAE worsens ≥3% for 1 week |
   | Cluster calibration | Per-cluster MAE improves for clusters with N≥50 | Any cluster with \|mean_delta\| > 15 and N<50 |
   | Injection | Arm D beats Arm C on MAE or % within 10 pts | No lift after 100+ validated rows |

3. **Shadow mode** (optional but valuable)
   - Run calibration + injection in predict path but **do not** use for user-facing output; log what *would* have been scored
   - Compare shadow vs live for 2 weeks before flipping prod default

**Definition of done:**

- [ ] Written go/no-go decision doc (1 page) with actual numbers from your corpus
- [ ] Prod defaults updated based on evidence, not optimism
- [ ] `09_BUILD_PLAN.md` or this file updated with decision

**Estimated effort:** Mostly analysis + harness wiring; 1 PR if Phase E telemetry exists.

---

### Phase G — LLM hybrid feedback v2 (P2)

**Goal:** Actionable “why” lessons without hallucination or unbounded cost.

**Only start after Phase F shows template-only injection is worth improving** (or templates plateau on MAE).

**Design:**

1. **Hybrid generator** (`feedback/generate.py` → `generate_hybrid_feedback`)
   - \|delta\| < 5 → template only (keep v1)
   - \|delta\| ≥ threshold (e.g. 10) → LLM fills `what_missed` + `lessons_for_similar_posts` only
   - **Hard rule:** LLM must cite fields from validated row (percentiles, count deltas, neighbor metadata); reject on schema validation failure

2. **Versioning**
   - `FEEDBACK_VERSION = "v2"` for LLM-enriched rows
   - `generation_method = "llm"` or `"hybrid"`
   - Retrieval/injection: prefer v2 within cluster when present; fall back to v1

3. **Human review queue** (required for prod LLM lessons)
   - New status: `feedback_review_status` = `pending` | `approved` | `rejected`
   - **Only `approved` rows injectable** in production
   - Dashboard panel on Feedback Loop: review high-magnitude misses first
   - Skip auto-approve until error rate is low in staging

4. **Cost controls**
   - Settings: `VALIDATION_FEEDBACK_LLM_ENABLED`, max LLM rows per day, max \|delta\| for LLM
   - Telemetry: token cost per feedback row

5. **Prompt safety**
   - Feedback block is untrusted text; wrap with same sanitization as `agents/prompt_safety.py`
   - Never let lesson text override deterministic percentile requirements (already stated in `retrieve.py`)

**Definition of done:**

- [ ] ≥10 human-approved v2 rows reviewed for factual grounding
- [ ] Injection uses approved-only in prod
- [ ] Eval shows Arm D-v2 vs Arm D-v1 on held-out set
- [ ] Cost per 100 validations documented

**Estimated effort:** 2–3 PRs (generator, schema/migration, review UI).

---

### Phase H — Smarter routing & retrieval (P2)

**Goal:** Clusters match *similar* posts, not just similar shape metadata.

**Prerequisites:** Phase E embedding persistence; enough validated rows per centroid.

**Build:**

1. **Persist embedding at predict time**
   - Store vector reference (or copy) on `predictions` when prediction is created
   - Pin `embedding_model_version` / corpus id

2. **Embedding centroids** (`prediction_clusters` extension)
   - Offline job: k-means or incremental centroid update on validated embeddings
   - Routing: `assign_cluster_id` → nearest centroid; metadata bucket as fallback when cluster N < min

3. **Ranked retrieval within cluster**
   - Today: newest N lessons
   - Upgrade: rank by cosine similarity to current post embedding, then recency
   - Still cap at `VALIDATION_FEEDBACK_INJECTION_LIMIT`

4. **Cluster labels** (optional LLM)
   - One-time or periodic human-readable label for dashboard only — **does not affect routing**

**Definition of done:**

- [ ] Same post always routes to same cluster (reproducibility test)
- [ ] Per-cluster MAE compared: metadata vs embedding routing
- [ ] Fallback chain tested: centroid → metadata → global → none

**Estimated effort:** 2 PRs (data model + routing/retrieve).

---

### Phase I — Scale & cost (P3)

**Goal:** Sustainable cost and worker reliability at higher validation volume.

**Build:**

1. **Async feedback queue**
   - Worker enqueues `prediction_id` after `mark_validated`; separate job processes queue
   - Idempotent upsert (already designed); dead-letter for failures
   - Decouple rescrape success from feedback latency

2. **Cluster roll-up summaries**
   - Periodic job: one paragraph per cluster (`mean_delta`, common miss patterns, N)
   - Inject summary + top 2 recent examples instead of 5 full rows (smaller prompt)

3. **Gemini context caching**
   - Cache stable prefix: global instructions + cluster summary block
   - Refresh cache on cluster stats recompute, not every validation
   - Track cache hit rate in telemetry

4. **Multi-window validation** (optional, coordinate with T7)
   - Store 48h as primary grade; optional 7d snapshot for long-tail posts
   - Feedback version tied to validation window

**Definition of done:**

- [ ] Worker p99 latency unchanged when feedback LLM is enabled
- [ ] Token cost per predict reduced ≥20% vs uncached at target volume
- [ ] Queue backlog visible in dashboard or logs

---

## 5. Production rollout playbook

### Stage 0 — Collect only (week 1–2)

- Feedback records: **ON**
- Calibration: **OFF**
- Injection: **OFF**
- Target: ≥30 validated rows, coverage ≈100%

### Stage 1 — Calibration candidate (week 3+)

- Run Phase F offline eval
- If pass: Calibration **ON**, Injection still **OFF**
- Monitor MAE weekly in Accuracy History

### Stage 2 — Injection candidate

- If calibration stable: enable injection in **shadow**, then treatment
- Start with `VALIDATION_FEEDBACK_INJECTION_LIMIT=3`

### Stage 3 — v2 LLM lessons (optional)

- Staging only → human review → prod approved-only injection

### Rollback (any stage)

1. Feedback Loop dashboard → turn offending flag OFF → Save  
2. Or delete `data/feedback_loop_overrides.json` and set env vars  
3. Re-run `refresh_cluster_stats` only if cluster table corrupted  
4. Do **not** delete `prediction_feedback` rows — history is valuable

---

## 6. Success metrics (production KPIs)

| KPI | Source | Target (initial) |
|-----|--------|------------------|
| Validated N | Feedback coverage panel | ≥30 before global calib ON |
| Feedback coverage | `missing_feedback / validated` | <5% |
| MAE (percentile) | Accuracy History | Down vs baseline after calib ON |
| % within 10 pts | `fetch_accuracy_aggregates` | Up vs baseline |
| Per-cluster MAE | New query (Phase E) | No cluster >2× global MAE |
| Calibration apply rate | Telemetry | Logged; not 100% until N sufficient |
| Injection token cost | Telemetry | Below eval cost warning threshold |
| LLM lesson reject rate | v2 generator | <10% schema failures |

---

## 7. Risks ranked (production lens)

1. **Thin-data calibration** — applying offset at N=15 hurts more than helps. **Mitigation:** Phase F gates; default OFF until proven.
2. **Corpus percentile drift** — same engagement maps to different percentile after corpus refresh. **Mitigation:** benchmark version on prediction; regenerate feedback only on version bump.
3. **Eval leakage** — injecting holdout lessons. **Mitigation:** Phase E harness rules; unit tests on `fetch_cluster_feedback(exclude_prediction_id=…)`.
4. **LLM hallucination in lessons** — plausible but false “why.” **Mitigation:** hybrid + human review + approved-only injection.
5. **Ops confusion** — dashboard overrides vs `.env`. **Mitigation:** runbook + override audit log.
6. **Worker coupling** — feedback failures block validation perception. **Mitigation:** Phase I async queue; already fail-open in code — verify in integration tests.
7. **Cost spike** — LLM per validation at scale. **Mitigation:** daily caps, \|delta\| threshold, template-first forever for small misses.

---

## 8. Explicitly out of scope for Part 2

- Fine-tuning predictor or embedding models
- LLM-based cluster routing
- Tabular / transformer models on structured features
- Backfilling validated posts into main corpus (defer until 48h window trusted)
- Replacing deterministic percentile with LLM-generated numbers

---

## 9. Open decisions (resolve in first Part 2 chat)

| # | Question | Recommendation |
|---|----------|----------------|
| 1 | Prod default for calibration ON day 1? | **OFF** until Phase F pass |
| 2 | \|delta\| threshold for LLM v2? | Start 10 pts; tune in staging |
| 3 | Human review required for all LLM rows? | **Yes** for prod injection |
| 4 | Embedding on `predictions` vs side table? | Side table or nullable column + version |
| 5 | When to invest in embedding centroids? | When any metadata cluster has N≥100 validated |
| 6 | Shadow mode duration? | 2 weeks or 50 predicts, whichever first |

---

## 10. File map for the next chat

| Area | Start here |
|------|------------|
| Part 1 context | `planning/validation-feedback-loop/README.md`, `09_BUILD_PLAN.md` |
| Peer review risks | `planning/validation-feedback-loop/07_PEER_REVIEW.md` |
| Code layout rules | `planning/validation-feedback-loop/08_BUILD_PRACTICES.md` |
| Calibration math | `feedback/calibration.py`, `validation_pipeline/predict.py` |
| Template feedback | `feedback/generate.py`, `feedback/batch.py` |
| Injection | `feedback/retrieve.py`, `agents/predictor.py` |
| Dashboard | `dashboard/pages/validation/10_Feedback_Loop.py`, `feedback/ui.py` |
| Runtime toggles | `feedback/runtime_flags.py`, `data/feedback_loop_overrides.json` |
| Eval / telemetry | `telemetry/`, `data/telemetry/eval_*.json` |
| Tests to extend | `tests/test_feedback_*.py`, `tests/test_validation_predict.py` |

**Suggested first PR in Part 2:** Phase E telemetry + eval harness arms (smallest step that unlocks everything else).

---

## 11. Checklist to paste into next session

```
Part 2 — Session start
[ ] Read this file + 09_BUILD_PLAN.md
[ ] Confirm validated N and current MAE baseline
[ ] Phase E: telemetry fields on predict + feedback generate
[ ] Phase E: eval harness 4-arm comparison
[ ] Phase E: per-cluster MAE in Accuracy History
[ ] Phase F: run offline eval, record go/no-go
[ ] Update prod defaults based on evidence
[ ] Only then: Phase G (v2 LLM) or Phase H (embeddings)
```

---

## Bottom line

Part 1 built the **pipes**. Part 2 must prove the **water is safe to drink** before turning learning on in production. Measure first (Phase E–F), then deepen lessons (Phase G) and routing (Phase H), then optimize cost (Phase I). Skipping proof and shipping LLM “why” feedback would optimize for narrative, not accuracy.
