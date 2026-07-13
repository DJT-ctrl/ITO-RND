# Feedback Loop Production Runbook

## Safe baseline

- `VALIDATION_FEEDBACK_ENABLED=true`
- `VALIDATION_CALIBRATION_ENABLED=false`
- `VALIDATION_FEEDBACK_INJECTION_ENABLED=false`

Keep collecting template feedback while calibration and injection are in
monitor-only mode. Dashboard overrides take precedence over environment values.

## Evaluate before enabling learning

Run the leakage-safe replay after at least 31 validated rows exist:

```bash
python -m feedback.jobs.run_feedback_evaluation --holdout-size 30
```

Reports are written to `data/telemetry/eval_feedback_*.json`. The holdout rows
are excluded from calibration statistics. Review overall and per-cluster MAE.

Enable global calibration only when:

1. the holdout has at least 30 rows;
2. raw-to-calibrated MAE improves by at least 5%;
3. the result repeats in two evaluation runs.

Enable cluster calibration only for clusters with at least 50 training rows and
better MAE than the global fallback.

Prompt injection cannot currently improve numeric MAE: deterministic
post-processing fixes the percentile after the model runs. Injection arms are
retained to expose that constraint and measure future architecture changes.

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
