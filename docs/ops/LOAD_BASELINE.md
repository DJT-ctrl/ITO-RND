# Post-launch load testing and performance baseline

Issue **#21** — reproducible load scripts, published baseline, and measurable
targets for the next release. Feeds orchestrator tuning in **#22**. Prefer
running live baselines after **#5** (CI quality gates) and **#8** (SLOs/alerts)
so Prometheus histograms match these scenarios.

Scripts: [`scripts/load/`](../../scripts/load/).

## How to reproduce

### A. Offline stub (CI-friendly, no Gemini/DB)

```bash
python scripts/load/stub_api.py &
STUB_PID=$!
python scripts/load/run_load_test.py --scenario baseline \
  --base-url http://127.0.0.1:8010 \
  --output /tmp/ito-load-baseline-stub.json
kill $STUB_PID
```

### B. Live Compose stack (staging / local with corpus)

```bash
docker compose up -d
# GEMINI_API_KEY set; posts ingested into pgvector
python scripts/load/run_load_test.py --scenario baseline \
  --output /tmp/ito-load-baseline-live.json
```

Compare route `latency_ms.p95` and `throughput_rps` against the targets below.
Grafana **ITO Stack Overview** / Prometheus `http_request_duration_seconds`
should agree within measurement noise when #8 alerts are wired.

## Hot-path profile (code)

| Stage | Where | Cost driver |
| ----- | ----- | ----------- |
| Embed draft | `processors/embedder.embed_query` via `api/main.py` / `agents/orchestrator._gather_similar_posts` | Sync Gemini HTTP; no request-level cache |
| Vector search | `storage/vector_store.find_similar` | HNSW on `halfvec(3072)`; new DB connection per call |
| Setup extras (evaluate) | voice profile, follower count, discoverability | Extra sync DB / Trends I/O on the event loop via `to_thread` |
| Concurrent agents | predictor + diagnostic workers | Dominant wall time; provider latency + fan-out |
| Finalize variants | `agents/variant_engine` | Additional LLM (+ optional re-embed) after agents |

## Top 3 bottlenecks

1. **Multi-agent Gemini fan-out on `/evaluate`** — predictor and diagnostics run
   concurrently, then the variant engine runs sequentially. This dominates p95
   and caps concurrency on a single API worker. Primary focus for **#22**.
2. **Uncached `embed_query` on every request** — both public POST routes pay a
   full embedding round-trip; identical drafts under load amplify provider
   latency and cost with no shared cache.
3. **Per-request Postgres connections (no pool)** — `get_connection()` /
   `conn.close()` on every similar-posts and each evaluate setup step adds
   handshake overhead and contention under concurrent load (called out in
   `api/main.py` as a future optimization).

## Baseline report

### Lab stub run (2026-07-17)

Environment: local macOS, Python 3.12, `scripts/load/stub_api.py` on `:8010`,
scenario `baseline` from `scenarios.yaml`. Stub delays: similar-posts **450ms**,
evaluate **12s** (proxy for provider-bound evaluate without billing Gemini).

| Route | N | Concurrency | p50 (ms) | p95 (ms) | Throughput (ok RPS) | Errors |
| ----- | - | ----------- | -------- | -------- | ------------------- | ------ |
| `GET /health` | 20 | 10 | 4.8 | 6.8 | 414 | 0 |
| `POST /similar-posts` | 40 | 8 | 455 | 459 | 17.5 | 0 |
| `POST /evaluate` | 6 | 2 | 12003 | 12005 | 0.167 | 0 |

Re-run and paste an updated JSON path when numbers change:

`python scripts/load/run_load_test.py --scenario baseline --base-url http://127.0.0.1:8010 --output …`

### Live staging (fill after first post-launch run)

| Route | N | Concurrency | p50 | p95 | RPS | Errors | Notes |
| ----- | - | ----------- | --- | --- | --- | ------ | ----- |
| similar-posts | 40 | 8 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | Needs #5/#8 signals |
| evaluate | 6 | 2 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | Watch Gemini quotas |

Keep raw JSON under `/tmp` or an internal ops bucket; do not commit secrets.

## Next-release targets (improvement plan)

Aligned with MVP SLOs from issue **#8** (availability / error budgets unchanged).
Latency and throughput below are the **next-release** bar after #21 baseline + #22
tuning.

| Metric | Current MVP / lab | Next release target | Owner issue |
| ------ | ----------------- | ------------------- | ----------- |
| similar-posts p95 | ≤ 2s SLO; stub ~0.5s | **≤ 1.0s** at 8 concurrent on Compose | #21 cache / pool follow-ups |
| evaluate p95 | ≤ 30s SLO; stub ~12s | **≤ 20s** at 2 concurrent | **#22** |
| similar-posts sustained throughput | stub ~17 ok RPS | **≥ 10 ok RPS** with <1% 5xx | #21 / capacity |
| evaluate sustained throughput | stub ~0.16 ok RPS | **≥ 0.5 ok RPS** (2 workers) without burning 2% 5xx budget | **#22** |
| Health p95 | ≤ 200ms | Keep **≤ 50ms** | ops |

### Recommended work order

1. Capture a **live** `baseline` JSON on staging; replace TBD rows above.
2. Add embedding memoization / short TTL cache for identical draft hashes.
3. Introduce a small psycopg connection pool for API handlers.
4. **#22:** per-agent timeouts, partial-result fallbacks, and slow-step telemetry
   so evaluate p95 moves from 30s → 20s without raising 5xx rate.
5. Re-run `similar-posts-steady` + `evaluate-mixed`; only then tighten Prometheus
   alert thresholds in #8 rules.

## Acceptance mapping

| #21 criterion | Location |
| ------------- | -------- |
| Reproducible load scripts | `scripts/load/run_load_test.py`, `scenarios.yaml`, `stub_api.py` |
| Baseline performance report | This document (lab stub + live TBD table) |
| Improvement plan with measurable targets | “Next-release targets” table + work order |
