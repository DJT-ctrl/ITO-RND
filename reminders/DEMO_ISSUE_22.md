# Demo — Issue #22 (orchestrator latency & resilience)

**Branch:** `feature/issue-22-orchestrator-latency`  
**Issue:** [intotheopen/intotheopen-backend#22](https://github.com/intotheopen/intotheopen-backend/issues/22)

| Criterion | Deliverable |
| --------- | ----------- |
| Latency profile documented | `docs/ops/ORCHESTRATOR_LATENCY.md` |
| Timeout/fallback policy | `AGENT_STEP_TIMEOUT_S` / `FINALIZE_TIMEOUT_S` + partial results |
| Improve p95 / error rate vs #21 | Caps ~22s worst-case; partial 200s instead of hangs |

```bash
pytest tests/test_orchestrator.py tests/test_orchestrator_latency.py -q
```
