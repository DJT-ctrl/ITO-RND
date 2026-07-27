# Orchestrator latency profile and timeout policy

Issue **#22** — bound slow evaluation steps, keep partial results on failure,
and move `/api/v1/evaluate` p95 toward the next-release target from **#21**
(≤ **20s** at 2 concurrent; MVP SLO remains ≤ 30s).

## Latency profile by stage

Wall clock for one `run_evaluation_cycle` call (Compose monolith, typical
warm Gemini):

| Stage | Steps (telemetry `step_id`) | Typical | Tail risk | Bounded by |
| ----- | --------------------------- | ------- | --------- | ---------- |
| **Retrieval** | `retrieval.embed_query`, `retrieval.vector_search` | 0.3–1.5s | Embedding provider spike | Provider / DB (no agent timeout) |
| **Setup** | voice profile, follower count, neighbor prediction, discoverability | 0.05–2s | Google Trends / DB | Offloaded via `asyncio.to_thread` |
| **Agents** | `agent.predictor`, `agent.<diagnostic>` (concurrent) | 3–12s | Slowest agent dominates | **`AGENT_STEP_TIMEOUT_S`** (default **12s**) |
| **Finalize** | variant engine (`finalize` hook) | 2–8s | Extra LLM / re-embed | **`FINALIZE_TIMEOUT_S`** (default **8s**) |

Agent stage wall time is approximately **max**(per-agent latency), not the
sum, because predictors and diagnostics run under `asyncio.gather`.

Budget sketch (defaults): retrieval+setup ≤ ~2s + agents ≤ 12s + finalize ≤ 8s
⇒ **≤ ~22s** worst-case when every stage saturates its bound — under the 30s
SLO and aligned with the #21 next-release p95 goal of **20s** for typical
runs (finalize often finishes faster than the cap).

## Timeout / fallback policy

| Setting | Default | Effect |
| ------- | ------- | ------ |
| `AGENT_STEP_TIMEOUTS_ENABLED` | `true` | Master switch |
| `AGENT_STEP_TIMEOUT_S` | `12` | Per agent `asyncio.wait_for` |
| `FINALIZE_TIMEOUT_S` | `8` | Caps variant finalize |

### On agent timeout

1. Telemetry step recorded with `status: "timeout"`.
2. Cycle continues (other agents keep their results).
3. **Predictor:** if neighbor prediction exists, return deterministic
   neighbor-weighted scores with `partial: true` (still a usable prediction).
4. **Diagnostics:** write a structured partial payload
   (`status: "timeout", partial: true, …`) instead of omitting the key.
5. Append a human-readable entry to `state.errors` (HTTP still **200**).

### On agent exception

Same partial-result path: diagnostics get `{status: "error", partial: true}`;
predictor prefers the deterministic neighbor fallback when available.

### On finalize timeout / failure

Agent results are **kept**. `state.errors` records `finalize: …`; variants may
be empty/incomplete. Previously a finalize exception could fail the whole
HTTP request.

Disable bounds (debug only): `AGENT_STEP_TIMEOUTS_ENABLED=false`.

## Expected improvement vs baseline (#21)

| Signal | Before #22 | After #22 (defaults) |
| ------ | ---------- | -------------------- |
| Evaluate **p95** | Unbounded Gemini hangs → can exceed 30s SLO | Agent+finalize caps keep most runs **≤ ~22s** wall |
| **5xx / client timeouts** | Hung evaluate → gateway/client abort | Partial **200** with `errors[]` + `partial` fields |
| Predictor availability | Hard fail → empty `predictor_result` | Deterministic neighbor fallback when possible |
| Telemetry | Errors only | Explicit `timeout` step status for Grafana / run JSON |

Re-validate with #21 scripts after deploy:

```bash
python scripts/load/run_load_test.py --scenario evaluate-mixed
```

Compare `latency_ms.p95` and error rate to the #21 live TBD table /
`docs/ops/LOAD_BASELINE.md` when that PR is merged.

## Acceptance mapping

| #22 criterion | Deliverable |
| ------------- | ----------- |
| Documented latency profile for orchestration stages | This document (table above) |
| Timeout/fallback policy implemented for slow steps | `config/settings.py` + `telemetry/instrument.py` + `agents/orchestrator.py` |
| Error rate and p95 latency improve versus baseline | Caps + partial 200s (table above); confirm with #21 load scenarios post-merge |
