# Feedback Loop Production Runbook

## Safe baseline

- `VALIDATION_FEEDBACK_ENABLED=true`
- `VALIDATION_CALIBRATION_ENABLED=false`
- `VALIDATION_FEEDBACK_INJECTION_ENABLED=false`

Keep collecting template feedback while calibration and injection are in
monitor-only mode. Dashboard overrides take precedence over environment values.

**Phase F decision (updated 2026-07-15 afternoon):** calibration and injection stay **OFF** —
see [11_GO_NO_GO.md](11_GO_NO_GO.md). Afternoon re-run (N=702, holdout=30) confirmed
morning: calibration MAE lift **2.97%** (<5% gate). Shadow in holdout **16/30**;
shadow MAE ≉ better than live (delta −0.0004). Keep `hard_lock`; shadow mode ON
for more data is OK. Do not confuse `global_mean_delta` (~5) with MAE lift %.
Feedback Loop UI shows Phase F gate metrics from the latest `eval_feedback_*.json`.

## Phase I — async feedback + roll-ups

After validate, the worker **enqueues** a `feedback_jobs` row (fail-open). Drain with:

```bash
python -m feedback.jobs.run_feedback_worker --limit 20
```

Or **Feedback Loop → Process feedback queue**. Coverage panel shows pending / dead backlog.

Refresh template cluster roll-ups (also runs after cluster stats refresh):

```bash
python -m feedback.jobs.run_cluster_rollups
```

Injection format (default `lessons` = numbered rows):

- `VALIDATION_FEEDBACK_INJECTION_FORMAT=lessons|rollup_top2|rollup_contrastive`
- Dashboard: **Injection format** selectbox

Keep injection OFF in prod until Phase F GO. Formats only matter when injection is ON.

## Phase G+ — auto-approve (staging)

Defaults stay OFF:

```
VALIDATION_FEEDBACK_AUTO_APPROVE_ENABLED=false
VALIDATION_FEEDBACK_AUTO_APPROVE_MAX_PER_DAY=20
VALIDATION_FEEDBACK_AUTO_APPROVE_DELTA_MAX=40
```

When enabled, grounded hybrid rows with `|delta| ≤ cap` and under the daily max
are written `approved` with `reviewed_by=auto_approve`. Prefer human review until
reject rate is low.

## Phase G / H staging

- `VALIDATION_FEEDBACK_LLM_ENABLED=false` by default. Enable only in staging to
  generate v2 hybrid lessons for large misses (`|delta| ≥ VALIDATION_FEEDBACK_LLM_DELTA_MIN`).
- New hybrid rows are `pending` until approved on **Feedback Loop → Human review queue**.
- Injection still uses **approved-only** rows; keep injection OFF in prod.
- Refresh embedding centroids after enough validated predictions have embeddings:

```bash
python -m feedback.jobs.run_cluster_centroids
```

Backfill embeddings on pre-H predictions (API cost — start with a limit):

```bash
python -m feedback.jobs.run_embedding_backfill --limit 50
# then refresh centroids
python -m feedback.jobs.run_cluster_centroids
# optional routing comparison
python -m feedback.jobs.run_routing_mae_report --holdout-size 30
```

### Phase G ops checklist — ≥10 approved v2 rows

1. On **Feedback Loop → Feedback loop settings**, enable **LLM hybrid (v2)** only.
   Keep **Prompt injection** and **Calibration** OFF.
2. Validate or backfill posts with `|prediction_delta| ≥ VALIDATION_FEEDBACK_LLM_DELTA_MIN`
   (default 10), or run `python -m feedback.jobs.run_feedback_batch --limit 50`.
3. Open **Human review queue**. For each pending v2 row, confirm lessons cite only
   grounded numbers (predicted/actual percentiles, deltas) — then **Approve** or **Reject**.
4. Confirm the dashboard shows **Approved v2 ≥ 10** (or run):

```sql
SELECT COUNT(*) FROM prediction_feedback
WHERE feedback_version = 'v2' AND feedback_review_status = 'approved';
```

5. Check **Cost / 100 hybrid** on Feedback Loop coverage (from stored `cost_usd`).
   Document the figure in the eval notes if promoting staging further.

Do **not** turn injection ON for live scores until Phase F re-run passes after
Phase J shadow evidence (2 weeks or 50+ predicts with shadow telemetry).

### Phase J flags (injectability)

Defaults keep live scores safe:

| Flag | Default | Purpose |
|------|---------|---------|
| `VALIDATION_SHADOW_MODE_ENABLED` | `false` | Log soft-blend `shadow_percentile` without changing live score |
| `VALIDATION_INJECTABILITY_MODE` | `hard_lock` | `hard_lock` \| `soft_blend` \| `shadow_only` |
| `VALIDATION_SOFT_BLEND_WEIGHT` | `0.15` | `w` in `neighbor + w*(llm − neighbor)` |

Recommended staging experiment: enable **Shadow mode** and set mode to
`shadow_only` (or leave `hard_lock` + shadow ON). Compare shadow vs live MAE
in eval reports (`shadow_live` block) before flipping soft_blend or prod
calibration/injection.

Dashboard toggles: Feedback Loop → Shadow mode / Injectability mode / Soft blend weight.

### Hybrid cost per 100 validations

Hybrid writes store `input_tokens`, `output_tokens`, and estimated `cost_usd`
(via `telemetry.pricing.cost_from_tokens`). The Feedback Loop coverage panel
shows **Cost / 100 hybrid** = `(SUM(cost_usd) / hybrid_rows) * 100`.


## Evaluate before enabling learning

Run the leakage-safe replay after at least 31 validated rows exist:

```bash
python -m feedback.jobs.run_feedback_evaluation --holdout-size 30
```

Reports are written to `data/telemetry/eval_feedback_*.json`. The holdout rows
are excluded from calibration statistics. Review overall and per-cluster MAE.
When Phase J shadow telemetry is present, reports include `shadow_live` and
injection arms can use `shadow_percentile` so MAE may diverge from control.

Enable global calibration only when:

1. the holdout has at least 30 rows;
2. raw-to-calibrated MAE improves by at least 5%;
3. the result repeats in two evaluation runs.

Enable cluster calibration only for clusters with at least 50 training rows and
better MAE than the global fallback.

With default `hard_lock`, live percentiles stay neighbor-locked. Use shadow
mode to measure injectability without changing user-facing scores; only flip
`soft_blend` or prod injection after gates pass.

## Dashboard overrides

Use **Validation Pipeline → Feedback Loop → Feedback loop settings**. Saving or
resetting settings appends an audit record to
`data/telemetry/feedback_loop_overrides.jsonl`.

To return to environment/default settings:

1. click **Reset to .env defaults**; or
2. stop the app, remove `data/feedback_loop_overrides.json`, and restart.

Do not delete the audit JSONL.

## Backfill and refresh

From the Feedback Loop page:

1. select a bounded backfill limit;
2. run **Generate missing feedback**;
3. run **Refresh cluster stats**;
4. confirm feedback coverage and the cluster refresh timestamp.

### Bulk import vectorized corpus (recommended)

Clear validation data and import **only analysed LinkedIn CSV/JSONL rows that have
matching `.npy` embeddings** from Corpus Pipeline → Vectorisation:

```bash
# Preview vectorized bundles + deduped post count
python3 -m validation_pipeline.jobs.run_bulk_import --dry-run --source vectorized

# Reset + import vectorized corpus (flash-lite enforced)
python3 -m validation_pipeline.jobs.run_bulk_import --reset --source vectorized

# Full bootstrap: import → validate due posts → feedback + clusters
python3 -m validation_pipeline.jobs.run_bulk_import \
  --reset --source vectorized --validate --feedback
```

Legacy raw JSON import remains available with `--source raw|validation|all`.

### Bulk import saved scrapes (legacy raw JSON)

Clear validation data and load all saved LinkedIn JSON scrapes in one pass:

```bash
# Preview counts without predicting
python3 -m validation_pipeline.jobs.run_bulk_import --dry-run --source all

# Reset + import all unique posts (flash-lite enforced)
python3 -m validation_pipeline.jobs.run_bulk_import --reset --source all

# Full bootstrap: import → validate due posts → feedback + clusters
python3 -m validation_pipeline.jobs.run_bulk_import \
  --reset --source all --validate --feedback
```

Sources: `data/raw/linkedin_*.json` (Scraper Stage) and
`data/validation/collect_*.json`. Duplicates are skipped by `linkedin_post_id`.
Posts older than 48h are already due for the validation worker.

CLI alternative:

```bash
python -m feedback.jobs.run_feedback_batch --limit 100
```

Both paths are idempotent for `(prediction_id, feedback_version)`.

## Incident: MAE worsened after calibration

1. Turn **Calibration** off in the dashboard immediately.
2. Export the relevant `eval_feedback_*.json` report and Accuracy History data.
3. Record the affected time range, validated N, mean delta, calibration source,
   cluster id, and prediction methods.
4. Check for a corpus refresh or a cluster with `N < 50` or
   `abs(mean_delta) > 15`.
5. Keep feedback records; do not delete `prediction_feedback`.
6. Re-enable only after a new held-out evaluation passes the gates above.

## Injection rollback

Turn **Prompt injection** off. Existing feedback remains available for analysis
and no redeploy is required. Confirm subsequent prediction telemetry shows
`feedback_injection_enabled=false` and `feedback_injected=false`.
